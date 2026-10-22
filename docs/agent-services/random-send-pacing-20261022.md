# Random mailbox send pacing

## Scope

Replace the fixed five-second cooldown with a uniform random choice from
`[8, 9, 10]`, independently for every mailbox. Direct API sends, outreach batches
and bounce retries still share the same normalized-sender PostgreSQL lock and
durable gate. No new provider calls, automatic retries, hold releases or mailbox
fallbacks are introduced.

The cooldown starts after each transport outcome (sent, failed or unknown), and
is persisted as `available_at`. Polls and idempotent replays cannot resample or
shorten it. Expired interrupted-owner recovery also persists one random cooldown.
The live advisory lock still protects transports exceeding their recovery lease.
The ten-second dispatcher scan remains unchanged, so actual batch spacing can be
longer than the selected cooldown; this is a minimum gate, not an exact scheduler.

## Compatibility

Positive `email_send_interval_seconds` values now enable this common policy;
legacy registry/environment values of 5 do not retain five-second behavior. The
default/example is 8. Zero remains an isolated-test escape hatch and deployment
readiness rejects it for enabled profiles. No schema/data migration is required.

Mailbox discovery keeps version 1, reports the effective minimum through
`send_interval_seconds=8`, and adds `send_interval_choices_seconds=[8,9,10]`.
Existing CLI JSON passthrough remains compatible; both Skills document the rule.

## Deployment boundary

This change does not unblock Namecheap or make the outreach policy acceptable to
the provider. Do not resume sending merely because pacing has changed.
Switch all sending-capable API/mail-worker roles in a held, drained window;
mixed old/new roles could still apply the old policy. Preserve historical
messages, pending recipients, unknown receipts, sender safety and monitoring.
Wait at least ten seconds after the last old transport finishes before any
separately authorized release. Publishing this source alone does not update
running containers or installed Skill copies.

## Verification

Tests cover each of 8/9/10, persisted choices across polling, independent mailbox
gates, concurrent tokens, direct API/batch/retry sharing, failed/unknown outcomes,
stale lease recovery, PostgreSQL shared time/live locks, CLI discovery and
two-Agent queue behavior. All transports in these tests are local fakes; no
real SMTP, IMAP or Gemini calls are required.

Local verification on 2026-10-22: full backend suite **616 passed, 1 skipped**
with isolated PostgreSQL/Redis and a freshly built CLI, including real two-Agent
and resource-budget scenarios (668.31 seconds). CLI `go test ./internal/...`
passed; both Skills passed `quick_validate.py`. Focused pacing/mailbox/retry
tests also passed (46), and the focused PostgreSQL/runtime/queue suite passed
(25). Production containers/configuration were not changed; no package was
published and no sender hold was released.
