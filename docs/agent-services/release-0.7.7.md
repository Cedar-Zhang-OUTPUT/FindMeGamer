# FMG 0.7.7 — best-effort email enrichment outcomes

- Valid Gemini emails complete as Found even without a source URL; retain
  `model_reported_unverified`. Normal valid empty responses complete as Not Found.
  Optional grounding/retrieval diagnostics no longer block completion or a batch.
- Real quota/credit, HTTP, transport and invalid/truncated-output errors remain
  failures. Failed-attempt markers cannot be mistaken for successful empty results.
- Reuse saved valid checkpoints, including old source-only empty failures, without
  another paid call. Preserve original jobs, run attribution and historical usage.
- CLI job output includes `outcome=found|not_found` for completed results. Both
  Skills and the research validator accept unsourced model results with saved
  completed service-response provenance; no invented URLs or verified-delivery claim.
- Evidence-first extraction and bounded contact-page/Gemini fallback remain.
  Mail templates, sending approvals, pacing, replies and bounce safety are unchanged.

Upgrade with `fmg upgrade --latest --skills`, then read both installed Skills and
their email/completion references. Upgrading does not authorize replay or sending.

## Verification

- Full backend suite with isolated native PostgreSQL/Redis: 369 passed, one Docker
  opt-in check skipped, one existing Starlette/AnyIO deprecation warning. Local
  Docker remains stopped. Go tests/vet and both Skill validators passed.
- Four local release-bundle/installer tests and all archive SHA256 checks passed.
- Independent Skill application changed the old unresolved interpretation into
  Found/Not Found for normal completed responses while preserving real 429 errors
  and no-send authority. Existing public evidence still avoids enrichment entirely.
- Independent review found malformed optional nested URL metadata could invalidate
  valid emails. Four regressions reproduced it before the fix. Failed/interrupted
  old/current attempt markers are also tested; the final full suite includes them.
- Research validation accepts source-null model contacts with a completed saved
  response artifact; removing that provenance still fails validation.

Public bundle and deployment acceptance will be recorded after the checks actually
run. Recovery is separate from release acceptance; queued jobs are not claimed
completed, and estimates are not actual charges.
