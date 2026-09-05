# EC2 internal Demo deployment

The approved deployment uses one existing EC2 instance, a maintenance window,
and a fresh Library. It is not a multi-tenant or zero-downtime rollout.

- EC2: `i-041e77ab08c86ff1d`, `us-west-2`, Ubuntu 24.04 x86_64.
- Public origin: `https://44.233.174.193` (fixed Elastic IP).
- S3: `zhangyue-data-493392056671-us-west-2`.
- Acquisition and backup prefixes: `acquisition/` and `backups/`.
- API, Worker, Beat, PostgreSQL 17, Redis 7, and Caddy run in Docker Compose.
- Only Caddy publishes ports 80 and 443. SSH is restricted to the operator.

## Public-IP HTTPS

Caddy 2.11.4 requests Let's Encrypt's `shortlived` ACME profile. IP certificates
are publicly trusted and valid for approximately six days. Caddy manages renewal
automatically; its `/data` volume must persist and port 80 must remain reachable
for HTTP-01 validation. `default_sni` selects the public certificate for clients
that omit SNI behind the EC2 Elastic IP's NAT. No client trust bypass is needed.

Reference: [Let's Encrypt IP certificates](https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability.html).

## Configuration and source delivery

`/etc/find-me-gamer/app.env` and `master.key` are root-owned, mode 0600. The master
key is exactly 44 base64 characters without a newline. Never regenerate it over
an existing deployment. Provider credentials are encrypted in the cloud database
using this key. There are no static AWS keys; the instance role supplies S3 access.

Only provider configuration is transferred from the local backend, not Profiles,
analysis jobs, Match tasks, or outreach history. SMTP remains unconfigured until
the sender mailbox is supplied. Do not claim real email delivery has been tested.

For this private repository, a Git bundle is transferred over SSH into the bare
mirror `/opt/find-me-gamer-source.git`. `/opt/find-me-gamer` fetches from that local
mirror. This avoids storing a personal GitHub token on the server. For each future
release, upload a new bundle, import the release branch into the mirror, and run
`sudo /opt/find-me-gamer/ops/deploy.sh <exact-commit>` from the clean checkout.
The deploy script stops API/Worker/Beat, backs up PostgreSQL, migrates, and restarts.

## Verification

Use `ops/smoke_test.sh https://44.233.174.193` with a private
`FMG_WORKSPACE_KEY_FILE`. It checks authenticated API access but does not prove
provider credentials are usable. Separately check DeepSeek, YouTube, and Google
AI Studio connection tests, one real Game and Creator analysis, profile details,
and one Match. SMTP tests must use an explicitly approved recipient after setup.

The instance role may not expose lifecycle inspection or EC2 Describe APIs. Do
not expand IAM merely to satisfy optional inventory probes: validate actual S3
Put/Get and backup behavior. The bucket's 30-day prefix lifecycle was provisioned
in the infrastructure handoff and must not be overwritten as part of deployment.

## Vision image delivery

The backend downloads public image bytes and supplies inline Base64 images to
DeepSeek, rather than asking the model provider to download YouTube/Steam URLs.
Each redirect is revalidated, DNS answers must all be public, and connections
pin the validated address while preserving TLS hostname verification. Image
requests never use the DeepSeek API client or its Authorization header.

Downloads are limited to four concurrent requests, 4 MiB per image, 15 seconds
per image across redirects, and 24 MiB of aggregate inline image characters.
The existing maximum of 12 images and evidence-reference order remain unchanged.
Supported raster formats are detected from bytes. This path keeps image bytes
in request-local memory, without adding stored image artifacts or new services.
Structured-output repair reuses those inline bytes. Unavailable image inputs
retain the existing nonfatal, explicitly marked visual fallback.

For deployment verification, rerun a real Game and Creator analysis and require
both `source_status.visual_analysis=available` and
`model_metadata.vision_available=true`; a successful job with visual fallback
alone does not verify this fix.
