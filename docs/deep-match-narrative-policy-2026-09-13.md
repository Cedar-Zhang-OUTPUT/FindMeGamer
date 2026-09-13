# Deep Match narrative policy adjustment

Scope: internal Demo; remove the blanket `played`, `watched`, and `viewing`
business rejection from Deep Match only. Audience preferences, negated statements,
and evidence limitations no longer fail merely because of these words.

Candidate IDs, cited work IDs, supported-evidence checks, strict schemas, and
URL/contact/timestamp rejection remain unchanged. Prompts still prohibit invented
viewing claims. Model text does not confer sender-watched or Outreach sender-facts
eligibility; SMTP and mail qualification logic are not modified.

TDD: 20 new word/field cases failed against the previous implementation. Remove
only the two regex branches, then run focused model/worker/evaluation and Outreach
qualification regression with one bounded independent review.

Deployment requires an idle guard, fresh database backup, unchanged database and
configuration fingerprints, and synthetic/read-only smoke checks. No migration or
client update is required.

After deployment, re-read evaluation `412a1dfe-91b7-45f7-adfb-51c5b0340334` and
resolve its five failed Deep Match step IDs. Submit one bounded authenticated
`POST /api/v2/discovery/evaluations/{id}/retry` with explicit `step_ids` and a
persisted single idempotency key. Do not use the Creator Search retry endpoint.
Successful screening, Deep Match and ranking steps remain untouched; new successful
briefs receive a new ranking batch. Do not delete historical results or retry the
remaining failed Creator Profile. On an uncertain response inspect acceptance before
any resend; never generate another idempotency key for the same operation.
