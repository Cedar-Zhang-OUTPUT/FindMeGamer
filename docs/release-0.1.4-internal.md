# macOS 0.1.4 internal release

Published on 2026-09-07 at 07:45:10 UTC under the user's final release authorization. This supersedes the earlier source-only delivery of the second-pass UI. Development and performance investigation stop after this release; further work awaits a new product brief/PRD.

- Release: https://github.com/Cedar-Zhang-OUTPUT/FindMeGamer/releases/tag/v0.1.4-internal.1
- Download: https://github.com/Cedar-Zhang-OUTPUT/FindMeGamer/releases/download/v0.1.4-internal.1/FindMeGamer-0.1.4.dmg
- Release ID: `383908899`; published, not a draft; marked as an internal prerelease.
- Frozen application source / annotated tag target: `c90aaac4de6d2460a05fcf1344d026402046e64d`.
- Tag: `v0.1.4-internal.1`.
- Asset: `FindMeGamer-0.1.4.dmg`, 15,704,483 bytes; GitHub asset ID `548383181`.
- SHA-256: `38b5ef3cfef0a4d96fba70721ed1d52eae4f31fef9dabb77fcf40ec3e9799d57`.
- Checksum sidecar asset ID: `548383182`.
- Universal Apple Silicon / Intel; minimum macOS 14.
- Default: real service at `https://44.233.174.193`; Demo mode off.
- Ad-hoc signed, not Developer ID signed or notarized. Colleagues need private-repository access and the agreed manual macOS first-launch approval. No workspace, provider, or GitHub credentials are bundled.

## Included and excluded scope

The completed UI freeze `5e7cd2d`, integrated as `87313a6`, reduces repeated guidance and improves in-place facts/source details, explicit Match and recipient selection, per-email preview navigation, campaign filtering, template validation, and immediately observable Settings disclosures/confirmations. Existing analysis timing and client update discovery remain included. The frontend task confirmed that no additional completed production UI fix was omitted.

Performance-only commits `f05283a` and `75f94eb` are excluded. No window-drag or Stage Manager performance improvement is claimed. No backend application or API contract change, migration, production data mutation, analysis submission, or real email delivery was performed for this release. Previously published 0.1.3 assets and tag remain unchanged.

## Verification

- Repeated strict client suite: **329 tests in 44 suites passed**. The independent bounded UI source review returned GO.
- Release-script regression tests passed. Both release slices compiled with the macOS 14 target. `verify_release.sh --allow-adhoc` passed.
- Independent read-only DMG audit returned GO: disk-image/sidecar checksums, both Mach-O architectures and minimum OS, UUIDs matching the two build outputs, plist version/service/Demo settings, bundle strict signatures, installation instructions, and payload inspection passed.
- The actual loadable `Contents/Frameworks/libswiftCompatibilitySpan.dylib` is bundled with both architectures and valid signatures/install names; both executable slices have the Frameworks rpath. This is not a `.original` signing backup.
- The packaged app was copied out of the DMG and launched on the build Mac. Its About panel reported `0.1.4 (0.1.4)`. Restoring that Mac's existing credential waited for macOS Keychain authorization (`SecItemCopyMatching`); no system credential or security prompt was bypassed. Therefore this check does not claim authenticated GUI navigation. The temporary release app was closed; the pre-existing Demo instance was preserved.
- GitHub draft assets were downloaded again; the sidecar verified and the downloaded DMG was byte-for-byte identical to the independently verified local artifact. Publishing retained the asset IDs and matching GitHub digest.
- Manifest test TDD: 0.1.4 expectations failed against the old 0.1.3 configuration, then passed after the manifest-only change. Existing tests verified anonymous GET/HEAD, exact method/path isolation, unchanged backend routing, stdin validation/hot reload, and persistence after restarting an isolated test container. Test containers were cleaned up.
- Actual URLSession/AppUpdateChecker test failed as expected before promotion against the live 0.1.3 feed, then passed after promotion: **1 test in 1 suite**, 3.512 seconds. Installed 0.1.2 and 0.1.3 discover 0.1.4; installed 0.1.4 remains current. The live test is `liveApprovedManifestOffers014To012And013AndKeeps014Current`.
- Production HTTPS checks after promotion: manifest HTTP 200, JSON, `no-store`, `nosniff`; readiness healthy; unauthenticated session HTTP 401; authenticated session successful.

No separate physical Intel/macOS 14 machine run, complete VoiceOver traversal, Apple notarization, or real SMTP acceptance test is claimed.

## Manifest promotion without backend deployment

Root manifest commit: `ac49062149780517c88068ffd69b1e9ace74bf86`. Backend-only equivalent: `77d6f234de46942f769afb2c0a9d05b18db994ab`, based on `ecb3dea113c8116f6c128d0f249125b510f2290a`. Only `Caddyfile` and its corresponding operations test changed. The root live-update test adjustment is `50aef76`.

The existing server checkout was clean and matched the expected old commit. The exact two-path change was validated before fast-forwarding the checkout. New host Caddy bytes were then hot-loaded through stdin to avoid a stale single-file-bind inode. The existing API, Worker, Beat, proxy, Postgres, and Redis retained exactly the same container IDs and start times; all remained healthy. No Compose restart, backend rebuild, migration, or database operation was used.

The live feed is `https://44.233.174.193/updates/macos.json` and now points to the published 0.1.4 release. Update discovery opens the approved GitHub page; installation is still manual. Local network checks used the user's existing proxy; no local proxy configuration was copied to the server.

## Closure

Release, downloadable artifacts, source/tag, manifest promotion, and live update validation are complete. No follow-on feature or performance work is included. Real SMTP still awaits the separately planned mailbox configuration.
