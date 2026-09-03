#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
lifecycle_document="$repo_root/ops/s3-lifecycle.json"
lifecycle_script="$repo_root/ops/configure_s3_lifecycle.sh"
access_script="$repo_root/ops/validate_instance_access.sh"

fail() {
  echo "s3 configuration test: $*" >&2
  exit 1
}

[[ -f "$lifecycle_document" ]] || fail "ops/s3-lifecycle.json is required"
[[ -x "$lifecycle_script" ]] || fail "ops/configure_s3_lifecycle.sh is required and executable"
[[ -x "$access_script" ]] || fail "ops/validate_instance_access.sh is required and executable"

jq -e '
  (.Rules | length == 2) and
  ([.Rules[].ID] | sort == ["FindMeGamerAcquisition30Days", "FindMeGamerBackups30Days"]) and
  ([.Rules[].Status] | all(. == "Enabled")) and
  ([.Rules[].Expiration.Days] | all(. == 30)) and
  ([.Rules[].Filter.Prefix] | sort == ["acquisition/", "backups/"]) and
  ([.Rules[].Filter.Prefix] | all(endswith("/")))
' "$lifecycle_document" >/dev/null

test_root="$(mktemp -d)"
cleanup() {
  rm -rf -- "$test_root"
}
trap cleanup EXIT

fake_bin="$test_root/bin"
fake_python="$test_root/python"
mkdir -p "$fake_bin" "$fake_python" "$test_root/home"
aws_log="$test_root/aws.log"
curl_log="$test_root/curl.log"
docker_log="$test_root/docker.log"
probe_log="$test_root/probe.log"
put_document="$test_root/put.json"

cat >"$fake_bin/aws" <<'FAKE_AWS'
#!/usr/bin/env bash
set -euo pipefail
printf '%q ' "$@" >>"$FMG_FAKE_AWS_LOG"
printf '\n' >>"$FMG_FAKE_AWS_LOG"

case "${1:-} ${2:-}" in
  "--version ")
    echo 'aws-cli/2.31.0 Python/3.13.7 Darwin/25.0 source/arm64'
    ;;
  "s3api get-bucket-lifecycle-configuration")
    case "${FMG_FAKE_LIFECYCLE_MODE:-success}" in
      success) cat "$FMG_FAKE_CURRENT_LIFECYCLE" ;;
      missing)
        echo "An error occurred (NoSuchLifecycleConfiguration) when calling the GetBucketLifecycleConfiguration operation" >&2
        exit 254
        ;;
      failure)
        echo "An error occurred (AccessDenied) when calling the GetBucketLifecycleConfiguration operation" >&2
        exit 254
        ;;
    esac
    ;;
  "s3api put-bucket-lifecycle-configuration")
    document=""
    while (($#)); do
      if [[ "$1" == "--lifecycle-configuration" ]]; then
        document="${2#file://}"
        break
      fi
      shift
    done
    [[ -n "$document" ]]
    cp "$document" "$FMG_FAKE_PUT_DOCUMENT"
    ;;
  "sts get-caller-identity")
    printf '%s\n' "${FMG_FAKE_IDENTITY_JSON:?}"
    ;;
  "ec2 describe-instances")
    if [[ "${FMG_FAKE_METADATA_FAILURE:-0}" == "1" ]]; then
      echo "An error occurred (UnauthorizedOperation) when calling DescribeInstances" >&2
      exit 254
    fi
    printf '%s\n' "${FMG_FAKE_METADATA_JSON:?}"
    ;;
  *)
    echo "unexpected aws command: $*" >&2
    exit 64
    ;;
esac
FAKE_AWS

cat >"$fake_bin/curl" <<'FAKE_CURL'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == *"/latest/api/token"* ]]; then
  echo "PUT token" >>"$FMG_FAKE_CURL_LOG"
  printf '%s' 'test-metadata-token'
elif [[ "$*" == *"/latest/meta-data/instance-id"* ]]; then
  echo "GET instance-id with-token" >>"$FMG_FAKE_CURL_LOG"
  printf '%s' 'i-0123456789abcdef0'
