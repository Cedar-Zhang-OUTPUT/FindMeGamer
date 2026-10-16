# Task 3 — mailbox delivery isolation

## Implementation

SendStore resolves each persisted preview through preview_mailbox and then settings_for(profile.id). API sends pass app.state.mailboxes explicitly. The same shared live sender lock, durable pacing reservation, sender safety checks, recipient exclusions, reservation-before-provider-call ordering, and immutable receipt replay path remain in use. No alternate send path was added.

Preflight rejects missing/unverified mailbox bindings, disabled identities, changed frozen sender/name, and revoked template permission. Generic templates require explicit permission. A centralized check_mailbox_template rejects LIMINAL except for ontologyplay with OntologyPlay@hotmail.com, even if another profile explicitly lists LIMINAL. This helper is shared by preview creation, outreach creation, preview readiness, and delivery.

process_recipient/process_retry accept keyword-only expected_mailbox_id: str | None and registry. Wrong queues return {code: mailbox_queue_mismatch, transport_attempted: false} without blocking another mailbox's task or cancelling its retry. Retry snapshots keep Task 2's inherited mailbox_id/from_name; legacy missing names remain absent and no snapshots are rewritten here.

MIME From safely formats the frozen name and rejects CR/LF. SMTP envelope addresses and Message-ID domain still use the bare sender. Microsoft SMTP OAuth requires its username to match the sender; password-authenticated SMTP retains provider-specific relay username semantics. OAuth private store identity is checked before the transport callback. Graph also verifies actual /me mailbox and account_id before every sendMail POST, including cached access tokens. Its refresh requests now respect the supplied offline transport.

Preview readiness uses the bound registry profile and remains read-only without provider calls. Deferred Task 1 permission coverage now uses an otherwise valid registry at 0644; Graph readiness coverage rejects another stored account.

## TDD evidence

All commands below ran from agent-service with .venv Python/pytest. Provider traffic was replaced by offline fakes; no mail, Gemini, paid APIs, production resources, or Docker services were used.

- Initial RED: `.venv/bin/pytest tests/test_mailbox_delivery.py -q` → 6 failed, 4 passed. Bound-profile sends, per-mailbox pause independence and sent/unknown replay failed because the original global sender configuration was used; expected_mailbox_id/registry keywords were missing; MIME omitted display names. Four rejection tests already failed closed because the old global sender mismatched, so subsequent assertions also verify the specific binding/template error code.
- Graph cached-token RED: `.venv/bin/pytest tests/test_mailbox_delivery.py::test_graph_cached_token_actual_account_mismatch_never_posts -q` → 1 failed. A sendMail POST occurred instead of a pre-POST identity rejection.
- Bound readiness RED: `.venv/bin/pytest tests/test_mailbox_delivery.py -q` → 1 failed, 13 passed. Beta's ready profile was reported false because readiness consulted the global sender.
- Fixed LIMINAL sender RED: `.venv/bin/pytest tests/test_mailbox_delivery.py -q` → 3 failed, 17 passed. Wrong ID, wrong sender, and reassigned fixed sender all created previews despite explicit fixed-signature restrictions.
- SMTP OAuth RED: `.venv/bin/pytest tests/test_mailbox_delivery.py::test_smtp_oauth_cannot_send_as_another_account -q` → 1 failed. A matching OAuth username/store could send with another profile's From.
- GREEN task suite: `.venv/bin/pytest tests/test_mailbox_delivery.py -q` → 22 passed. Additional regression coverage includes recipient/retry queue mismatch state preservation, credential rotation preserving the frozen message, and same mailbox email with changed Graph account_id.

## Verification

Native PostgreSQL environment for database-inclusive runs:

`FMG_AGENT_TEST_DATABASE_URL=postgresql+psycopg://fmg_agent_test@127.0.0.1:55441/find_me_gamer_agent_test`

