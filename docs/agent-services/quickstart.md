# FMG CLI and Skills — company setup

To delegate setup to an Agent, give it the public [Agent installation guide](https://github.com/Cedar-Zhang-OUTPUT/FindMeGamer/releases/download/fmg-v0.2.0/AGENT-INSTALL.md). It covers environment checks, verified installation, private-token login, Skill loading and no-quota acceptance checks.

The CLI gateway is `https://44.233.174.193` (base URL, without `/v1`). The legacy macOS backend is intentionally stopped. Old client credentials do not work here. Ask the administrator for a personal revocable CLI token; provider keys are never installed on the user's machine.

## Install a prepared bundle locally

macOS/Linux arm64/amd64, Python 3.10+, and a shell are supported. The CLI itself has no runtime language dependency. From a verified downloaded release directory:

```sh
python3 install.py --release-dir . --skills
```

Default binary directory is `$HOME/.local/bin`; add it to PATH if needed. Skills go to `$HOME/.codex/skills`, with `--skill-dir` available for a different Codex runtime. Without `--skills`, only the binary is installed. Existing Skill versions are retained as `.previous` folders; move those backups outside the active Skills folder after verification before a subsequent upgrade. Reload Codex Skills if required. Installation cannot automatically inject a first conversation message.

Install the explicit CLI release and both Skills:

```sh
curl -fsSL https://github.com/Cedar-Zhang-OUTPUT/FindMeGamer/releases/download/fmg-v0.2.0/install.py | python3 - --tag fmg-v0.2.0 --skills
```

For inspection before execution, download the installer and review it first. Asset URLs come from exact GitHub release metadata; binary/Skill archives are checked against SHA256SUMS. Checksums detect corruption, not a compromised release publisher. Unsigned macOS binaries may require normal local approval; no automatic Gatekeeper disabling is performed.

Add `$HOME/.local/bin` to PATH for your shell, or invoke `$HOME/.local/bin/fmg` explicitly. Start a new Codex conversation after installation so it discovers the Skills. No provider credentials or access tokens are embedded in the installer.

## Authenticate

Administrator provides the new verified HTTPS gateway and personal revocable token separately. Never paste provider/SMTP credentials in an Agent chat or command argument. Pipe the token privately into:

```sh
fmg auth login --server https://44.233.174.193 --token-stdin
fmg auth check
fmg version
```

Configuration is mode 0600; `auth logout` removes it locally. Server-side revocation is separate. Remote HTTP is rejected. Read access is default; enrichment and sending need `email:enrich` and `email:send` scopes.

## Ask Codex

“Use fmg-research to find suitable English-speaking creators for this Steam game on YouTube and X. Save the evidence locally; do not send mail.”

“Find more new creators for the same game, excluding everyone previously seen.”

“Explain why this creator was matched using our saved evidence.”

“Draft outreach for these three creators and show me the recipients and messages.”

The workflow defaults to a bounded target and announces its request budget. It saves a game Markdown profile, JSON matches and evidence, progress and a local identity index. Missing geography/contact information stays unknown. Email lookup failure is distinct from Not Found. Drafting is not permission to send.

## Costs, updates and limits

Use `fmg --run-id RUN_ID ...` and `fmg --run-id RUN_ID usage`. Responses include price snapshots; the ledger returns known estimated USD subtotals, pricing versions and unpriced components. Estimates precede discounts/free allowances and X daily deduplication, exclude infrastructure/subscriptions, and are not invoices. Historical unpriced calls remain unknown. YouTube quota estimates are separate. Skills now call the host's `get_usage_limits` at run start/end when available: shared-account changes are reported separately, never as precise task use.

`fmg upgrade --latest --skills` updates the CLI and both Skills with checksums, preserving credentials and numbered Skill backups. Use `--tag fmg-vX.Y.Z` to pin a version, or omit `--skills` for binary only. CLI 0.1.0 users bootstrap with the 0.2.0 installer and `--skills`; see the Agent guide. SMTP is currently unconfigured: preview works, real sending is unavailable. Steam Store helpers work without a key; Web API operations requiring a Steam key remain unavailable until configured.

Only YouTube/X/Steam API reads, public business email enrichment and templated sends are included. No legacy Library/Match database, social platform writes, Instagram/Twitch API, reply ingestion, Yes/No callbacks or attachment sending is claimed.
