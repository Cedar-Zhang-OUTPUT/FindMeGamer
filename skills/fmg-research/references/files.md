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
  "contacts": {"status":"not_requested","emails":[]}
}
```

Resolve paths relative to the Match Brief. Use actual hashes, dates, IDs and observations, not example strings. Filter outcome is pass/fail/unknown; decision suitable/needs_verification/rejected. Evidence levels distinguish metadata, public text, transcript excerpt, inspected visual and user-supplied notes. Contacts status: found/not_found/failed/not_requested; each email includes purpose/source/verification. Only a completed empty lookup is not_found. Explaining a result reads these files before calling APIs again.
