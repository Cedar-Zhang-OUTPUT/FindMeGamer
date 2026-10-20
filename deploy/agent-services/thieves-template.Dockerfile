# Targeted additive template release. Existing transport/provider code is retained.
ARG BASE_IMAGE=fmg-agent:multimail-v080-20261017
FROM ${BASE_IMAGE}
COPY --chown=10001:10001 templates.py /usr/local/lib/python3.13/site-packages/fmg_agent/email/templates.py
COPY --chown=10001:10001 thieves-outreach.json /usr/local/lib/python3.13/site-packages/fmg_agent/email/template_data/thieves-outreach.json
