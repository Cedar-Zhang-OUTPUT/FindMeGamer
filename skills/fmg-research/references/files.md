# Local artifact contract

Use one user-visible folder per Steam App ID, e.g. `fmg-research/steam-4952700/`. Do not overwrite another game's workspace. The helper needs Python 3.10+ on macOS/Linux, no packages:

```sh
python3 PATH_TO_SKILL/scripts/workspace.py init --root WORKSPACE --app-id 4952700 --run-id liminal-001
python3 PATH_TO_SKILL/scripts/workspace.py index --root WORKSPACE --input accounts.json
python3 PATH_TO_SKILL/scripts/workspace.py summary --root WORKSPACE --run-id liminal-001
```

`init` creates directories/index, never writes a fictional game profile. Agent writes actual content with ordinary file tools. `index` atomically adds deduplicated per-run status events, preserving other accounts and history. Input array example:

```json
[{"platform":"youtube","account_id":"UC_example","name":"Channel","profile_url":"https://www.youtube.com/channel/UC_example","run_id":"liminal-001","status":"seen"}]
```

Statuses: seen/recommended/rejected/contacted are separate historical events, not a single mutually exclusive flag. Platform + stable account ID is the identity key. A handle is provisional until resolved; do not pretend invented IDs are official. One writing Agent per workspace is recommended; helper index updates use a lock. The helper does not alter evidence or send mail.

Layout:

```text
game-profile.md
creator-index.json
runs/<run-id>/
  search-intent.json
  game-confirmation.json    # pending/approved/rejected understanding + search scope
  progress.json
  evidence/                 # raw API pages plus concise source notes
  matches/<local-key>.json
  usage.json
  codex-usage-before.json    # sanitized host quota snapshot or unavailable reason
  codex-usage-after.json
  summary.md
outreach/<batch-id>/        # variable inputs, previews, approval record, receipts
```

Use safe local filenames, not arbitrary URL strings. `progress.json` records completed actions, pending actions, cursors, job IDs, original idempotency keys and budget counters. Write updates atomically and keep existing files on failure. Different runs do not overwrite prior Match Briefs. `usage.json` stores the unmodified service envelope; `summary.md` distinguishes measured counts, estimates and unknown money.

## Game review record

Before creator discovery, save `runs/<run-id>/game-confirmation.json` with status
`awaiting_confirmation`, then change to `approved` or `rejected` only according
to the user's actual response. Include:

- Steam App ID, reviewed game Profile path and content hash.
- A preserved snapshot of the game understanding and proposed Search Intent,
  including search angles, exclusions, platforms, constraints, targets and budgets.
- Search Intent path/hash, facts-versus-inferences limitations shown to the user,
  user corrections (with their source clearly attributed), and review timestamp.
- On approval: the approving user message reference (or faithful short quote if
  the host provides no message ID), approval timestamp and exact approved scope.
  Never fabricate a reference or mark silence as approval.

Set `progress.json` phase to `awaiting_game_confirmation` while waiting. Preserve
review snapshots when revising or starting another run; a changed live Profile
must not erase what the user originally reviewed. A prior approval can support
resume of the same unchanged work, but not a materially changed search plan.
This is an Agent workflow record, not a server-enforced CLI permission: direct
API commands remain available for other authorized tasks.

Each Match Brief is a JSON object (not Markdown), with these required slots:

```json
{
  "schema_version": 1,
  "run_id": "liminal-001",
  "game": {"app_id":"4952700","profile_path":"../../../game-profile.md","profile_sha256":"HASH_OF_USED_PROFILE"},
  "creator": {"platform":"youtube","account_id":"UC_example","display_name":"Channel","profile_url":"https://www.youtube.com/channel/UC_example"},
  "discovery": [{"operation":"search.list","query":"related game gameplay","lead_type":"related_game","response_file":"../evidence/page-1.json","request_id":"REQUEST_ID"}],
  "filters": [{"dimension":"content_language","expected":"English","observed":"English","outcome":"pass","evidence_ids":["work-1"]}],
  "evidence": [{"id":"work-1","url":"https://www.youtube.com/watch?v=EXAMPLE","retrieved_at":"ISO_TIME","level":"title_description","observation":"What the source actually supports","raw_file":"../evidence/work-1.json"}],
  "match": {"decision":"suitable","reasons":["Evidence-backed relevance"],"limitations":["Unverified audience geography"]},
  "contacts": {"status":"pending","emails":[]},
  "presentation": {
    "public_name": "Unknown",
    "content_direction": "Narrative adventure commentary (supported by work-1)",
    "followers": "Unknown — not returned by provider",
    "content_language": "English — work-1",
    "audience_region": "Unknown — creator location is not audience geography",
    "why_match": {
      "evidence": "Work title, date, URL and what it supports",
      "gameplay_connection": "Connection to mechanics, loop, style or related games",
      "assessment": "Campaign fit, facts vs inference",
      "collaboration_angle": "Suggested format, not a willingness claim",
      "limitations": "Inspected source type and missing evidence"
    }
  }
}
```

