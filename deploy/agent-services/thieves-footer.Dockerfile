# Minimal patch over the active template release; leave enrichment unchanged.
ARG BASE_IMAGE=fmg-agent:thieves-template-20261020
FROM ${BASE_IMAGE}
COPY --chown=10001:10001 templates.py mime.py /usr/local/lib/python3.13/site-packages/fmg_agent/email/
COPY --chown=10001:10001 outreach.py /usr/local/lib/python3.13/site-packages/fmg_agent/outreach.py
COPY --chown=10001:10001 thieves-outreach.json thieves-banner.jpg /usr/local/lib/python3.13/site-packages/fmg_agent/email/template_data/
