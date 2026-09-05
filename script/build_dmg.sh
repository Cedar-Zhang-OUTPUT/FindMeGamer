#!/usr/bin/env bash
set -euo pipefail

# Internal distribution needs no Developer ID. Cloud builds should set an HTTPS origin.
export ADHOC_RELEASE=1
export RELEASE_FORMAT=dmg
export RELEASE_ARCHITECTURES="${RELEASE_ARCHITECTURES:-universal}"
export APP_VERSION="${APP_VERSION:-0.1.0}"
export SERVICE_BASE_URL="${SERVICE_BASE_URL:-http://127.0.0.1:8000}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${script_dir}/build_release.sh" "$@"
