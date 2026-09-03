#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
helper="${repository_root}/integration/runtime/bounded_command.py"

started_at=$SECONDS
set +e
python3 "$helper" --timeout 0.2 -- python3 -c 'import time; time.sleep(10)'
helper_status=$?
set -e
[[ "$helper_status" -eq 124 ]] || {
  echo "expected timeout exit 124, got ${helper_status}" >&2
  exit 1
}
[[ "$((SECONDS - started_at))" -lt 3 ]] || {
  echo "timeout helper did not return promptly" >&2
  exit 1
}

python3 - \
  "${repository_root}/integration/run.sh" \
  "${repository_root}/integration/runtime/scenario.py" \
  "$helper" <<'PY'
import ast
from pathlib import Path
import sys

runner = Path(sys.argv[1]).read_text(encoding="utf-8")
assert 'bounded_command.py' in runner
assert 'COMPOSE_BUILD_TIMEOUT_SECONDS' in runner
assert 'COMPOSE_CLEANUP_TIMEOUT_SECONDS' in runner
assert 'DOCKER_DIAGNOSTIC_TIMEOUT_SECONDS' in runner
assert runner.count('"${compose[@]}"') == 1, "Compose must be invoked only by its bounded wrapper"

tree = ast.parse(Path(sys.argv[2]).read_text(encoding="utf-8"))
for node in ast.walk(tree):
    if not isinstance(node, ast.Call):
        continue
    function = node.func
    is_subprocess_run = (
        isinstance(function, ast.Attribute)
        and isinstance(function.value, ast.Name)
        and function.value.id == "subprocess"
        and function.attr == "run"
    )
    if is_subprocess_run:
        keywords = {keyword.arg for keyword in node.keywords}
        assert "timeout" in keywords, f"subprocess.run at line {node.lineno} has no timeout"

helper_tree = ast.parse(Path(sys.argv[3]).read_text(encoding="utf-8"))
for node in ast.walk(helper_tree):
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        continue
    if node.func.attr == "wait":
        keywords = {keyword.arg for keyword in node.keywords}
        assert "timeout" in keywords, f"process.wait at line {node.lineno} has no timeout"
print("PASS: Docker command bounds")
PY
