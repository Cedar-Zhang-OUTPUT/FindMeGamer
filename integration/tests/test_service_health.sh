#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if [[ "${FMG_INTEGRATION_ACTIVE:-}" == "1" ]]; then
  python3 "${repository_root}/integration/runtime/scenario.py" health
else
  bash "${repository_root}/integration/run.sh" --scenario health
fi