else
  echo "unexpected curl command" >&2
  exit 64
fi
FAKE_CURL

cat >"$fake_bin/openssl" <<'FAKE_OPENSSL'
#!/usr/bin/env bash
set -euo pipefail
[[ "$*" == "rand -hex 32" ]]
printf '%s\n' '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef'
FAKE_OPENSSL

cat >"$fake_bin/docker" <<'FAKE_DOCKER'
#!/usr/bin/env bash
set -euo pipefail
printf '%q ' "$@" >>"$FMG_FAKE_DOCKER_LOG"
printf '\n' >>"$FMG_FAKE_DOCKER_LOG"
[[ "$1" == "compose" ]]
shift
project_directory=""
env_file=""
while [[ "${1:-}" == --* ]]; do
  case "$1" in
    --project-directory)
      project_directory="$2"
      shift 2
      ;;
    --env-file)
      env_file="$2"
      shift 2
      ;;
    *) exit 64 ;;
  esac
done
[[ "$project_directory" == "$FMG_FAKE_EXPECTED_PROJECT_DIRECTORY" &&
  "$env_file" == "$FMG_FAKE_EXPECTED_ENV_FILE" ]]
if [[ "$1" == "config" ]]; then
  [[ "$2" == "--quiet" && $# == 2 ]]
  [[ "${FMG_FAKE_COMPOSE_CONFIG_FAILURE:-0}" != "1" ]] || exit 65
  exit 0
fi
[[ "$1" == "run" ]]
shift
[[ "$1" == "--rm" && "$2" == "--no-deps" && "$3" == "-T" && "$4" == "api" ]]
shift 4
[[ "$1" == "python" && "$2" == "-c" ]]
program="$3"
shift 3
PYTHONPATH="$FMG_FAKE_PYTHONPATH" /usr/bin/python3 -c "$program" "$@"
FAKE_DOCKER

cat >"$fake_python/boto3.py" <<'FAKE_BOTO'
import os


class Body:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return self.payload


class S3:
    def __init__(self):
        self.payload = None

    def record(self, operation, bucket, key):
        with open(os.environ["FMG_FAKE_PROBE_LOG"], "a", encoding="utf-8") as log:
            log.write(f"{operation} {bucket} {key}\n")

    def put_object(self, *, Bucket, Key, Body):
        self.record("put", Bucket, Key)
        self.payload = Body
        if os.environ.get("FMG_FAKE_PROBE_FAILURE") == "put":
            raise RuntimeError("simulated put failure")

    def get_object(self, *, Bucket, Key):
        self.record("get", Bucket, Key)
        if os.environ.get("FMG_FAKE_PROBE_FAILURE") == "get":
            raise RuntimeError("simulated get failure")
        return {"Body": Body(self.payload)}

    def delete_object(self, *, Bucket, Key):
        self.record("delete", Bucket, Key)


def client(service, *, region_name):
    assert service == "s3"
    assert region_name == "us-west-2"
    return S3()
FAKE_BOTO

chmod +x "$fake_bin/aws" "$fake_bin/curl" "$fake_bin/docker" "$fake_bin/openssl"

current_lifecycle="$test_root/current.json"
cat >"$current_lifecycle" <<'JSON'
{
  "Rules": [
    {
      "ID": "KeepUnrelatedArchiveRule",
      "Status": "Enabled",
      "Filter": {"And": {"Prefix": "legal/", "Tags": [{"Key": "hold", "Value": "yes"}]}},
      "Transitions": [{"Days": 90, "StorageClass": "GLACIER"}]
    },
    {
      "ID": "FindMeGamerAcquisition30Days",
      "Status": "Disabled",
      "Filter": {"Prefix": "old-acquisition/"},
      "Expiration": {"Days": 365}
    },
    {
      "ID": "FindMeGamerBackups30Days",
      "Status": "Disabled",
      "Filter": {"Prefix": "old-backups/"},
      "Expiration": {"Days": 365}
    }
  ]
}
JSON

base_environment=(
  PATH="$fake_bin:/usr/bin:/bin"
  HOME="$test_root/home"
  FMG_S3_BUCKET=company-demo-artifacts
  FMG_AWS_REGION=us-west-2
  FMG_ACQUISITION_PREFIX=import/acquisition/
  FMG_BACKUP_PREFIX=database/backups/
  FMG_FAKE_AWS_LOG="$aws_log"
  FMG_FAKE_CURRENT_LIFECYCLE="$current_lifecycle"
  FMG_FAKE_PUT_DOCUMENT="$put_document"
)

: >"$aws_log"
env -i "${base_environment[@]}" FMG_FAKE_LIFECYCLE_MODE=success \
  "$lifecycle_script" >/dev/null
jq -e '
  (.Rules | length == 3) and
  ([.Rules[] | select(.ID == "KeepUnrelatedArchiveRule")] == [{
    "ID": "KeepUnrelatedArchiveRule",
    "Status": "Enabled",
    "Filter": {"And": {"Prefix": "legal/", "Tags": [{"Key": "hold", "Value": "yes"}]}},
    "Transitions": [{"Days": 90, "StorageClass": "GLACIER"}]
  }]) and
  ([.Rules[] | select(.ID == "FindMeGamerAcquisition30Days")] | length == 1) and
  ([.Rules[] | select(.ID == "FindMeGamerAcquisition30Days")][0] |
    .Status == "Enabled" and .Expiration.Days == 30 and
    .Filter.Prefix == "import/acquisition/") and
  ([.Rules[] | select(.ID == "FindMeGamerBackups30Days")] | length == 1) and
  ([.Rules[] | select(.ID == "FindMeGamerBackups30Days")][0] |
    .Status == "Enabled" and .Expiration.Days == 30 and
    .Filter.Prefix == "database/backups/")
' "$put_document" >/dev/null
[[ "$(grep -c '^s3api get-bucket-lifecycle-configuration ' "$aws_log")" == "1" ]]
[[ "$(grep -c '^s3api put-bucket-lifecycle-configuration ' "$aws_log")" == "1" ]]

: >"$aws_log"
rm -f "$put_document"
env -i "${base_environment[@]}" FMG_FAKE_LIFECYCLE_MODE=missing \
  "$lifecycle_script" >/dev/null
jq -e '.Rules | length == 2' "$put_document" >/dev/null

: >"$aws_log"
rm -f "$put_document"
if env -i "${base_environment[@]}" FMG_FAKE_LIFECYCLE_MODE=failure \
  "$lifecycle_script" >"$test_root/lifecycle-failure.out" 2>"$test_root/lifecycle-failure.err"; then
  fail "lifecycle configuration continued after a failed Get"
fi
[[ ! -e "$put_document" ]]
! grep -q '^s3api put-bucket-lifecycle-configuration ' "$aws_log"

for unsafe_pair in \
  'same/ same/' \
  'parent/ parent/child/' \
  '../escape/ backups/'; do
  read -r acquisition_prefix backup_prefix <<<"$unsafe_pair"
  if env -i "${base_environment[@]}" \
    FMG_ACQUISITION_PREFIX="$acquisition_prefix" FMG_BACKUP_PREFIX="$backup_prefix" \
    "$lifecycle_script" >/dev/null 2>&1; then
    fail "lifecycle accepted unsafe or overlapping prefixes"
  fi
done

identity_json='{"Account":"123456789012","Arn":"arn:aws:sts::123456789012:assumed-role/FindMeGamerEc2Role/i-0123456789abcdef0","UserId":"AROATEST:i-0123456789abcdef0"}'
metadata_json='{"HttpTokens":"required","HttpPutResponseHopLimit":2,"HttpEndpoint":"enabled"}'
protected_env="$test_root/app.env"
dotenv_execution_marker="$test_root/dotenv-was-executed"
workspace_hash='$argon2id$v=19$m=65536,t=3,p=4$cHJvZHVjdGlvbi1zYWx0$cHJvZHVjdGlvbi1oYXNoLWJ5dGVz'
cat >"$protected_env" <<EOF
SERVICE_DOMAIN=demo.find-me-gamer.example.invalid
BACKEND_SUBNET=172.30.0.0/24
POSTGRES_DB=find_me_gamer
POSTGRES_USER=find_me_gamer
POSTGRES_PASSWORD=protected-password-canary-never-log
WORKSPACE_ACCESS_KEY_HASH='$workspace_hash'
FMG_AWS_REGION=us-west-2
FMG_S3_BUCKET=company-demo-artifacts
FMG_BACKUP_PREFIX=database/backups/
FMG_ACQUISITION_PREFIX=import/acquisition/
IGNORED_COMMAND=\$(touch "$dotenv_execution_marker")
EOF
chmod 0600 "$protected_env"
access_environment=(
  "${base_environment[@]}"
  FMG_FAKE_CURL_LOG="$curl_log"
  FMG_FAKE_DOCKER_LOG="$docker_log"
  FMG_FAKE_PROBE_LOG="$probe_log"
  FMG_FAKE_PYTHONPATH="$fake_python"
  FMG_FAKE_IDENTITY_JSON="$identity_json"
  FMG_FAKE_METADATA_JSON="$metadata_json"
  FMG_FAKE_EXPECTED_PROJECT_DIRECTORY="$repo_root"
  FMG_FAKE_EXPECTED_ENV_FILE="$protected_env"
)

: >"$aws_log"; : >"$curl_log"; : >"$docker_log"; : >"$probe_log"
if ! env -i "${access_environment[@]}" \
  FMG_S3_BUCKET= FMG_AWS_REGION= FMG_ACQUISITION_PREFIX= FMG_BACKUP_PREFIX= \
  "$access_script" --test-mode "$protected_env" \
  >"$test_root/access-success.out" 2>"$test_root/access-success.err"; then
  fail "validator must load the protected env and render Compose before the probe"
fi
expected_key='import/acquisition/health/0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef'
[[ "$(grep -c "^put company-demo-artifacts $expected_key$" "$probe_log")" == "1" ]]
[[ "$(grep -c "^get company-demo-artifacts $expected_key$" "$probe_log")" == "1" ]]
[[ "$(grep -c "^delete company-demo-artifacts $expected_key$" "$probe_log")" == "1" ]]
[[ "$(grep -c ' config --quiet ' "$docker_log")" == "1" ]]
[[ "$(grep -c ' run --rm --no-deps -T api ' "$docker_log")" == "1" ]]
[[ "$(grep -c -- "--env-file $protected_env " "$docker_log")" == "2" ]]
[[ "$(wc -l <"$docker_log" | tr -d ' ')" == "2" ]]
grep -q ' config --quiet ' < <(sed -n '1p' "$docker_log")
grep -q ' run --rm --no-deps -T api ' < <(sed -n '2p' "$docker_log")
[[ ! -e "$dotenv_execution_marker" ]]
! grep -Fq 'protected-password-canary-never-log' \
  "$test_root/access-success.out" "$test_root/access-success.err" "$docker_log"
! grep -Fq "$workspace_hash" \
  "$test_root/access-success.out" "$test_root/access-success.err" "$docker_log"
! grep -Fq 'test-metadata-token' "$access_script" "$aws_log" "$curl_log" "$docker_log"

: >"$aws_log"; : >"$curl_log"; : >"$docker_log"; : >"$probe_log"
env -i "${access_environment[@]}" \
  FMG_S3_BUCKET=inherited-wrong-bucket FMG_AWS_REGION=eu-west-1 \
  FMG_ACQUISITION_PREFIX=inherited/acquisition/ FMG_BACKUP_PREFIX=inherited/backups/ \
  "$access_script" --test-mode "$protected_env" >/dev/null
[[ "$(grep -c "^put company-demo-artifacts $expected_key$" "$probe_log")" == "1" ]]
! grep -Fq 'inherited-wrong-bucket' "$docker_log" "$probe_log"

: >"$probe_log"; : >"$docker_log"
if env -i "${access_environment[@]}" FMG_FAKE_PROBE_FAILURE=get \
  "$access_script" --test-mode "$protected_env" \
  >"$test_root/probe-failure.out" 2>"$test_root/probe-failure.err"; then
  fail "access validation accepted a failed read probe"
fi
[[ "$(grep -c "^put company-demo-artifacts $expected_key$" "$probe_log")" == "1" ]]
[[ "$(grep -c "^get company-demo-artifacts $expected_key$" "$probe_log")" == "1" ]]
[[ "$(grep -c "^delete company-demo-artifacts $expected_key$" "$probe_log")" == "1" ]]

: >"$aws_log"; : >"$curl_log"; : >"$docker_log"
if env -i "${access_environment[@]}" AWS_ACCESS_KEY_ID=forbidden \
  "$access_script" --test-mode "$protected_env" \
  >"$test_root/static.out" 2>"$test_root/static.err"; then
  fail "access validation accepted static credentials"
fi
grep -Fq 'static AWS credentials are forbidden' "$test_root/static.err"
[[ ! -s "$aws_log" && ! -s "$curl_log" && ! -s "$docker_log" ]]

legacy_env="$test_root/legacy-unquoted.env"
sed "s#^WORKSPACE_ACCESS_KEY_HASH=.*#WORKSPACE_ACCESS_KEY_HASH=$workspace_hash#" \
  "$protected_env" >"$legacy_env"
chmod 0600 "$legacy_env"
: >"$aws_log"; : >"$curl_log"; : >"$docker_log"
if env -i "${access_environment[@]}" FMG_FAKE_EXPECTED_ENV_FILE="$legacy_env" \
  "$access_script" --test-mode "$legacy_env" \
  >"$test_root/legacy.out" 2>"$test_root/legacy.err"; then
  fail "validator accepted a legacy unquoted Workspace hash"
fi
grep -Fq 'single quotes' "$test_root/legacy.err"
[[ ! -s "$aws_log" && ! -s "$curl_log" && ! -s "$docker_log" ]]
! grep -Fq "$workspace_hash" "$test_root/legacy.out" "$test_root/legacy.err"

missing_key_env="$test_root/missing-key.env"
grep -v '^FMG_BACKUP_PREFIX=' "$protected_env" >"$missing_key_env"
chmod 0600 "$missing_key_env"
unsafe_mode_env="$test_root/unsafe-mode.env"
cp "$protected_env" "$unsafe_mode_env"
chmod 0644 "$unsafe_mode_env"
overlap_env="$test_root/overlap.env"
sed 's#^FMG_BACKUP_PREFIX=.*#FMG_BACKUP_PREFIX=import/#' "$protected_env" >"$overlap_env"
chmod 0600 "$overlap_env"
malformed_hash_env="$test_root/malformed-hash.env"
sed "s#^WORKSPACE_ACCESS_KEY_HASH=.*#WORKSPACE_ACCESS_KEY_HASH='not-an-argon2id-hash'#" \
  "$protected_env" >"$malformed_hash_env"
chmod 0600 "$malformed_hash_env"
symlink_env="$test_root/symlink.env"
ln -s "$protected_env" "$symlink_env"

for invalid_env in \
  "$test_root/does-not-exist.env" \
  "$missing_key_env" \
  "$unsafe_mode_env" \
  "$overlap_env" \
  "$malformed_hash_env" \
  "$symlink_env"; do
  : >"$aws_log"; : >"$curl_log"; : >"$docker_log"
  if env -i "${access_environment[@]}" \
    "$access_script" --test-mode "$invalid_env" \
    >"$test_root/invalid-config.out" 2>"$test_root/invalid-config.err"; then
    fail "access validation accepted missing, malformed, or unsafe protected config"
  fi
  [[ ! -s "$aws_log" && ! -s "$curl_log" && ! -s "$docker_log" ]]
  ! grep -Fq 'protected-password-canary-never-log' \
    "$test_root/invalid-config.out" "$test_root/invalid-config.err"
done

: >"$aws_log"; : >"$curl_log"; : >"$docker_log"
if env -i "${access_environment[@]}" FMG_FAKE_COMPOSE_CONFIG_FAILURE=1 \
  "$access_script" --test-mode "$protected_env" \
  >"$test_root/compose-config.out" 2>"$test_root/compose-config.err"; then
  fail "access validation continued after Compose render failed"
fi
[[ "$(grep -c ' config --quiet ' "$docker_log")" == "1" ]]
! grep -q ' run --rm --no-deps -T api ' "$docker_log"
[[ ! -s "$curl_log" ]]

: >"$aws_log"; : >"$docker_log"
if env -i "${access_environment[@]}" \
  FMG_FAKE_IDENTITY_JSON='{"Account":"123456789012","Arn":"arn:aws:iam::123456789012:user/operator","UserId":"AIDATEST"}' \
  "$access_script" --test-mode "$protected_env" \
  >"$test_root/identity.out" 2>"$test_root/identity.err"; then
  fail "access validation accepted a non-Instance-Role identity"
fi
grep -Fq "not using this EC2 instance's assumed Instance Role" "$test_root/identity.err"
! grep -q ' run --rm --no-deps -T api ' "$docker_log"

: >"$aws_log"; : >"$docker_log"
if env -i "${access_environment[@]}" \
  FMG_FAKE_METADATA_JSON='{"HttpTokens":"optional","HttpPutResponseHopLimit":1,"HttpEndpoint":"enabled"}' \
  "$access_script" --test-mode "$protected_env" \
  >"$test_root/metadata.out" 2>"$test_root/metadata.err"; then
  fail "access validation accepted unsafe metadata options"
fi
grep -Fq 'aws ec2 modify-instance-metadata-options --instance-id "i-0123456789abcdef0" --http-tokens required --http-put-response-hop-limit 2' \
  "$test_root/metadata.err"
! grep -q 'modify-instance-metadata-options' "$aws_log"
! grep -q ' run --rm --no-deps -T api ' "$docker_log"

: >"$aws_log"; : >"$docker_log"
if env -i "${access_environment[@]}" FMG_FAKE_METADATA_FAILURE=1 \
  "$access_script" --test-mode "$protected_env" \
  >"$test_root/permission.out" 2>"$test_root/permission.err"; then
  fail "access validation continued without metadata inspection permission"
fi
grep -Fq 'ensure the Instance Role permits ec2:DescribeInstances' "$test_root/permission.err"
! grep -q ' run --rm --no-deps -T api ' "$docker_log"

: >"$aws_log"; : >"$curl_log"; : >"$docker_log"
lifecycle_plan="$(env -i PATH="$fake_bin:/usr/bin:/bin" HOME="$test_root/home" FMG_DRY_RUN=1 \
  FMG_FAKE_AWS_LOG="$aws_log" "$lifecycle_script")"
grep -Fq 'find-me-gamer-example-bucket' <<<"$lifecycle_plan"
grep -Fq 'acquisition/' <<<"$lifecycle_plan"
grep -Fq 'backups/' <<<"$lifecycle_plan"
access_plan="$(env -i PATH="$fake_bin:/usr/bin:/bin" HOME="$test_root/home" FMG_DRY_RUN=1 \
  FMG_FAKE_AWS_LOG="$aws_log" FMG_FAKE_CURL_LOG="$curl_log" \
  FMG_FAKE_DOCKER_LOG="$docker_log" "$access_script")"
grep -Fq 'find-me-gamer-example-bucket/acquisition/health/' <<<"$access_plan"
grep -Fq -- '--env-file /etc/find-me-gamer/app.env config --quiet' <<<"$access_plan"
grep -Fq -- '--env-file /etc/find-me-gamer/app.env run --rm --no-deps -T api' <<<"$access_plan"
[[ ! -s "$aws_log" && ! -s "$curl_log" && ! -s "$docker_log" ]]

echo "s3 configuration test: PASS"
