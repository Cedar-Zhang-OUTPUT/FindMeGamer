# Consolidated final-review fix wave

Base: `2471665`. Status: implemented and focused verification passed; controller owns the subsequent scoped review and final full-suite scheduling.

## Changes and self-review

- `MailboxRegistry.current()` reloads and validates the authoritative private file at operation boundaries. Process/in-memory configuration remains authoritative only when no file is configured. Discovery, preview create/read, batch creation and approval use current configuration. The guarded send reload occurs after ownership, existing-attempt replay and the runtime gate. No send-route eager reload can break sent/unknown receipt replay when the file becomes missing, malformed or too permissive.
- Approval now applies the existing template allowlist validator as well as the existing frozen identity validator. Send and approval rejection leave frozen messages, recipients and approval revisions unchanged. Credential rotation uses the current secret while retaining the frozen message.
- IMAP `configured()` is an offline preflight for host, username, folders, password or locally validated Microsoft store/client/mailbox identity. OAuth monitoring also checks the selected sender matches the IMAP account. It neither refreshes tokens nor calls a provider. Actual authentication and remote connectivity remain outside local readiness claims.
- Monitor loops reload file configuration for each iteration and record readiness only for locally configured `active` or `held-local` results. `not_configured`, errors and absent outcomes clear readiness. Role probes independently revalidate selected-mailbox IMAP configuration, including while held.
- Positive monitor/release fixtures now provide complete offline IMAP configuration. The subprocess fixture uses a virtual IMAP protocol connection while retaining real synchronization, cursor writes, leadership, gates and role evidence. It previously gained readiness from `not_configured`.
- Read the complete production diff and new tests; `git diff --check` passed. Mutation review: cached send config, cached lifecycle selection, missing approval allowlist, permissive monitor probe, accepting not_configured, and OAuth store mismatch are each covered by behavioral regressions. Existing sender locks/pacing, retry policies, copy/images and maintenance drain logic are unchanged.

## Files

Production:
- `agent-service/src/fmg_agent/mailboxes.py`
- `agent-service/src/fmg_agent/email/routes.py`
- `agent-service/src/fmg_agent/email/sending.py`
- `agent-service/src/fmg_agent/outreach.py`
- `agent-service/src/fmg_agent/email/inbox.py`
- `agent-service/src/fmg_agent/email/monitor.py`
- `agent-service/src/fmg_agent/role_health.py`

Tests:
- `agent-service/tests/test_mailbox_live_configuration.py` (40 cases)
- `agent-service/tests/test_mailbox_monitor.py`
- `agent-service/tests/test_deploy_tools.py`
- `agent-service/tests/mailbox_runtime_fixture.py`

## RED evidence

Commands ran from `agent-service`; no PostgreSQL run or production edit began until the controller confirmed baseline full-suite session 34948 finished.

1. `.venv/bin/python -m pytest tests/test_mailbox_live_configuration.py -q`: first draft had 22 failures and 1 pass; 14 probe cases had a fixture setup mistake (missing required database_url), which was corrected before using RED evidence.
2. `.venv/bin/python -m pytest tests/test_mailbox_live_configuration.py -q --tb=line`: 22 failures, 1 pass. The eight API cases used cached private-file configuration; fourteen held/released probe cases failed to reject missing/invalid IMAP configuration.
3. `.venv/bin/python -m pytest tests/test_mailbox_live_configuration.py -m 'not postgres' -q --tb=line`: after splitting lifecycle coverage, 25 failures, 1 pass, 8 deselected. Discovery remained enabled and preview/create/approval returned success after file disable; invalid file sends still returned 200; probes still accepted invalid local configuration.
4. `.venv/bin/python -m pytest tests/test_mailbox_live_configuration.py -k 'change_blocks_approval' -q --tb=line`: 3 failures, 34 deselected. Revoked template and changed sender/display name still approved (200 vs 409).
5. `.venv/bin/python -m pytest tests/test_mailbox_live_configuration.py -k oauth_sender -q --tb=line`: 2 failures, 37 deselected. Both held/released probes accepted an OAuth monitor for another sender.
6. `.venv/bin/python -m pytest tests/test_mailbox_live_configuration.py -k credential_rotation -q --tb=line`: 1 failure, 39 deselected. Delivery still received the old private-file secret.
7. `FMG_AGENT_TEST_DATABASE_URL=postgresql+psycopg://fmg_agent_test@127.0.0.1:55441/find_me_gamer_agent_test .venv/bin/python -m pytest tests/test_mailbox_live_configuration.py -m postgres -q --tb=line`: 5 failed, 3 passed, 32 deselected in 3.88s. Missing IMAP falsely wrote readiness both held/released; invalid OAuth falsely wrote held readiness and reached the forbidden connection sentinel after release; not_configured falsely wrote readiness.

