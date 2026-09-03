#!/usr/bin/env bash
set -euo pipefail
if [[ "$-" == *x* ]]; then
  set +x
fi

fail() {
  echo "s3-lifecycle: $*" >&2
  exit 1
}

require_environment() {
  local name="$1"
  [[ -n "${!name:-}" ]] || fail "$name is required"
}

validate_prefix() {
  local name="$1"
  local value="${!name}"
  [[ "$value" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*/$ ]] ||
    fail "$name must be a nonempty slash-terminated key prefix"
  [[ "$value" != /* && "$value" != *'//'* && "$value" != *'/../'* &&
    "$value" != '../'* && "$value" != *'/./'* && "$value" != './'* ]] ||
    fail "$name must be relative and normalized"
}

dry_run="${FMG_DRY_RUN:-0}"
[[ "$dry_run" == "0" || "$dry_run" == "1" ]] || fail "FMG_DRY_RUN must be 0 or 1"

if [[ "$dry_run" == "1" ]]; then
  FMG_S3_BUCKET="${FMG_S3_BUCKET:-find-me-gamer-example-bucket}"
  FMG_AWS_REGION="${FMG_AWS_REGION:-us-east-1}"
  FMG_ACQUISITION_PREFIX="${FMG_ACQUISITION_PREFIX:-acquisition/}"
  FMG_BACKUP_PREFIX="${FMG_BACKUP_PREFIX:-backups/}"
fi

require_environment FMG_S3_BUCKET
require_environment FMG_AWS_REGION
require_environment FMG_ACQUISITION_PREFIX
require_environment FMG_BACKUP_PREFIX

[[ "$FMG_S3_BUCKET" =~ ^[a-z0-9][a-z0-9.-]*[a-z0-9]$ ]] ||
  fail "FMG_S3_BUCKET is invalid"
[[ "$FMG_AWS_REGION" =~ ^[a-z0-9-]+$ ]] || fail "FMG_AWS_REGION is invalid"
validate_prefix FMG_ACQUISITION_PREFIX
validate_prefix FMG_BACKUP_PREFIX

if [[ "$FMG_ACQUISITION_PREFIX" == "$FMG_BACKUP_PREFIX" ||
  "$FMG_ACQUISITION_PREFIX" == "$FMG_BACKUP_PREFIX"* ||
  "$FMG_BACKUP_PREFIX" == "$FMG_ACQUISITION_PREFIX"* ]]; then
  fail "acquisition and backup prefixes must be distinct and non-overlapping"
fi

if [[ -n "${AWS_ACCESS_KEY_ID:-}" || -n "${AWS_SECRET_ACCESS_KEY:-}" ]]; then
  fail "static AWS credentials are forbidden; use the EC2 Instance Role"
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
template="$script_dir/s3-lifecycle.json"
[[ -f "$template" ]] || fail "$template is required"
command -v jq >/dev/null 2>&1 || fail "jq is required"

render_managed_rules() {
  jq --arg acquisition "$FMG_ACQUISITION_PREFIX" \
    --arg backups "$FMG_BACKUP_PREFIX" '
      .Rules
      | map(
          if .ID == "FindMeGamerAcquisition30Days" then
            .Filter.Prefix = $acquisition
          elif .ID == "FindMeGamerBackups30Days" then
            .Filter.Prefix = $backups
          else . end
        )
    ' "$template"
}

managed_rules="$(render_managed_rules)" || fail "unable to render lifecycle rules"
if ! jq -e '
  (length == 2) and
  ([.[].ID] | sort == ["FindMeGamerAcquisition30Days", "FindMeGamerBackups30Days"]) and
  ([.[].Status] | all(. == "Enabled")) and
  ([.[].Expiration.Days] | all(. == 30))
' >/dev/null <<<"$managed_rules"; then
  fail "managed lifecycle template is invalid"
fi

if [[ "$dry_run" == "1" ]]; then
  printf 'aws s3api get-bucket-lifecycle-configuration --bucket %q --region %q\n' \
    "$FMG_S3_BUCKET" "$FMG_AWS_REGION"
  printf 'preserve unrelated lifecycle rules; replace only acquisition prefix %q and backup prefix %q\n' \
    "$FMG_ACQUISITION_PREFIX" "$FMG_BACKUP_PREFIX"
  printf 'aws s3api put-bucket-lifecycle-configuration --bucket %q --region %q --lifecycle-configuration <merged-rules-document>\n' \
    "$FMG_S3_BUCKET" "$FMG_AWS_REGION"
  exit 0
fi

command -v aws >/dev/null 2>&1 || fail "AWS CLI v2 is required"
aws_version="$(aws --version 2>&1)" || fail "unable to inspect AWS CLI version"
[[ "$aws_version" == aws-cli/2.* ]] || fail "AWS CLI v2 is required"

temp_dir="$(mktemp -d)"
cleanup() {
  rm -rf -- "$temp_dir"
}
trap cleanup EXIT
current_document="$temp_dir/current.json"
get_error="$temp_dir/get.err"
merged_document="$temp_dir/merged.json"

if aws s3api get-bucket-lifecycle-configuration \
  --bucket "$FMG_S3_BUCKET" --region "$FMG_AWS_REGION" \
  >"$current_document" 2>"$get_error"; then
  jq -e '.Rules | type == "array"' "$current_document" >/dev/null ||
    fail "current lifecycle response does not contain a Rules array"
elif grep -Fq 'NoSuchLifecycleConfiguration' "$get_error"; then
  printf '{"Rules":[]}\n' >"$current_document"
else
  cat "$get_error" >&2
  fail "unable to read current bucket lifecycle configuration; no update was attempted"
fi

if ! jq --argjson managed "$managed_rules" '
  {
    Rules: (
      [.Rules[] | select(
        .ID != "FindMeGamerAcquisition30Days" and
        .ID != "FindMeGamerBackups30Days"
      )] + $managed
    )
  }
' "$current_document" >"$merged_document"; then
  fail "unable to merge lifecycle configuration"
fi

aws s3api put-bucket-lifecycle-configuration \
  --bucket "$FMG_S3_BUCKET" --region "$FMG_AWS_REGION" \
  --lifecycle-configuration "file://$merged_document"
printf 'Applied the two managed 30-day lifecycle rules to s3://%s/.\n' "$FMG_S3_BUCKET"
