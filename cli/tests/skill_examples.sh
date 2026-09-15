#!/bin/sh
set -eu
# Executable isolated examples; never targets the company gateway or sends externally.
root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$root"
agent-service/.venv/bin/python cli/tests/gateway_smoke.py --binary cli/fmg
cd agent-service
: "${FMG_AGENT_TEST_DATABASE_URL:?Use only the dedicated local test database}"
FMG_AGENT_TEST_CLI=../cli/fmg .venv/bin/pytest tests/test_email_e2e.py tests/test_workflow_workspace.py -q
