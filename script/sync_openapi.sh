#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
BACKEND_SCHEMA="$BACKEND_DIR/openapi.json"
PACKAGE_DIR="$ROOT_DIR/macos"
TARGET_DIR="$PACKAGE_DIR/Sources/FindMeGamerAPI"
TARGET_SCHEMA="$TARGET_DIR/openapi.json"
NORMALIZER="$ROOT_DIR/script/normalize_openapi_for_swift.py"
TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/find-me-gamer-openapi.XXXXXX")"
NETWORK_GUARD="$TEMP_DIR/network-guard"
NORMALIZED_SCHEMA="$TEMP_DIR/openapi.json.normalized"
SCHEMA_BACKUP="$TEMP_DIR/openapi.json.previous"
SCHEMA_REPLACED=0
SCHEMA_PREEXISTED=0

cleanup() {
  local status=$?
  set +e
  if [[ "$status" -ne 0 && "$SCHEMA_REPLACED" -eq 1 ]]; then
    local restore_path="$TARGET_DIR/.openapi.json.restore.$$"
    if [[ "$SCHEMA_PREEXISTED" -eq 1 ]]; then
      cp "$SCHEMA_BACKUP" "$restore_path"
      mv -f "$restore_path" "$TARGET_SCHEMA"
    else
      rm -f "$TARGET_SCHEMA"
    fi
  fi
  rm -rf "$TEMP_DIR"
  return "$status"
}
trap cleanup EXIT

mkdir -p "$NETWORK_GUARD"
cat >"$NETWORK_GUARD/sitecustomize.py" <<'PYTHON'
import socket


def blocked(*args, **kwargs):
    raise AssertionError("OpenAPI export attempted network access")


class GuardedSocket(socket.socket):
    def connect(self, *args, **kwargs):
        blocked()

    def connect_ex(self, *args, **kwargs):
        blocked()


socket.socket = GuardedSocket
socket.create_connection = blocked
socket.getaddrinfo = blocked
socket.gethostbyname = blocked
socket.gethostbyname_ex = blocked
PYTHON

run_local_exporter() {
  local python=$1
  (
    cd "$BACKEND_DIR"
    PYTHONPATH="$NETWORK_GUARD${PYTHONPATH:+:$PYTHONPATH}" \
      "$python" scripts/export_openapi.py
  )
}

