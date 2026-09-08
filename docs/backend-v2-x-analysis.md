# X Creator Analyze — internal Demo

This unit extends the existing Analyze workflow to X. It does not create a new
service or require a new credential type. Instagram remains a preset/interface;
Twitch is not advertised as implemented. No live provider/model/mail/deployment
calls are part of the offline gate below.

## Client contract

For a Library Creator with platform `x` and a bound numeric account ID, submit:

```http
POST /api/v1/jobs/analysis
Authorization: Bearer <workspace key>
Idempotency-Key: <new operation key>
Content-Type: application/json

{"target_type":"creator","url":"https://x.com/i/user/123456","mode":"reanalyze"}
```

Use the `source_identity.canonical_url` returned by the Library. Public job type
remains `creator`; internal/public `canonical_target_id` is `x:123456`, namespaced
to prevent collisions with other platforms. This is an account identifier, not a
Library UUID. `profile_id` is the unchanged Library UUID after success.

- Existing job create/reuse, idempotency replay, polling, changes, retry and explicit
  collection resume are reused. Metadata-only entries should use `reanalyze` even
  without a prior analysis date. X handle URLs without a bound numeric account are
  not resolved by this unit; they remain manual source identities, not fake success.
- X uses its own collection switch. Pausing YouTube does not pause X; paused X jobs
  require explicit resume after re-enabling. Active X Analyze prevents conflicting
  identity correction. Completed jobs remain readable after a later explicit rebind.
- `CreatorDetail.analysis`, `brief`, and `source_status` are additive read-only JSON
  fields for both implemented platforms. They never become manual overrides.
  `analysis_available` is capability, not proof that credentials or live permissions
  have been verified. The separate collection/settings state still applies.
- X is now advertised as Analyze-capable in discovery capabilities. Missing or
  insufficient credentials produce the normal safe job failure, not a success stub.

## Actual data and AI path

The gateway reads the public user profile at `/2/users/{id}` and **one page of at
most 50 original recent posts** at `/2/users/{id}/tweets`, excluding reposts and
replies. It records `coverage=recent_account_posts`, `post_limit`, `sample_size`,
`more_available`, and excluded types. There is no automatic pagination, recent
search masquerading as account history, private audience access, media download,
or claim of watching a video. Partial/inaccessible/mismatched responses do not
replace an existing Profile.

Sources: [official user posts timeline](https://docs.x.com/x-api/posts/timelines/introduction)
and [official user lookup](https://docs.x.com/x-api/users/lookup/integrate).
The existing successful live search test does **not** verify these two endpoints;
their real permission acceptance remains with the developer-access thread.

Normalized source is checkpointed and stored through the existing acquisition
artifact store/lifecycle. Up to ten posts per AI call are analyzed with the existing
DeepSeek V4 Flash gateway; at most four calls run concurrently. Multiple batches
receive one compact reduction. Calls use a bounded 4096-token output and English
schema-only instructions. Every available interpretation is explicitly
`kind=ai_inference` and must cite supplied source IDs; unknown stays unavailable.
Profile identity, metrics and content languages remain provider-owned.

Successful source/batch checkpoints are reused on a retry of the **same job**.
The gateway itself does not retry paid reads. The existing bounded worker retry
policy still applies to transient failures; a failure before the source checkpoint
can repeat its two reads. A new user-created retry job takes a new source sample.

Only a complete validated analysis publishes source facts, languages, works, contact
candidates, analysis, brief and dates atomically. Manual profile fields, manual
work/contact overrides and stable source record IDs are preserved. Public email
candidates are extracted from the actual X description/posts, deduplicated and
syntax-validated (not delivery-verified). No AI-invented email or automatic sender
viewing confirmation is created. X does not reuse the YouTube-specific Gemini
research/vision prompt under a false YouTube identity.

Scheduled X reanalysis uses the existing Creator interval and Beat/Worker, including
the existing maximum 30 days. Successful refresh clears stale status. There is no
new scheduler, queue, public response callback, or send action.

## Migration and safety

`20260908_0019`, from current `0018`, extends the deferred successful-result predicate
to canonical X identities and their explicit historical bindings, preserving exact
Game/YouTube validation. It adds safe X error codes to the existing database check.
No data rewrite or Profile deletion occurs. Downgrade refuses while X jobs exist;
back up/restore instead of deleting them. API, Worker and Beat may be stopped during
the agreed maintenance window; mixed old/new workers are not a delivery requirement.

Existing encrypted `x` and `deepseek` credentials are read in short transactions;
clients are closed and provider calls never hold the job/profile write transaction.
IDs cannot become arbitrary request paths. Provider error bodies are not public job
messages. Failed analysis leaves the existing Profile intact. No SMTP or outreach
behavior is changed by this unit.

## Acceptance

TDD covered missing source gateway, X being incorrectly gated by the YouTube switch,
missing production pipeline/runtime, old SQL rejecting X success, absent scheduled
X refresh, and stale status surviving a successful refresh. Verification results:

- Added 27 tests covering the gateway, real API/worker/pipeline wiring with offline
  providers, retry checkpoints, atomic publication/manual overrides, scheduling,
  encrypted runtime configuration, and the current-version migration.
- Focused integration/contract regression: **112 passed** in 17.71s.
- One bounded, read-only GPT-6 Astra / Medium independent review: **Accept**, no
  reproducible internal-Demo blocking findings. No second broad review was added.
- The first full run stopped at an older migration test because the new committed
  X test fixture restored explicit collection defaults instead of the prior raw
  settings. The fixture now restores its entry value; production migration guards
  were not weakened. Sequential X pipeline + older migration regression:
  **8 passed** in 4.92s. Only the isolated test database's leftover setting was reset.
- The next full run reached 428 passing tests before an old contract asserted X
  could never be scheduled. Updated that assertion to require X scheduling while
  retaining the legacy YouTube API exclusion; Library + X regression: **34 passed**
  in 13.18s. Neither issue required a production-code change after review.
- Complete real-Redis regression executed through the end: **2346 passed,
  3 skipped, 1 failed** in 288.94s. The sole failure was the old single-head test's
  literal `0018` expectation after adding `0019`. Updated only that expected value;
  the full original migration group plus X migration then passed **31 tests** in
  1.29s. No remaining observed failure. This is full-suite evidence plus a targeted
  final correction check, **not** a claimed single all-green full-suite run.
- The three skips are the established old live-writer migration cases, outside the
  approved maintenance-window scope. The existing Starlette/AnyIO deprecation
  warning is non-blocking. No second full run was needed for the one-line test-only
  head expectation correction; production code remained unchanged.
