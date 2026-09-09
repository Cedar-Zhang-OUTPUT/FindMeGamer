# Match priority versus mail evidence

These are separate rules. No new platform or viewing-confirmation requirement is added to discovery.

## Matching

New evaluation snapshots prefer actual linked current-game work records, then linked reference-game work records, then type-related Creator candidates. A current-game association uses the recorded `game_id`; a reference association uses the Activity's selected reference names. A source URL is required for the first two categories. This classifies an existing work association, not whether anyone viewed its content.

No-work/type-related candidates remain eligible for model screening and matching. The model may reject irrelevant candidates, but is told not to reject solely for absent work or viewing evidence. Content confidence remains limited without recorded observations; no sender-viewed claim is introduced.

The frozen priority is computed from all effective current-identity works before choosing the bounded 20-work model context. Related works enter that context first, so an older current-game work is not lost behind newer unrelated records. The full work fingerprint remains independent of Activity-specific ordering.

Result ordering applies priority before pagination, then internal model score and stable input order. Unranked candidates remain after scored candidates. No numeric ranking is added to the public result DTO. Method version is `discovery-evaluation-v2-work-priority-chunk20`.

## Mail personalization

Only works explicitly chosen for an Activity selection can supply mail evidence. Require all three: source URL, evidence excerpt, and verification notes. Among these, choose current-game work, then reference-game work, then other explicitly selected recorded content, preserving operator order within a category.

The chosen source retains its URL, work/game ID, relation, timestamp and evidence status. `input.work.evidence_tier` is `current_game`, `reference_game`, `related_content`, or `unverified`; reference/observation slot sources carry the same evidence metadata. No usable recording means normal repair, not invented observation. Existing explicit sender attestations are unchanged.

## Verification

Initial tests were red before the priority helpers existed. Focused business gate: 68 passed; its new mail-flow fixture used a nonexistent `work_ids` response field and was corrected to use `works[].id`. Final new priority/API gate: 10 passed. The 21-work regression reproduced the independently reviewed truncation problem, then passed after the fix. One bounded independent review returned Accept after that correction. No frontend-owned fixture or production state was modified by this unit.
