# Install FindMeGamer CLI and Skills

Maintained with the FindMeGamer website. Verified release: **fmg-v0.8.4**, 2026-10-22.

Read this entire document before installing. Follow the user's instructions and your host's permission policies; this guide grants no additional authority. If the user asked you to install and your tools permit it, perform setup rather than merely restating these instructions.

## Scope and prerequisites

- CLI `fmg`, with companion Skills `fmg-api` and `fmg-research`.
- macOS or Linux, arm64/aarch64 or x86_64, Python 3.10+ for installation.
- This guide targets Codex with terminal and file tools. For another host, check its documented Skills support and directory before proceeding. Native Windows is not supported by this installer.
- No Docker, server deployment, compiler, or third-party provider API keys are needed.
- Service access requires a personal, revocable FMG token from your FMG administrator. There is no public self-service token issuance in this setup.
- Installation, update, and authentication do not authorize research, email enrichment, draft creation, or sending. Do not spend provider quota or send test email during setup.

Check OS, architecture, Python, and existing `fmg` before choosing an installation path. Preserve existing credentials, custom Skills and host configuration.

## Existing installations

For CLI 0.2.0 or later, after the user authorizes an update:

```sh
fmg upgrade --latest --skills
fmg version
fmg update check
```

The CLI-specific selector finds numeric `fmg-vX.Y.Z` releases, including published prereleases; GitHub's generic latest release may be an unrelated old macOS DMG. Do not use it. For 0.1.0 or an absent CLI, use the verified release procedure below. For an already correct installation, skip unnecessary replacement. If interrupted, inspect CLI and both Skill versions; do not assume the update is atomic.

## Fresh installation

Default binary destination: `$HOME/.local/bin/fmg`. Default Skills: `$HOME/.codex/skills/fmg-api` and `$HOME/.codex/skills/fmg-research`. Respect a host's custom Skill directory with the installer's `--skill-dir ABSOLUTE_DIRECTORY`. Do not change `CODEX_HOME` or delete unrelated Skills.

Download the installer and its checksums over verified HTTPS to a private temporary directory:

```sh
fmg_setup_dir=$(mktemp -d)
curl -fsSL --proto '=https' --proto-redir '=https' \
  https://github.com/Cedar-Zhang-OUTPUT/FindMeGamer/releases/download/fmg-v0.8.4/install.py \
  -o "$fmg_setup_dir/install.py"
curl -fsSL --proto '=https' --proto-redir '=https' \
  https://github.com/Cedar-Zhang-OUTPUT/FindMeGamer/releases/download/fmg-v0.8.4/SHA256SUMS \
  -o "$fmg_setup_dir/SHA256SUMS"
python3 - "$fmg_setup_dir" <<'PY'
import hashlib
import pathlib
import sys
root = pathlib.Path(sys.argv[1])
entries = [line.split() for line in (root / 'SHA256SUMS').read_text().splitlines()]
expected = next((row[0] for row in entries if len(row) == 2 and row[1].lstrip('*') == 'install.py'), None)
actual = hashlib.sha256((root / 'install.py').read_bytes()).hexdigest()
if not expected or expected != actual:
    raise SystemExit('Checksum mismatch: do not execute installer')
print('Installer checksum verified')
PY
```

Stop on any failed download or verification. Read `install.py` before executing: confirm the intended repository, checksum checks and destination handling. Checksums verify consistency with the publisher's manifest, not an independent publisher identity.

After review:

```sh
python3 "$fmg_setup_dir/install.py" --tag fmg-v0.8.4 --skills
"$HOME/.local/bin/fmg" version
"$HOME/.local/bin/fmg" --help
"$HOME/.local/bin/fmg" update check
```

Use explicit paths if PATH has not been updated. Do not silently rewrite shell startup files, bypass OS security checks, or require sudo. Preserve installer backups of replaced Skills. Read both installed `SKILL.md` files; reload Skills using the host's documented mechanism, or ask the user to start a fresh conversation. File presence alone does not prove the host loaded the Skills.

## Private authentication

First run `fmg auth check` if an existing configuration may work. Never print that configuration: it contains credentials. Keep an existing `FMG_CONFIG` override.

If authorization is missing, ask the user to obtain their personal token from the FMG administrator and save it in a private local file. Ask only for that file's path—not its contents in chat. Without a token, report **installed, awaiting authentication** and stop business operations.

For the current administrator-managed gateway, after the user supplies the token file:

```sh
"$HOME/.local/bin/fmg" auth login \
  --server https://44.233.174.193 \
  --token-stdin < "/absolute/path/to/private-fmg-token"
"$HOME/.local/bin/fmg" auth check
```

The path above is a placeholder. Use the actual user-supplied file; do not create a dummy token. Preserve the administrator's different gateway if explicitly configured. Never print/echo credentials, include them in arguments or screenshots, upload them, or commit them. Do not log out or delete token files automatically. Never disable TLS verification, use remote HTTP, or turn off the user's proxy globally.

## Read-only verification and handoff

After authentication, use help/catalog operations only:

```sh
fmg auth check
fmg youtube describe search.list
fmg twitch describe searchCategories
fmg x describe getUsersByUsername
fmg steam describe store.search
```

These read gateway metadata, not paid upstream search results. Missing scopes must be reported to the administrator, not bypassed. Use `email mailboxes` and `email templates` only when needed and permitted; never hardcode a game's sender or template from an old guide. Read the current installed Skills for business tasks and obtain separate approval before research/enrichment or outreach. Server acceptance is not a delivery guarantee.

Finish with CLI version, install paths, both Skill versions/reload status, authorization result and outstanding blockers. Confirm no paid research or emails were triggered during setup. Example next task, only after the user chooses to run it: “Find relevant creators for this Steam game, show reasons and evidence, and do not send email.”

Network errors do not prove a server task failed. For later business operations, query the same job/receipt and preserve idempotency keys; follow the installed Skill's bounded retry rules. Never blindly repeat a send or paid submission.