if [[ -n "${BACKEND_PYTHON:-}" ]]; then
  if [[ "$BACKEND_PYTHON" == */* ]]; then
    [[ -x "$BACKEND_PYTHON" ]] || {
      echo "BACKEND_PYTHON is not executable" >&2
      exit 1
    }
    backend_python="$BACKEND_PYTHON"
  else
    backend_python="$(command -v "$BACKEND_PYTHON")" || {
      echo "BACKEND_PYTHON command was not found" >&2
      exit 1
    }
  fi
  run_local_exporter "$backend_python"
elif [[ -x "$BACKEND_DIR/.venv/bin/python" ]]; then
  run_local_exporter "$BACKEND_DIR/.venv/bin/python"
else
  command -v docker >/dev/null || {
    echo "OpenAPI export requires BACKEND_PYTHON, backend/.venv, or Docker" >&2
    exit 1
  }
  docker compose --file "$BACKEND_DIR/compose.test.yaml" run \
    --rm \
    --no-deps \
    --volume "$NETWORK_GUARD:/network-guard:ro" \
    --env PYTHONPATH=/network-guard \
    test python scripts/export_openapi.py
fi

validation_python="$(command -v python3)" || {
  echo "python3 is required to validate the OpenAPI contract" >&2
  exit 1
}

"$validation_python" "$NORMALIZER" "$BACKEND_SCHEMA" "$NORMALIZED_SCHEMA"

"$validation_python" - "$BACKEND_SCHEMA" "$NORMALIZED_SCHEMA" <<'PYTHON'
import hashlib
import json
import re
import sys


expected = [
    "listJobs",
    "createAnalysisJob",
    "retryAnalysisJob",
    "getAnalysisJob",
    "listMatches",
    "createMatch",
    "getMatch",
    "retryMatch",
    "listOutreachCampaigns",
    "getOutreachCampaign",
    "getOutreachDelivery",
    "resendOutreachDelivery",
    "createOutreachSendBatch",
    "previewOutreachSendBatch",
    "getOutreachSMTPSettings",
    "updateOutreachSMTPSettings",
    "testOutreachSMTPConnection",
    "sendOutreachSMTPTestEmail",
    "listOutreachTemplates",
    "createOutreachTemplate",
    "deleteOutreachTemplate",
    "getOutreachTemplate",
    "updateOutreachTemplate",
    "setDefaultOutreachTemplate",
    "duplicateOutreachTemplate",
    "previewOutreachTemplate",
    "listCreatorProfiles",
    "updateCreatorManual",
    "listGameProfiles",
    "rejectUnknownProfileType",
    "getProfile",
    "setProfileFavorite",
    "validateSession",
    "getConnectionStatus",
    "testConnection",
    "replaceConnectionSecret",
    "getReanalysisSettings",
    "updateReanalysisSettings",
    "checkLiveness",
    "checkReadiness",
    "showCreatorResponseConfirmation",
    "confirmCreatorResponse",
]
with open(sys.argv[1], "rb") as stream:
    source_bytes = stream.read()
    document = json.loads(source_bytes)
with open(sys.argv[2], "rb") as stream:
    swift_document = json.load(stream)

source_digest = hashlib.sha256(source_bytes).hexdigest()
if swift_document.get("x-find-me-gamer-source-sha256") != source_digest:
    raise SystemExit("Swift OpenAPI schema source digest is invalid")

actual = []
response_roots = []
for path in document["paths"].values():
    for operation in path.values():
        if not isinstance(operation, dict):
            continue
        operation_id = operation.get("operationId")
        if operation_id is not None:
            actual.append(operation_id)
        if "responses" in operation:
            response_roots.append(operation["responses"])

if set(actual) != set(expected) or len(actual) != len(expected):
    raise SystemExit("OpenAPI operation IDs differ from the approved contract")
if len(actual) != len(set(actual)):
    raise SystemExit("OpenAPI operation IDs are not unique")
if not all(re.fullmatch(r"[a-z][A-Za-z0-9]*", value) for value in actual):
    raise SystemExit("OpenAPI operation IDs must be camelCase")
if "createSendBatch" in actual:
    raise SystemExit("OpenAPI contains the stale createSendBatch alias")

swift_actual = [
    operation["operationId"]
    for path in swift_document["paths"].values()
    for operation in path.values()
    if isinstance(operation, dict) and "operationId" in operation
]
if swift_actual != actual:
    raise SystemExit("Swift OpenAPI operation IDs differ from the backend source")


def contains_value_null_union(value):
    if isinstance(value, list):
        return any(contains_value_null_union(item) for item in value)
    if not isinstance(value, dict):
        return False
    alternatives = value.get("anyOf")
    if isinstance(alternatives, list) and len(alternatives) == 2:
        null_count = sum(item == {"type": "null"} for item in alternatives)
        if null_count == 1:
            return True
    return any(contains_value_null_union(item) for item in value.values())


if contains_value_null_union(swift_document):
    raise SystemExit("Swift OpenAPI schema retains an unsupported value/null union")

schemas = document["components"]["schemas"]
pending = list(response_roots)
visited = set()
while pending:
    value = pending.pop()
    if isinstance(value, list):
        pending.extend(value)
    elif isinstance(value, dict):
        reference = value.get("$ref")
        if isinstance(reference, str) and reference.startswith("#/components/schemas/"):
            name = reference.rsplit("/", 1)[-1]
            if name not in visited:
                visited.add(name)
                pending.append(schemas[name])
        pending.extend(item for key, item in value.items() if key != "$ref")

forbidden = {
    "rank",
    "backend_order",
    "total_score",
    "dimension_scores",
    "response_token",
    "response_token_digest",
    "token_digest",
    "password",
    "ciphertext",
    "nonce",
    "master_key",
    "master_key_file",
    "workspace_access_key_hash",
    "workspace_key_hash",
    "workspace_key_digest",
}
exposed = {
    property_name.casefold()
    for name in visited
    for property_name in schemas[name].get("properties", {})
}
if not exposed.isdisjoint(forbidden):
    raise SystemExit("OpenAPI response schemas expose hidden ranking or secret fields")

smtp_password = schemas["SMTPSettingsUpdate"]["properties"]["password"]
if smtp_password.get("writeOnly") is not True:
    raise SystemExit("SMTP password must remain write-only")
if "password" in schemas["SMTPSettingsResponse"].get("properties", {}):
    raise SystemExit("SMTP password must not appear in response schemas")
PYTHON

mkdir -p "$TARGET_DIR"
candidate="$TARGET_DIR/.openapi.json.sync.$$"
cp "$NORMALIZED_SCHEMA" "$candidate"
if [[ -f "$TARGET_SCHEMA" ]] && cmp -s "$candidate" "$TARGET_SCHEMA"; then
  rm -f "$candidate"
else
  if [[ -f "$TARGET_SCHEMA" ]]; then
    cp "$TARGET_SCHEMA" "$SCHEMA_BACKUP"
    SCHEMA_PREEXISTED=1
  fi
  mv -f "$candidate" "$TARGET_SCHEMA"
  SCHEMA_REPLACED=1
fi

cmp -s "$NORMALIZED_SCHEMA" "$TARGET_SCHEMA" || {
  echo "Swift OpenAPI schema differs from the normalized backend contract" >&2
  exit 1
}

swift build --package-path "$PACKAGE_DIR" --target FindMeGamerAPI
SCHEMA_REPLACED=0
echo "OpenAPI schema synchronized and FindMeGamerAPI built (42 operations; offline export)."
