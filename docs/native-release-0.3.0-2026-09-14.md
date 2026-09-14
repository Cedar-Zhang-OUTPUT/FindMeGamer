# Native 0.3.0 internal release and maintenance cutover

## Authorization and scope

The user accepted the native Profile editor by manual operation, authorized backend deployment/client publication, then explicitly approved retaining the v2 database and using a new empty native database with compatible settings/secrets only. No conversion of v2 business records was requested. This release restores SwiftUI, YouTube acquisition and Library-only Match; it does not carry over Electron activities or X collection.

Application source: `c880ccb134a862ec90259acdc4a50d156acf993a`, tag `v0.3.0-internal.1`. Operational update-manifest promotion is a separate change. The client is a universal ad-hoc internal build, macOS 14+, real service at `https://44.233.174.193`; no credentials are bundled. Apple notarization, physical Intel/macOS 14 acceptance and SMTP delivery are not claimed.

## Executed backend cutover

- EC2: `44.233.174.193`. Native source directory: `/opt/find-me-gamer-native-030`.
- Original database `find_me_gamer` remains intact at `20260913_0023`. Old application source in `/opt/find-me-gamer` is retained; its Caddyfile is the retained proxy mount and receives only the new client-update manifest. Original Caddy bytes remain in the rollback backup.
- Native database: `find_me_gamer_native_20260914`, migration head `20260914_native_0008`.
- Native image: `find-me-gamer-native:0.3.0-c880ccb`; API, Worker and Beat all use this image. Redis namespace `/1`, distinct from old `/0`; old queue was empty. Proxy, PostgreSQL and Redis containers were retained.
- Runtime files: `/etc/find-me-gamer/native.env` and `/opt/find-me-gamer-native-030/runtime.override.yaml`. The unchanged `/etc/find-me-gamer/master.key` remains protected. Original `app.env` is preserved.
- Native business tables were empty after migration/settings import: Game, Creator, Analysis, Match and deliveries all zero. Old business data include 1,122 Creators, one Game, two activities and 184 analysis jobs, none running.
- Compatible shared settings imported via five-column allowlist. All four service-secret ciphertexts (`deepseek`, `youtube`, `google_ai`, `x`) preserved and successfully decrypted; old health timestamps were cleared. Only supported DeepSeek/YouTube/Google AI connection probes were executed, all successful. DeepSeek `/models` includes `deepseek-flash`. X retained does not mean native X support; SMTP remains unconfigured.
- Existing Workspace Access Key authenticated successfully against both staged native API and public HTTPS. Readiness and both empty Library routes passed. No real analysis or email was triggered.

During preparation, an exported old `POSTGRES_DB` overrode the new Compose env file. Alembic rejected the old v2 revision before migration. After removing that inherited variable, an explicit native database-name assertion passed and native migrations completed. Full old-database inventory comparison confirmed it remained unchanged.

## Backup evidence

Protected rollback directory: `/var/backups/find-me-gamer/native-cutover-20260914`.

- Complete dump `v2.dump`, SHA-256 `18ef69b065ba176204a906faf56b127cfdec6b81c7eb8ef6a8cdfb1583909687`.
- S3: `s3://zhangyue-data-493392056671-us-west-2/backups/native-cutover-20260914/`, dump/checksum and encrypted configuration archive, SSE AES256.
- Restore-test database: `find_me_gamer_restore_20260914`, retained. Every public table's exact row count and sorted-row digest matched the old DB. Normalized full inventory SHA-256 before and after cutover: `4c9c47ec2541049473229e7e4da2a86601ed87b93c94a15b89847995044459b3`.
- Original master key, environment, Compose/Caddy configuration and image IDs retained under the protected directory. Configuration archive additionally encrypted using the existing master-key file; do not print or publish these files.
- Rollback image tags: `find-me-gamer-rollback:api-20260914`, `:worker-20260914`, `:beat-20260914`.
- Daily backup service uses drop-in `/etc/systemd/system/find-me-gamer-backup.service.d/native.conf` and `/usr/local/sbin/fmg-native-backup-030`, explicitly naming the native DB. This avoids relying on the unchanged PostgreSQL container's original `POSTGRES_DB`. Actual service run succeeded, uploading `20260914T102836Z-c880ccb-native.dump`; existing timer remains enabled.

## Operating this deployment

Use the native configuration, not the old deployment script:

```sh
cd /opt/find-me-gamer-native-030
sudo docker compose -p find-me-gamer --env-file /etc/find-me-gamer/native.env -f compose.yaml -f runtime.override.yaml ps
```

Do not use plain `up` to unnecessarily recreate the retained database services. Future API/Worker/Beat updates must retain the native DB and Redis namespace. The old `ops/deploy.sh` is not a converter and must not be run against the v2 database for this branch.

Rollback is a maintenance operation: stop native API/Worker/Beat, first preserve any new native writes, then explicitly select original `app.env`, original Compose configuration and the three rollback image tags together. Revert the backup-service drop-in and update feed to the old client only after deciding how to handle any new native records. Do not drop either DB or merge task queues. No rollback was needed for this deployment.

## Verification and publication

- Fresh backend full suite: 1,862 passed, 3 existing skips, one existing warning, 194.18 seconds.
- Release script regression suite passed.
- Update-manifest regression first failed against 0.1.4, then passed against 0.3.0, including exact route/method restrictions, hot reload and restart persistence.
- Automated editor walkthrough remained tool-blocked; user manual acceptance is recorded instead.
- Fresh native suite: default parallel run encountered three `waitUntilEntered` expectations; these helpers poll a fixed 1,000 `Task.yield()` turns. The explicit `--no-parallel` rerun passed all 344 tests / 49 suites in 0.491 seconds, without application or test-helper changes. Parallel-runner sensitivity remains a follow-up, not silently counted as a passing run.
- DMG verifier passed checksum, mount/structure, strict deep signatures, packaged compatibility runtime, both `x86_64 arm64` slices, minimum OS 14, version 0.3.0 and real-service/Demo-off metadata. Mounted artifact launched to the Workspace Access Key connection screen; no stored credential was overwritten and authenticated GUI traversal is not claimed.
- GitHub release published at `2026-09-14T10:32:40Z`, `isDraft=false`, `isPrerelease=true`: https://github.com/Cedar-Zhang-OUTPUT/FindMeGamer/releases/tag/v0.3.0-internal.1 . Historical releases/assets remain unchanged.
- DMG asset `563161604`, 15,494,172 bytes; checksum sidecar `563161605`. SHA-256 `29af9e5e25728997b4de626a5aae63f2c61cccd731cefc77ff56a5f56c36115a`. Downloaded the draft assets before publication, verified the sidecar and byte-compared the DMG against the local verified artifact; published metadata retains matching IDs/digest.
- Download: https://github.com/Cedar-Zhang-OUTPUT/FindMeGamer/releases/download/v0.3.0-internal.1/FindMeGamer-0.3.0.dmg .
- After publication, validated and hot-loaded the 0.3.0 update manifest, retaining proxy and application containers. Public manifest/readiness passed. The real URLSession/AppUpdateChecker live test passed (one test, 8.413 seconds): older native versions discover 0.3.0, installed 0.3.0 remains current.
- Final service snapshot: API, Worker, Beat, proxy, PostgreSQL and Redis healthy; native Celery queue empty. Removed only the temporary staging API container; production databases and all rollback backups remain available.

Backend deployment, client publication and update-feed promotion are complete. Colleagues can download the native client and start a fresh Library using the existing Workspace Access Key. SMTP still requires mailbox configuration before real delivery.