## GREEN and intermediate results

After implementation, the first 40-case run had 33 passed and 7 failures because tests compared the enriched initial-send response to the existing lean replay response. Corrected the assertion to compare receipt replay before/after mutation, retaining explicit receipt ID/state equality and no-extra-provider-call checks. No production receipt behavior changed.

`FMG_AGENT_TEST_DATABASE_URL=postgresql+psycopg://fmg_agent_test@127.0.0.1:55441/find_me_gamer_agent_test .venv/bin/python -m pytest tests/test_mailbox_live_configuration.py -q --tb=line`

Result: **40 passed**, 1 existing warning, 4.43s.

Broader focused command initially used the same environment and file list below except the final subprocess test: **160 passed, 1 failed**, 24.37s. Failure: `test_release_validates_actual_targets_before_opening_gates[None]`; its positive fixture still omitted IMAP. Added complete offline IMAP to that exact fixture and reran.

Final exact focused command:

```sh
FMG_AGENT_TEST_DATABASE_URL=postgresql+psycopg://fmg_agent_test@127.0.0.1:55441/find_me_gamer_agent_test FMG_AGENT_TEST_REDIS_URL=redis://127.0.0.1:55442/14 FMG_AGENT_TEST_CLI=../cli/fmg .venv/bin/python -m pytest tests/test_mailbox_live_configuration.py tests/test_mailbox_delivery.py tests/test_mailbox_outreach.py tests/test_mailbox_monitor.py tests/test_deploy_tools.py tests/test_microsoft_mail.py tests/test_inbox.py tests/test_mailboxes.py tests/test_queue_isolation_integration.py::test_real_roles_emit_fresh_local_readiness -q --tb=short
```

Result: **162 passed**, 1 existing Starlette/AnyIO BlockingPortal deprecation warning, 27.66s; exit 0 (session 81624). Native PostgreSQL 17 and Redis 8, UUID schemas/keys only. No skips in this focused run.

Formatting: `.venv/bin/python -m black src/fmg_agent/mailboxes.py src/fmg_agent/email/routes.py src/fmg_agent/email/sending.py src/fmg_agent/outreach.py src/fmg_agent/email/inbox.py src/fmg_agent/email/monitor.py src/fmg_agent/role_health.py tests/test_mailbox_live_configuration.py tests/test_mailbox_monitor.py tests/test_deploy_tools.py tests/mailbox_runtime_fixture.py`.

## Boundaries and concerns

- Controller reported baseline `2471665` full suite: 508 passed, 1 container skip, 1 existing warning, 662.99s. That is baseline evidence, not a full-suite claim for this patch. Per controller instruction this agent ran focused checks; final full suite is centrally scheduled after this wave.
- Container/Redis 7 and production gates remain unverified/closed. No Docker, provider API, SMTP/IMAP network, token refresh, production changes, publication or additional agents were used.
- Local readiness proves configuration and locally stored OAuth identity only; it cannot prove current remote authorization, DNS or provider availability. Configuration is checked at operation/scan boundaries; administrative configuration changes should still use the existing hold/drain workflow.
