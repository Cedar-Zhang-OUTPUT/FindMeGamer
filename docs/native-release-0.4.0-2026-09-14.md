# Native Discover 0.4.0 internal release

## Authorization and source

The user explicitly authorized backend deployment, full source upload to GitHub and a new native client release, and requested empty business data for fresh testing. Existing provider configuration and Workspace Access Key were to remain usable.

Application source and tag: `b1dc943247403f7153cb01c41d9fd5e139b7632d`, `v0.4.0-internal.1`. Full source branch: `codex/native-profile-editing`. Update-manifest follow-up: `fd767b7`; this release record is a subsequent documentation-only commit. No merge into the old v2 checkout or unrelated branch was performed.

Development evidence and independent review: [acceptance report](native-discover-acceptance-2026-09-14.md). Backend 1,986 passed / 3 existing skips; Swift 358 passed. Both scoped release-change review and the whole-feature review reported no blocking findings under the internal colleague Demo boundary.

## Backend deployment

- Server `44.233.174.193`; new source `/opt/find-me-gamer-native-040`.
- Image `find-me-gamer-native:0.4.0-b1dc943`, Docker image prefix `7227fbd0b118`; API, Worker and Beat use this image. Source archive local/remote SHA-256 matched `50bdba0abb1d0b073807eb33e8ee6eebf2ec365ff79effe1d75ac7c60e2e2b02`.
- Existing `/etc/find-me-gamer/native.env` and protected master key retained; native DB `find_me_gamer_native_20260914`, Redis `/1` explicitly asserted before migration.
- API/Worker/Beat were stopped together. Additive native0008→native0012 migration succeeded, then all three restarted and became healthy. Proxy/PostgreSQL/Redis containers were retained.
- Previous `/opt/find-me-gamer-native-030`, its image/configuration, old v2 source and old v2 database remain retained for recovery. They are not the current client's Library.

### Empty business data, configuration preserved

Before the upgrade, every current native business table was already empty. No deletion, reset, truncation or seed insertion was necessary. The stopped pre/post migration inventories matched exactly for every preexisting nonmigration table. All new Discover tables were also empty.

After startup and authenticated public reads, Game, Creator, contacts, Analysis/nodes, Discover/candidates/batches/items, Match inputs/results/stages, outreach campaigns/batches/deliveries/responses, templates and idempotency records remained **zero**. Four service-secret rows and the shared-settings row retained their exact predeployment digests. The analysis change-watermark row is system bookkeeping, not a business history record.

No real analysis, discovery, matching or email was submitted as a deployment smoke test. No SMTP was configured. YouTube and X capabilities report available based on configured credentials; Twitch/Instagram remain unavailable. These capability flags are not new paid live-provider verification.

## Backup and restore evidence

Protected directory: `/var/backups/find-me-gamer/native-040-20260914`.

- Full native dump SHA-256: `cb68e8034aab2ef47dcdb937a9011714ae9d1be6ce3be715fd0e74b78063a3ac`.
- Fresh restore database `find_me_gamer_native_restore_040_20260914` was created and retained. Its full table inventory matched the stopped native database exactly before migration.
- Original environment/master key/Compose/runtime override/Caddy/image IDs/backup script retained under the protected directory; configuration archive encrypted with the existing master-key file.
- Dump, checksum and encrypted configuration uploaded with SSE AES256 to `s3://zhangyue-data-493392056671-us-west-2/backups/native-040-20260914/`. Every uploaded object was downloaded as a stream and byte-compared against the original server file; all matched.
- Existing backup timer remains enabled. Its native script keeps the explicit native DB target and now labels future dumps `0.4.0-native`; an actual backup-service run returned `Result=success`.

## Client packaging and publication

Build command:

```sh
APP_VERSION=0.4.0 SERVICE_BASE_URL=https://44.233.174.193 \
ADHOC_RELEASE=1 RELEASE_ARCHITECTURES=universal RELEASE_FORMAT=dmg \
./script/build_release.sh
./script/verify_release.sh release/FindMeGamer-0.4.0.dmg --allow-adhoc
```

Verifier passed checksum, read-only DMG mount, installation instructions, bundle structure, strict deep ad-hoc signatures and compatibility-runtime packaging. Direct inspection verified `x86_64 arm64`, minimum macOS14, version0.4.0, `FMGDemoMode=false`, and the public HTTPS service address. No credentials are bundled. Apple notarization and physical Intel/macOS14 acceptance are not claimed.

The mounted release artifact actually launched, authenticated using the existing local Keychain credential and opened Discover. Its game picker showed an empty Library and the Steam URL entry. Library and Match opened with empty data; the app returned to Discover. No connection settings or credential was overwritten. An initial CLI Keychain read timed out awaiting access; a subsequent authorized read and the application authentication succeeded. This was not a backend outage.

GitHub prerelease published at `2026-09-14T14:25:45Z`, `draft=false`:

- [Release](https://github.com/Cedar-Zhang-OUTPUT/FindMeGamer/releases/tag/v0.4.0-internal.1)
- [DMG](https://github.com/Cedar-Zhang-OUTPUT/FindMeGamer/releases/download/v0.4.0-internal.1/FindMeGamer-0.4.0.dmg)
- [Versioned source](https://github.com/Cedar-Zhang-OUTPUT/FindMeGamer/tree/v0.4.0-internal.1)

DMG asset `563553211`, **17,284,738 bytes**, SHA-256 `2b477579f7be6c4a1553e8cbe0356f636b7362ecd67628bad41f53e4891f39ff`; checksum asset `563553210`. Both draft assets were downloaded before publication, the checksum verified, and the DMG byte-compared against the locally verified artifact. Published asset IDs/digests match. The remote tag dereferences to the exact source commit above; the complete branch was also pushed, not just binaries.

## Update feed and operational entrypoint

Manifest regression first failed against0.3.0, then passed against0.4.0, including exact GET/HEAD isolation, existing backend routes, stdin validation/hot reload and restart persistence. Release-script contract tests passed. After verified GitHub publication, Caddy config was validated and the version0.4.0 feed hot-loaded. Proxy container identity/start time remained unchanged. The persistent mount source `/opt/find-me-gamer/Caddyfile` and new native source Caddyfile both contain the promoted feed; unrelated proxy settings were preserved.

Public HTTPS readiness and the promoted manifest both returned200. The actual URLSession/AppUpdateChecker live test `FMG_VERIFY_LIVE_UPDATE=1 swift test --package-path macos --no-parallel --filter liveApprovedManifestOffers040AndKeeps040Current` passed: one test, 9.962 seconds. Older versions including0.3.0 receive0.4.0, while installed0.4.0 remains current.

Use only the current native deployment:

```sh
cd /opt/find-me-gamer-native-040
sudo docker compose -p find-me-gamer --env-file /etc/find-me-gamer/native.env \
  -f compose.yaml -f runtime.override.yaml ps
```

Do not run old `ops/deploy.sh`, repeat the empty-native cutover or drop retained databases. A future rollback requires a maintenance window, preservation of any new native writes, and explicit selection of the matching backup/image/configuration; no automatic downgrade or deletion is configured.

Local detailed logs: `/tmp/fmg-native-040-{build,verify,image,deploy,smoke,manifest-red,manifest-green,release-tests,promote,live-update}.log`. Transient preparation failure (runtime override not yet copied) happened before image build/deployment; retry waited for successful transfer. A redundant read-only migration probe had an unnecessary invalid module import, corrected without mutating data. Neither failure is counted as successful evidence.