- Mandatory focused suite plus Microsoft mail: `.venv/bin/pytest tests/test_mailbox_delivery.py tests/test_send_pacing.py tests/test_graph_diagnostics.py tests/test_bounce_retry.py tests/test_bounce_safety.py tests/test_invalid_recipients.py tests/test_liminal_fixed_copy.py tests/test_liminal_banner.py tests/test_smtp_delivery.py tests/test_microsoft_mail.py -q` → 121 passed. This preceded the extra same-email/different-account_id parametrization.
- First full run: 8 failed, 406 passed, 3 skipped, 1 error. Failures were test fixtures mutating global settings after registry snapshots: pacing in PostgreSQL bounce/invalid-recipient cases and the two email configuration-change tests. The sender-change pytest.fail also caused TestClient teardown error. Fixtures now explicitly replace registry snapshots; covering run passed 39 tests.
- Second full run after strict LIMINAL rule: 6 failed, 415 passed, 3 skipped. All six were test_outreach_compact LIMINAL fixtures using publisher@example.com. They now use the fixed sender. Its retry test needed the simulated DSN Message-ID domain changed to hotmail.com; the focused corrected regression passed.
- An in-flight full run collected the pre-DSN-fix version and ended 1 failed, 421 passed, 3 skipped; that known failure was test_summary_tracks_retry_unknown_reply_and_sender_hold. Final full verification on the completed files is recorded below.
- Final full run: `FMG_AGENT_TEST_DATABASE_URL=postgresql+psycopg://fmg_agent_test@127.0.0.1:55441/find_me_gamer_agent_test .venv/bin/pytest -q -rs` → **422 passed, 3 skipped, 1 warning in 37.01s**. Skips: test_email_e2e.py requires compiled FMG_AGENT_TEST_CLI; test_outreach_local.py requires compiled FMG_AGENT_TEST_CLI; test_release_container.py requires explicit locally built FMG_AGENT_TEST_IMAGE. Native PostgreSQL tests ran; none of the database cases were skipped.
- `git diff --check` passed. Changed production/new test files were formatted using bundled Black 25.1.0.

The existing Starlette TestClient emits one AnyIO BlockingPortal DeprecationWarning. This is not pristine warning-free output; no new application warnings were introduced.

## Files changed

Production: email/sending.py, email/routes.py, email/mime.py, email/graph.py, email/retries.py, email/templates.py, outreach.py.

New coverage: tests/test_mailbox_delivery.py.

Fixture/compatibility and deferred coverage: tests/test_bounce_retry.py, test_bounce_safety_postgres.py, test_email_sending.py, test_graph_diagnostics.py, test_graph_mail.py, test_invalid_recipients.py, test_liminal_banner.py, test_liminal_fixed_copy.py, test_mailboxes.py, test_outreach_compact.py, test_send_pacing.py.

templates.py/routes.py are additional touched files necessary to centralize fixed-template validation and pass the app's registry snapshot at the API boundary. SMTP and sender-safety implementations need no change because shared MIME and bound SendStore settings already feed their existing behavior.

## Self-review and boundaries

Read the full production diff, modified fixture diff, and new tests. Checked the send reservation/pacing boundary remains shared; all profile mismatches precede provider callbacks; receipt replay remains available after mailbox disablement; wrong queue workers preserve task/retry state; historical messages/images and approval revisions are not edited. Reviewed explicit error-code assertions and transport argument checks so unrelated configuration failures cannot masquerade as isolation success.

Graph /me adds one read request and potential failure/latency per send, including a second identity read after refresh. A failed/timed-out identity check produces a failed preparation receipt without a sendMail POST; it never claims sent and never switches accounts or auto-retries. Discovery never makes that request. SMTP OAuth validates the private stored grant's mailbox plus exact configured username/From; no delegated send-as support is added.

Task 4 must wire actual workers to their own expected_mailbox_id/registry. Task 5's runtime/backfill gate is intentionally not implemented. Existing five-second default, retry count/delay, pause counters and safety thresholds are unchanged. No actual Redis queue integration or deployment certification is claimed by this Task 3 report. CLI/container skips remain for their later tasks.
