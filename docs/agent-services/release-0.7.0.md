# FMG CLI / Skills 0.7.0 — Research completion and update awareness

- Required follower/subscriber lookup with platform-specific metrics, source and timestamp. Unqueried/blocked counts are incomplete, not a successful Unknown result.
- Required basic contact lookup and enrichment when absent; failed/pending enrichment cannot become Not Found. One selected email is displayed without purpose suffixes; alternate evidence remains internal.
- Published display/username/channel name can supply the public greeting. Unknown diagnostic strings are not valid email greetings.
- Local interactive game/filter review with persistent approval, stale-profile protection and bounded wait/status commands. Defaults: YouTube, X and Twitch, 10 per selected platform; no Instagram. Contact options: any / has email. Saving does not send mail or invoke platform discovery by itself.
- Stage-specific next-step guidance and updated completeness checks, preserving legacy/partial records visibly rather than overwriting them.
- `fmg update check [--refresh] [--skill-dir DIRECTORY]` and automatic structured stderr notifications during normal authenticated remote commands. Six-hour success cache, fifteen-minute failure cache, two-second network budget; business stdout and exit status are unchanged.
- Installer stamps both Skill versions independently. Upgrade guidance requires reading updated instructions from disk, preserving task IDs and never replaying completed work. Old clients need one bootstrap upgrade to acquire update awareness.

Upgrade: `fmg upgrade --latest --skills`, then `fmg version`, `fmg update check --refresh`, and re-read both installed Skills/current-stage references. Use the same custom Skill directory when applicable.

This is an internal prerelease. The release changes CLI/Skills/local scripts only, with no backend runtime, database, credentials or SMTP allowlist changes. Existing service remains running; publication does not send emails or spend provider credits.

Validation: Go suite; Python service suite (168 passed, four environment-dependent integration checks skipped); browser interaction tests on desktop/narrow view; both Skill validators; four-architecture build and actual isolated bundle installation. Public asset acceptance is checked after upload.
