#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

python3 - "${repository_root}/integration/run.sh" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1]).read_text(encoding="utf-8")
required = (
    'for service in api worker beat',
    'docker image inspect',
    'com.docker.compose.project',
    'com.docker.compose.service',
    'docker image rm "$image_name"',
)
missing = [fragment for fragment in required if fragment not in source]
assert not missing, f"runner lacks exact project-image cleanup: {missing}"
assert "docker image prune" not in source
assert "docker system prune" not in source
print("PASS: exact integration image cleanup policy")
PY
