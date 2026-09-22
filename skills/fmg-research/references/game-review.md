# Interactive game and filter confirmation (Codex)

Prepare `game-profile.md` at the workspace root: actual Steam identity and source facts, genre, gameplay loop, style, audience, Steam related games, plus clearly labeled AI interpretation and limitations. Prepare `runs/RUN/search-intent.json` with proposed search angles, example keywords, related-game leads, exclusions, finite budgets and any already-requested filters. The browser displays both files as safe text; write the profile in clear sections and use readable intent values.

Optional `filters` uses the contract in `scripts/review_filters.py`. Omit it for defaults: YouTube/X/Twitch selected, 10 per selected platform, any language/region/count/contact. Instagram is not offered. An explicit total overrides per-platform defaults. Contact options are only 不限 / 有邮箱; required email lookup/enrichment applies to both.

```sh
python3 PATH_TO_SKILL/scripts/game_review.py serve --root WORKSPACE --run-id RUN
```

Keep the local server running and open its printed URL using the host's built-in browser. Do not expose the loopback server publicly or place provider credentials in the page. The user can change filters, add corrections, and save. Cancel/Escape in the filter panel discards unsaved panel changes. Known region codes are canonical; unknown free-text tags must be resolved with the user before final approval. Language, creator region and audience region are independent. Follower presets form a union; unknown counts are included by default only in unrestricted mode.

While the current task is active, use bounded waits (not a terminal prompt):

```sh
python3 PATH_TO_SKILL/scripts/game_review.py wait --root WORKSPACE --run-id RUN --timeout 45
python3 PATH_TO_SKILL/scripts/game_review.py status --root WORKSPACE --run-id RUN
```

Pending is `awaiting_confirmation`; approved returns the exact filters, corrections and saved profile/intent snapshots. Read and honor them before discovery. User corrections take priority over the proposal; ask about conflicting or ambiguous corrections instead of guessing. The local page does not invoke an LLM or platform search itself. It cannot wake a finished Codex turn: if the session stops, tell the user to say “按已保存条件继续”; `status` recovers the approval. Do not claim background notification if no wait is active.

The saved `game-confirmation.json` records source `local_browser_user_save`, timestamp and content revision; no conversation message ID is fabricated. Changing either input file invalidates approval. Preserve the old snapshot; present a revised plan for any material change. Do not rewrite an approved input just to change formatting before checking status. In conversation-only fallback, follow the existing explicit user-message confirmation contract instead.

No automatic dispatch follows save. Only the Agent continues within approved scope and budgets; sending still needs separate explicit approval.
