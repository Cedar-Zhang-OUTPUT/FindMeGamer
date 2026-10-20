# Only registry schema compatibility. No Gemini/task logic changes.
ARG BASE_IMAGE=fmg-agent:gemini429-20261020
FROM ${BASE_IMAGE}
COPY --chown=10001:10001 config.py mailboxes.py /usr/local/lib/python3.13/site-packages/fmg_agent/
