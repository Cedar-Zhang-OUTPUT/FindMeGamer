# macOS 0.1.3 internal release

Published on 2026-09-07. The repository remains private; colleagues need repository access.

- Release: https://github.com/Cedar-Zhang-OUTPUT/FindMeGamer/releases/tag/v0.1.3-internal.1
- Source commit: `401f8b467b05b54c583f336489c77b085f3de76f`
- Asset: `FindMeGamer-0.1.3.dmg` (15,500,308 bytes)
- SHA-256: `9dcf517ba1722f1e5b621660b640f09160cb4d9b3b42a794471bb075774f6462`
- Universal Apple Silicon / Intel; minimum macOS 14.
- Default: real service at `https://44.233.174.193`; Demo mode is off.
- Ad-hoc signed, not Developer ID signed or notarized. The first launch still requires the agreed manual macOS approval.
- No provider, workspace, or GitHub credentials are bundled.

## Included client changes

The client uses actual task timestamps for elapsed time and adds manual and daily update discovery. Update discovery reads the anonymous HTTPS manifest, without workspace credentials or cookies, then opens the verified GitHub release page. It does not silently install updates. Users on 0.1.2 must manually install 0.1.3 once to obtain this feature.

The published package contains the loadable `Contents/Frameworks/libswiftCompatibilitySpan.dylib`. Release build and verification scripts check its exact filename, executable dependency, runtime install name, required architectures, and signatures. An earlier unpublished candidate was rejected by independent artifact review; it is not the published asset.

## Verification

- Integrated strict Swift suite: 312 tests across 41 suites passed.
- Release-script regression tests and `verify_release.sh --allow-adhoc`: passed.
- Independent read-only DMG mount: both executable slices, minimum OS, embedded runtime, and strict signatures passed.
- Published GitHub asset digest matches the locally verified package.
- Anonymous live manifest: HTTP 200, JSON version 0.1.3, `Cache-Control: no-store`, correct release page.
- Real URLSession test independently passed in both root and client worktrees: installed 0.1.2 discovers 0.1.3; installed 0.1.3 has no update.
- HTTPS readiness remained healthy. Unauthenticated workspace session remains HTTP 401; authenticated session succeeds.
- Manifest-only server change `0d405d720984c342bdf63d9ce05778ca2201d2f2` was hot-loaded through Caddy. All six container IDs and start timestamps remained unchanged.

No physical Intel/macOS 14 machine smoke test or notarization is claimed. Backend repair deployment is tracked separately and does not require rebuilding this client.
