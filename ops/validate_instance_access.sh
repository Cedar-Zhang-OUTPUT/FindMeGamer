#!/usr/bin/env bash
set -euo pipefail
if [[ "$-" == *x* ]]; then
  set +x
fi

fail() {
  echo "instance-access: $*" >&2
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

test_mode=false
config_file="/etc/find-me-gamer/app.env"
case "$#" in
  0) ;;
  2)
    [[ "$1" == "--test-mode" && -n "$2" ]] ||
      fail "usage: $0 [--test-mode /path/to/app.env]"
    test_mode=true
    config_file="$2"
    ;;
  *) fail "usage: $0 [--test-mode /path/to/app.env]" ;;
esac

if [[ "$dry_run" == "1" ]]; then
  FMG_S3_BUCKET="${FMG_S3_BUCKET:-find-me-gamer-example-bucket}"
  FMG_AWS_REGION="${FMG_AWS_REGION:-us-east-1}"
  FMG_ACQUISITION_PREFIX="${FMG_ACQUISITION_PREFIX:-acquisition/}"
  FMG_BACKUP_PREFIX="${FMG_BACKUP_PREFIX:-backups/}"
fi

file_mode() {
  if [[ "$(uname -s)" == "Darwin" ]]; then
    stat -f '%Lp' "$1"
  else
    stat -c '%a' "$1"
  fi
}

file_owner_id() {
  if [[ "$(uname -s)" == "Darwin" ]]; then
    stat -f '%u' "$1"
  else
    stat -c '%u' "$1"
  fi
}

load_protected_configuration() {
  local line
  local bucket_count=0
  local region_count=0
  local acquisition_count=0
  local backup_count=0
  local workspace_hash_count=0
  local workspace_hash_safe=0
  local workspace_hash_value=""
  local workspace_hash_inner=""

  while IFS= read -r line || [[ -n "$line" ]]; do
    case "$line" in
      FMG_S3_BUCKET=*)
        FMG_S3_BUCKET="${line#*=}"
        bucket_count=$((bucket_count + 1))
        ;;
      FMG_AWS_REGION=*)
        FMG_AWS_REGION="${line#*=}"
        region_count=$((region_count + 1))
        ;;
      FMG_ACQUISITION_PREFIX=*)
        FMG_ACQUISITION_PREFIX="${line#*=}"
        acquisition_count=$((acquisition_count + 1))
        ;;
      FMG_BACKUP_PREFIX=*)
        FMG_BACKUP_PREFIX="${line#*=}"
        backup_count=$((backup_count + 1))
        ;;
      WORKSPACE_ACCESS_KEY_HASH=*)
        workspace_hash_value="${line#*=}"
        workspace_hash_count=$((workspace_hash_count + 1))
        if [[ "$workspace_hash_value" == \'*\' ]]; then
          workspace_hash_inner="${workspace_hash_value:1:${#workspace_hash_value}-2}"
          if [[ "$workspace_hash_inner" =~ ^\$argon2id\$v=[0-9]+\$m=[0-9]+,t=[0-9]+,p=[0-9]+\$[A-Za-z0-9+/]+={0,2}\$[A-Za-z0-9+/]+={0,2}$ ]]; then
            workspace_hash_safe=1
          fi
          unset workspace_hash_inner
        fi
        unset workspace_hash_value
        ;;
    esac
  done <"$config_file"

  [[ "$bucket_count" == "1" && "$region_count" == "1" &&
    "$acquisition_count" == "1" && "$backup_count" == "1" ]] ||
    fail "protected app.env must contain each required S3 configuration key exactly once"
  [[ "$workspace_hash_count" == "1" && "$workspace_hash_safe" == "1" ]] ||
    fail "protected app.env Workspace hash must be one production Argon2id value enclosed in single quotes; edit only that value and retry"
}

if [[ "$dry_run" != "1" ]]; then
  [[ -f "$config_file" && ! -L "$config_file" ]] ||
    fail "$config_file must be a regular, non-symlink file"
  [[ "$(file_mode "$config_file")" == "600" ]] || fail "$config_file must have mode 0600"
  required_owner=0
  if [[ "$test_mode" == true ]]; then
    required_owner="$(id -u)"
  fi
  [[ "$(file_owner_id "$config_file")" == "$required_owner" ]] ||
    fail "$config_file must be owned by the required account"
  unset required_owner
  load_protected_configuration
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
repo_root="$(cd "$script_dir/.." && pwd)"

if [[ "$dry_run" == "1" ]]; then
  probe_key="${FMG_ACQUISITION_PREFIX}health/dry-run-probe"
  printf 'require one single-quoted production Argon2id Workspace hash without printing it\n'
  printf 'request an IMDSv2 token without logging its value\n'
  printf 'resolve the EC2 instance ID with that token\n'
  printf 'aws sts get-caller-identity --output json --region %q\n' "$FMG_AWS_REGION"
  printf 'aws ec2 describe-instances --instance-ids <resolved-instance-id> --region %q --output json\n' \
    "$FMG_AWS_REGION"
  printf 'require HttpTokens=required and HttpPutResponseHopLimit=2; print remediation only on mismatch\n'
  printf 'docker compose --project-directory %q --env-file %q config --quiet\n' \
    "$repo_root" "$config_file"
  printf 'docker compose --project-directory %q --env-file %q run --rm --no-deps -T api python <single-object-probe> %q %q %q\n' \
    "$repo_root" "$config_file" "$FMG_S3_BUCKET" "$FMG_AWS_REGION" "$probe_key"
  printf 'probe target: s3://%s/%s\n' "$FMG_S3_BUCKET" "$probe_key"
  exit 0
fi

for command_name in aws curl docker jq openssl; do
  command -v "$command_name" >/dev/null 2>&1 || fail "$command_name is required"
done
aws_version="$(aws --version 2>&1)" || fail "unable to inspect AWS CLI version"
[[ "$aws_version" == aws-cli/2.* ]] || fail "AWS CLI v2 is required"

if ! docker compose --project-directory "$repo_root" --env-file "$config_file" \
  config --quiet; then
  fail "protected app.env cannot render the production Compose configuration"
fi

metadata_token=""
if ! metadata_token="$(
  curl -fsS --connect-timeout 2 --max-time 5 -X PUT \
    -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' \
    http://169.254.169.254/latest/api/token
)"; then
  fail "unable to obtain an IMDSv2 token"
