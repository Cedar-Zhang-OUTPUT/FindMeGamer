# Native workspace polling limit — 2026-09-15

User authorized a backend-only relaxation after Discover polling returned HTTP 429.

## Deployed configuration

On 44.233.174.193, `/opt/find-me-gamer-native-042-pagination/runtime.override.yaml` now includes these API environment settings:

```yaml
WORKSPACE_RATE_LIMIT: "10000"
WORKSPACE_RATE_LIMIT_WINDOW_SECONDS: "60"
```

Previously the effective values were 60 requests per 60 seconds. This is a higher ceiling, not an unlimited bypass. The limiter is keyed by workspace and client address, and also covers invalid-key and public-response requests. Authentication, SMTP throttling, job idempotency and provider-side limits remain unchanged.

Only the API container was recreated, using the existing `find-me-gamer-native:0.4.2-fde066e` image and `up -d --no-deps --no-build api`. No migration, model retry, email sending or client release occurred. Worker and Beat container IDs and start times remained unchanged. Effective settings read back as 10000/60 and API health passed.

Original override is backed up alongside it as `runtime.override.before-rate-limit-20260915.yaml`. Future deployments must preserve these explicit settings in their runtime override; application code defaults remain unchanged. To roll back, restore that override and recreate only API with the same Compose project and env file.

Existing authentication configuration tests: 38 passed. Independent bounded operational review found no blocker for the internal demo. Public HTTP verification uses only authenticated session reads and one invalid-key request, without model or mail operations.
