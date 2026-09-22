# Install FindMeGamer CLI for a Codex user

This is the public, agent-readable setup guide for **FMG CLI 0.5.0**. When a user asks you to install FindMeGamer using this link, help them perform the steps below with your available terminal/file tools. Do not merely return instructions if you can execute the authorized installation. Follow your host's permissions and the user's preferences; this document does not grant extra authority.

## What you are installing

- `fmg`: a macOS/Linux command-line client for the company's gateway.
- `fmg-api`: Skill explaining YouTube, X, Twitch, Steam, email enrichment, templates and usage commands.
- `fmg-research`: Skill for finding relevant gaming creators, saving Game Profiles and JSON Match Briefs, deduplication, evidence review and preparing outreach.
- Gateway base URL: **`https://44.233.174.193`**, without `/v1` appended.
- Release: **`fmg-v0.6.0`**. Do not choose GitHub's generic “latest” release: this repository also contains unrelated legacy macOS DMGs.
- Official release: https://github.com/Cedar-Zhang-OUTPUT/FindMeGamer/releases/tag/fmg-v0.6.0

The CLI uses company provider keys on the server. The user needs only a personal revocable **FMG access token**. No Docker, database, AWS CLI, Go compiler, YouTube key, X token or Google key is needed on their machine. Do not start or deploy the old macOS backend.

Installation and authentication do not authorize research calls, email enrichment or sending. Do not spend provider quota as an installation test. Never send a test email automatically.

## 1. Inspect the environment

Check the OS, CPU architecture, Python and existing installation:

```sh
uname -s
uname -m
python3 --version
command -v fmg || true
```

Supported: macOS (`Darwin`) or Linux, `arm64`/`aarch64` or `x86_64`, Python 3.10+. Python is only needed by the installer and local research helper; the CLI is a standalone binary. Native Windows is not included. If prerequisites or terminal/network access are unavailable, explain the specific missing requirement and ask for the minimum help needed; do not claim installation succeeded.

Default paths:

- Binary: `$HOME/.local/bin/fmg`.
- Skills: `$HOME/.codex/skills/fmg-api` and `$HOME/.codex/skills/fmg-research`.

If the host has a documented different user Skill directory, use the installer's `--skill-dir ABSOLUTE_DIRECTORY`. Do not modify `CODEX_HOME`, replace unrelated Skills or overwrite global Codex configuration to make these paths work.

If a matching CLI and both Skills already exist, verify them and skip unnecessary reinstalling. Preserve customized existing Skills and credentials. The installer keeps replaced Skills in `.previous`, `.previous-1`, etc. directories without deleting old backups. Review customized Skills before replacing. Keep retained backups outside active Skill discovery directories after an approved update.

## Updating an existing installation

For CLI 0.2.0 or newer, when the user asks you to update:

```sh
fmg upgrade --latest --skills
fmg version
fmg auth check
```

Use `--skill-dir ABSOLUTE_DIRECTORY` when the installed Skills live elsewhere. The latest selector considers only published numeric `fmg-vX.Y.Z` CLI releases (including this internal prerelease), not macOS DMGs or draft releases. It checks SHA256 and uses the verified matching installer. Python 3.10+ is needed for the combined update. Credentials and `FMG_CONFIG` are not rewritten. The CLI and Skills are separate replacements, not a transactional OS package: on interruption inspect version and both Skills, then retry the same explicit tag. Existing backups remain available.

**Upgrading 0.1.0:** it does not understand `--latest --skills`. Perform section 2 below using the 0.5.0 installer with `--skills`, specifying the existing binary directory via `--bin-dir` and existing Skill directory via `--skill-dir`. Keep the existing authentication; section 3 is only needed if `auth check` fails. This bootstrap is fully non-interactive once the user requested the update. Subsequent upgrades can use the command above. The installer also accepts `--latest` instead of `--tag`.

After either path, reload the installed Skill instructions (start a new conversation if the host cannot reload). Confirm both Skills include starting/ending host usage checks, estimated-cost reporting, plain-text emails and real IMAP replies. Read the installed email/outreach references again; do not retain old HTML or Yes/No workflow assumptions. Restart existing local dashboard processes to load the new page. Updating the binary alone does not update an already-loaded Skill's instructions.