fi
[[ -n "$metadata_token" ]] || fail "IMDSv2 returned an empty token"

instance_id=""
if ! instance_id="$(
  curl -fsS --connect-timeout 2 --max-time 5 \
    -H "X-aws-ec2-metadata-token: $metadata_token" \
    http://169.254.169.254/latest/meta-data/instance-id
)"; then
  unset metadata_token
  fail "unable to resolve the EC2 instance ID through IMDSv2"
fi
unset metadata_token
[[ "$instance_id" =~ ^i-[0-9a-f]{8,17}$ ]] || fail "IMDSv2 returned an invalid instance ID"

identity_document=""
if ! identity_document="$(aws sts get-caller-identity --output json --region "$FMG_AWS_REGION")"; then
  fail "unable to resolve the AWS identity; verify the EC2 Instance Role"
fi
identity_arn="$(jq -er '.Arn | strings' <<<"$identity_document")" ||
  fail "AWS identity response did not contain an ARN"
if [[ ! "$identity_arn" =~ ^arn:aws[^:]*:sts::[0-9]{12}:assumed-role/[^/]+/$instance_id$ ]]; then
  fail "AWS CLI is not using this EC2 instance's assumed Instance Role"
fi
unset identity_document identity_arn

metadata_options=""
if ! metadata_options="$(
  aws ec2 describe-instances --instance-ids "$instance_id" \
    --region "$FMG_AWS_REGION" \
    --query 'Reservations[0].Instances[0].MetadataOptions' --output json
)"; then
  fail "unable to inspect metadata options for $instance_id; ensure the Instance Role permits ec2:DescribeInstances"
fi

if ! jq -e '
  .HttpTokens == "required" and
  .HttpPutResponseHopLimit == 2 and
  .HttpEndpoint == "enabled"
' >/dev/null <<<"$metadata_options"; then
  printf 'aws ec2 modify-instance-metadata-options --instance-id "%s" --http-tokens required --http-put-response-hop-limit 2\n' \
    "$instance_id" >&2
  fail "EC2 metadata options must require IMDSv2 with hop limit 2"
fi
unset metadata_options

probe_id="$(openssl rand -hex 32)" || fail "unable to generate the S3 probe key"
[[ "$probe_id" =~ ^[0-9a-f]{64}$ ]] || fail "the generated S3 probe key is invalid"
probe_key="${FMG_ACQUISITION_PREFIX}health/${probe_id}"
unset probe_id

probe_program="$(cat <<'PYTHON'
import secrets
import sys

import boto3


bucket, region, key = sys.argv[1:]
client = boto3.client("s3", region_name=region)
payload = secrets.token_bytes(32)
try:
    client.put_object(Bucket=bucket, Key=key, Body=payload)
    downloaded = client.get_object(Bucket=bucket, Key=key)["Body"].read()
    if not secrets.compare_digest(downloaded, payload):
        raise RuntimeError("S3 probe content verification failed")
finally:
    client.delete_object(Bucket=bucket, Key=key)
PYTHON
)"

if ! docker compose --project-directory "$repo_root" --env-file "$config_file" \
  run --rm --no-deps -T api \
  python -c "$probe_program" "$FMG_S3_BUCKET" "$FMG_AWS_REGION" "$probe_key"; then
  fail "the one-object S3 write/read/delete probe failed"
fi
unset probe_program probe_key instance_id
printf 'Instance Role, IMDSv2, and the isolated S3 access probe are valid.\n'
