# Preserve every current provider hotfix; copy only the reviewed Sent changes.
ARG BASE_IMAGE=fmg-agent:thieves-footer-20261020
FROM ${BASE_IMAGE}
COPY --chown=10001:10001 config.py mailboxes.py /usr/local/lib/python3.13/site-packages/fmg_agent/
COPY --chown=10001:10001 smtp.py sending.py sent_copy.py mime.py /usr/local/lib/python3.13/site-packages/fmg_agent/email/