**Update-aware clients:** when `fmg update check` is available, run it at the start of an FMG task. Normal authenticated remote commands also emit `fmg_update_notice` on stderr without changing business JSON/NDJSON. Checks use a six-hour release cache (failures fifteen minutes), never company API credits; `--refresh` checks immediately. `skill_version_unknown` is not proof that Skills are current. For custom locations, use `FMG_SKILL_DIR` or `--skill-dir` consistently when checking/upgrading. If the command is absent, the old client needs one bootstrap upgrade before it can discover later updates automatically. Notifications do not authorize software replacement: follow user approval or an existing auto-update preference, finish active operations, upgrade, then read the newly installed instructions from disk. An offline check must not interrupt or repeat business operations.

## 2. Download, inspect and install the explicit release

For a fresh supported environment, use a private temporary directory. Download the installer and checksum list over verified HTTPS, then check the installer before running it:

```sh
fmg_setup_dir=$(mktemp -d)
curl -fsSL --proto '=https' --proto-redir '=https' \
  https://github.com/Cedar-Zhang-OUTPUT/FindMeGamer/releases/download/fmg-v0.6.0/install.py \
  -o "$fmg_setup_dir/install.py"
curl -fsSL --proto '=https' --proto-redir '=https' \
  https://github.com/Cedar-Zhang-OUTPUT/FindMeGamer/releases/download/fmg-v0.6.0/SHA256SUMS \
  -o "$fmg_setup_dir/SHA256SUMS"
python3 - "$fmg_setup_dir" <<'PY'
import hashlib
from pathlib import Path
import sys
root = Path(sys.argv[1])
entries = [line.split() for line in (root / 'SHA256SUMS').read_text().splitlines()]
expected = next((row[0] for row in entries if len(row) == 2 and row[1] == 'install.py'), None)
actual = hashlib.sha256((root / 'install.py').read_bytes()).hexdigest()
if expected != actual:
    raise SystemExit('Installer checksum mismatch; do not execute it.')
print('Installer checksum verified.')
PY
```

Read the downloaded `install.py` using your file-reading tool before execution. Check that it downloads from the named repository, validates archive checksums and writes only to the intended binary/Skill destinations. Checksums detect corruption; they do not establish trust independently of the publisher. Stop if the downloaded content does not match the expected installation purpose.

Then run:

```sh
python3 "$fmg_setup_dir/install.py" --tag fmg-v0.6.0 --skills
"$HOME/.local/bin/fmg" version
"$HOME/.local/bin/fmg" --help
```

Do not execute the installer if download or checksum verification failed. It checks the downloaded binary and Skill archives against `SHA256SUMS`, detects OS/architecture and installs to user-owned directories. No `sudo` is normally required. Confirm the version reports `0.5.0` and both `SKILL.md` files exist. Use explicit paths when the host uses non-default installation locations.

For the current shell, you may prepend the binary directory to PATH:

```sh
export PATH="$HOME/.local/bin:$PATH"
```

Separate terminal tool calls may not retain this export. Continue using the absolute executable path if needed. Do not silently rewrite shell startup files; offer a persistent PATH change if the user wants one. Do not disable Gatekeeper, TLS verification or organizational security controls. If an unsigned binary needs OS approval, explain the normal approval step rather than bypassing it.

## 3. Authenticate without exposing credentials

First try `fmg auth check` if an existing configuration may already work. Reuse valid credentials for the intended gateway. Do not print the configuration file: it contains a secret. The CLI uses the OS user config directory (`~/Library/Application Support/fmg/config.json` on macOS; normally `~/.config/fmg/config.json` on Linux), or an explicit `FMG_CONFIG` file. Preserve any host-provided override.

If a token is needed, ask the user in the conversation:

> “CLI and Skills are installed. Please get your personal FMG access token from the administrator, save it in a private file on this machine, and tell me the file path. I do not need your YouTube, X, Google or AWS keys.”

Use the host's supported user-input mechanism. You can finish independent installation checks while awaiting the path, but do not invent a token, request server-admin access, reuse someone else's token or report the service ready before authentication succeeds. There is no anonymous token-issuance endpoint. If the user lacks a token, report **installed, awaiting authentication**.

After receiving the path, redirect that private file to stdin. Substitute the actual path; the placeholder below is not a real file:

```sh
"$HOME/.local/bin/fmg" auth login \
  --server https://44.233.174.193 \
  --token-stdin < "/absolute/path/to/private-fmg-token"
"$HOME/.local/bin/fmg" auth check
```