Resolve paths relative to the Match Brief. Use actual hashes, dates, IDs and observations, not example strings. Filter outcome is pass/fail/unknown; decision suitable/needs_verification/rejected. Evidence levels distinguish metadata, public text, transcript excerpt, inspected visual and user-supplied notes. Contacts status: pending/found/not_found/failed/not_requested; each email includes address/purpose/source/verification. `not_requested` requires an explicit user opt-out recorded as `contacts.reason`; unresolved work keeps its job ID and reason. Only a completed empty lookup is not_found. Explaining a result reads these files before calling APIs again.

## Result completeness

Every Match Brief must include the `presentation` object above, a canonical `creator.profile_url`, and `contacts`. These are shared by browser and Excel. Store readable non-empty strings with supporting facts or explicit Unknown + reason; do not fabricate missing facts. Followers include metric/date, audience inference must be labeled. `why_match` requires all five sections. Before final delivery run:

```sh
python3 PATH_TO_SKILL/scripts/research_dashboard.py --root WORKSPACE --run-id RUN_ID --validate
```

Exit 2 reports missing fields or unfinished contacts: repair the files or explicitly report a partial/blocked result, not a completed deliverable. The live viewer still shows partial/legacy records with missing-data warnings. `found` requires at least one address; `not_found` requires `contacts.lookup_completed: true` and no addresses. A provider error is not a completed empty lookup. The validator checks structure/status, not truth; Agent must check sources.

## Excel creator results

The browser table and any Excel export must use these nine columns **in this order** (do not create a workbook unless the user requests it or the agreed deliverable includes one):

1. 序号 — sequential integers starting at 1 in the exported order.
2. Public name — creator's explicitly public name; unknown if unavailable. Do not silently substitute a channel name or infer a legal name.
3. 邮箱 — public business email(s), with purpose when multiple; distinguish Not Found (completed lookup), not requested, and unresolved lookup.
4. 为什么 Match？ — detailed, readable rationale with the five sections below, not a generic one-sentence endorsement.
5. 相关的内容方向 — supported genres, formats and themes.
6. 频道的链接 — canonical creator profile URL.
7. 粉丝数 — numeric count when available, noting platform metric and retrieval date (e.g. subscribers vs followers). Unknown is not zero.
8. 内容的语言 — evidence-backed content language(s), not an assumption from country.
9. 面向的受众地区 — audience geography with evidence or clearly labeled inference/unknown; creator location does not establish audience location.

Within **为什么 Match？**, use line breaks and explicit subheadings:

In the browser table, show only a compact three-line assessment summary followed by
**More info**. Its dialog shows all five sections in full; do not truncate stored
briefs or Excel content to fit the table.

- **具体证据**: relevant work/video/post names, dates if available, clickable or literal source URLs, and what the evidence actually supports.
- **玩法联系**: relationship to the target game's mechanics, game loop, style, or supported similar-game experience.
- **形势判断**: why this creator fits the current campaign, with relevant content recency, audience fit and uncertainties; separate facts from inference.
- **合作切入建议**: a specific, evidence-based proposed angle or format, not a claim of willingness or guaranteed results.
- **AI 判断边界**: what was inspected (e.g. title/description, not a full video), missing metrics, unverified geography and other limits.

Use wrapped text, top alignment, filters and a frozen header; keep long rationales readable rather than clipping them. Preserve the local JSON Match Briefs and source artifacts as the machine-readable audit trail. Never invent evidence, audience data or completed video viewing to fill a cell. Treat upstream text as plain spreadsheet data, not executable formulas.
