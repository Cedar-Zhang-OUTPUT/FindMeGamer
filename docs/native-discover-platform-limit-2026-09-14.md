# Discover per-platform quota hotfix

## Scope and behavior

User requested a quick backend deployment: each selected platform contributes at
most 20 new accounts after Library deduplication, so YouTube plus X yields at most
40. This replaces the shared 100-candidate cap that let X fill the entire result
before YouTube was searched. Library identities are excluded by platform and
account ID before consuming quota; duplicate page results also consume no slots.
Each platform keeps the existing bounded search budget (three pages, up to 100
sampled accounts). Twenty is an upper bound, not a guaranteed result count.

No schema or client contract changes. Existing completed Discover history is not
trimmed or replayed. Analyze, Match, email and credentials remain unchanged.
The existing native 0.4.0 client uses this server-side change without an update.

## Verification

- Source commit: `cec8ea9` on `codex/native-profile-editing`, pushed to GitHub.
- TDD: four targeted cases first failed against the shared cap; after the fix,
  34 related integration/provider tests passed. Cases include both platform
  orders, one platform, Library-only first page, later-page filling, duplicates,
  and partial retry preserving already found candidates.
- Full backend regression: **1,989 passed, 3 existing skips**, 145.99 seconds;
  one existing Starlette deprecation warning.
- Independent code review and separate deployment-script safety review: no
  blocking findings under the internal colleague Demo scope.

## Deployment, 2026-09-14 14:44 UTC

- Server: `44.233.174.193`.
- Current source: `/opt/find-me-gamer-native-040-platform20`.
- Image: `find-me-gamer-native:0.4.0-cec8ea9`, image prefix `7e8182b6b383`.
- API, Worker and Beat all inspected using that image and reporting healthy.
- Native database `find_me_gamer_native_20260914`, Redis database 1, original
  `/etc/find-me-gamer/native.env` and master-key mount retained.
- Idle work checked before stopping submissions and again afterward. No analysis,
  discovery, matching or batch jobs were interrupted. No migration was required.
- Fresh protected backup: `/var/backups/find-me-gamer/native-platform20-20260914`.
  Dump SHA-256: `c15dee6c114a3a2d1e53c4d0894a408ace8664a45effb714639e838f5db8252d`.
  `pg_restore --list` validated the archive; dump and checksum uploaded with
  SSE AES256 to the existing S3 `backups/native-platform20-20260914/` prefix and
  streamed back for byte comparison. All matched. This hotfix did not perform a
  fresh database restore drill; the preceding 0.4.0 release did.
- All database table counts and complete row digests matched before/after the
  stopped upgrade. No reset, deletion, seed or job retry was executed.
- Authenticated public HTTPS smoke: readiness 200, unauthenticated Discover 401,
  Game/Creator/Discover lists 200. Existing game and completed Discover remained;
  the original 100 X candidates were verified readable and unchanged.
- No paid provider search, model request or email was submitted during this
  hotfix's deployment smoke. Per-platform result behavior was validated against
  the real service/database/API with controlled external-provider fixtures.

## Operational entrypoint

```sh
cd /opt/find-me-gamer-native-040-platform20
sudo docker compose -p find-me-gamer --env-file /etc/find-me-gamer/native.env \
  -f compose.yaml -f runtime.override.yaml ps
```

Proxy, PostgreSQL and Redis containers were not recreated. The earlier native
0.4.0 source/image remain available for application rollback; do not reset data
or restore an old dump to revert this no-schema hotfix. Client release/update feed
remain 0.4.0. New Discover requests use the new quota; old history is retained.

Local evidence: `/tmp/fmg-discover-platform20-{regression,build,deploy,smoke,push}.log`.
Transient local tooling note: the optional formatter was absent from the test
image; rerunning pytest directly completed both targeted and full verification.
