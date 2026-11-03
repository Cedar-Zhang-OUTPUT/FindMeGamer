ARG BASE
FROM ${BASE}
COPY fmg_agent/ /usr/local/lib/python3.13/site-packages/fmg_agent/
RUN python -c "from pathlib import Path; [compile(p.read_bytes(), str(p), 'exec') for p in Path('/usr/local/lib/python3.13/site-packages/fmg_agent').rglob('*.py')]"
