"""Send fixture sources into an existing test-capable API container; no install."""
import json
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parent
payload = {name: (root / name).read_text() for name in
           ('test_settings_runtime.py', 'settings_runtime.py') if (root / name).exists()}
stable = Path('/tmp/fmg-frontend-stable.bpM1DM/repo')
payload['capture_smtp.py'] = (stable / 'integration/runtime/capture_smtp.py').read_text()
for source in (stable / 'backend/app').rglob('*.py'):
    payload[str(source.relative_to(stable / 'backend'))] = source.read_text()
runner = '''
import json, pathlib, sys, tempfile
import pytest
sources = json.load(sys.stdin)
with tempfile.TemporaryDirectory(prefix="settings-fixture-tests-") as directory:
    for name, source in sources.items():
        target = pathlib.Path(directory, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source)
    sys.path[:0] = [directory, "/app", "/harness"]
    raise SystemExit(pytest.main([directory, "-q", "-p", "no:cacheprovider",
                                 "--basetemp", directory + "/test-state"]))
'''
raise SystemExit(subprocess.run(
    ['docker', 'exec', '-i', '-e', 'PYTHONDONTWRITEBYTECODE=1',
     'fmg-frontend-http-api-1', 'python', '-c', runner],
    input=json.dumps(payload), text=True,
).returncode)