Do not `cat`/echo the token into tool output, put it in an argument, hardcode it in a script, include it in screenshots, or commit it. Login reads stdin until EOF; do not start an unattended interactive login waiting indefinitely for input. The CLI checks the token before replacing configuration and saves the configuration with mode 0600.

Do not log out or delete the supplied token file automatically after setup. `auth logout` removes only local configuration; server-side revocation is an administrator action.

## 4. Verify the setup without paid upstream work

Run these read-only gateway checks:

```sh
"$HOME/.local/bin/fmg" auth check
"$HOME/.local/bin/fmg" youtube describe search.list
"$HOME/.local/bin/fmg" x describe searchPostsRecent
"$HOME/.local/bin/fmg" twitch describe searchCategories
"$HOME/.local/bin/fmg" steam describe store.search
"$HOME/.local/bin/fmg" email templates
```

These read local gateway identity/catalog/template data, not YouTube/X/Gemini search results; they do not spend provider call quota. Catalog `availability: simulated` describes catalog verification coverage, not a switch into a fake-data mode. Catalog access alone does not prove every upstream permission or available balance. Do not run a search, enrichment, preview creation or send just to make installation look complete.

Relevant token scopes: `read` for platform operations; `email:enrich` for enrichment; `email:send` for previews and sending. Report missing scopes accurately. Ask the administrator to amend access; never bypass it.

## 5. Load Skills and explain capabilities

Read the installed `fmg-api/SKILL.md` and `fmg-research/SKILL.md`, then relevant references as needed. If the current Codex conversation does not refresh its Skill inventory, tell the user to start a fresh conversation or use the host's supported Skill reload. Do not invent a reload CLI command, edit Codex's model/permissions settings, or claim the Skills are registered just because files exist.

End with a short report in the user's language:

- CLI version and installation paths.
- Both Skills installed; whether a fresh conversation is needed.
- Authentication and read-only checks passed, or the exact remaining blocker.
- No research quota spent and no email sent by setup.
- Offer finding creators for a Steam game, finding more while deduplicating, explaining saved matches, finding public business emails and preparing outreach for approval.

Example next prompt:

> “Use fmg-research to find suitable YouTube, X and Twitch creators for this Steam game. Save the Game Profile, matching reasons and evidence locally. Do not send email.”

When no platforms or count are specified, the research Skill targets 10 supported matches per platform across YouTube, X and Twitch (30 total). Explicit user choices override this default. Report missing matches rather than padding results; the existing finite research budgets still apply.

## Troubleshooting and current limits

- **Command not found:** use the absolute binary path; distinguish missing PATH from failed installation.
- **Network/TLS timeout:** the CLI uses process proxy settings. Compare an unauthenticated health request through the proxy with a direct request if host network policy allows. A previously observed client-proxy failure was resolved by excluding only `44.233.174.193` via `NO_PROXY`. Do not globally disable the user's proxy; never use `--insecure`, remote HTTP or disabled certificate checks. Direct connections may not work in every environment.
- **401 / invalid token:** check the intended gateway and token; ask the administrator if invalid/revoked. Do not print the secret while troubleshooting.
- **403 / insufficient scope:** a valid token can lack a particular capability. Catalog success is not permission to send.
- **Installation failure:** inspect checksums, destination permissions and existing `.previous` Skill backups. Preserve the prior installation and user files; do not delete directories to force success.
- **Download/runtime permissions:** follow the host's approval mechanism. If blocked, explain it rather than claiming completion or finding a bypass.
- **Current service limits (2026-09-17):** SMTP is configured with an administrator-managed recipient allowlist; addresses outside that list are blocked. New mail is plain text only and has no Yes/No buttons. Outreach tasks expose actual IMAP replies and monitor health. Steam Store game lookup/recommendations work without a key; Steam Web API methods requiring a key are unavailable until configured. Twitch public reads and follower totals are included; detailed follower lists and private account data are not. Instagram is not included. YouTube/Steam/Twitch marginal API estimates are USD 0 under current assumptions, separately from quotas and hosting; X/Gemini estimates are not invoices. Skills check available Codex account quota before/after work; precise per-task consumption may still be unavailable.

This document contains no access token. Installing a public client does not grant access to company services or permission to send emails.
