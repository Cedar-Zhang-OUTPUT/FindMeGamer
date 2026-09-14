# Native restoration maintenance cutover

Status: deployment and client publication completed on 2026-09-14; see [executed cutover and release evidence](native-release-0.3.0-2026-09-14.md). The user confirmed keeping the complete v2 database and switching the native release to a new empty database, importing only compatible settings and service secrets. The checklist below remains the procedure for future maintenance; it is not authorization for another data reset.

## Why a separate database

The deployed v2 schema previously reached `0023`; native now ends at `20260914_native_0008`, parent `20260904_0007`. A shared numeric suffix does not make schemas compatible. Never downgrade production `0023` and never point native API/Worker/Beat at the v2 database. [Local acceptance evidence](native-profile-editing-acceptance-2026-09-14.md) is not a live cutover record.

## Release checkpoint

1. Isolated tests, real HTTP client verification and bounded whole-branch review have passed. The user manually checked the editor and reported no issue after automation repeatedly crashed. The new-outreach-preview propagation gap was fixed in `de7e962`. This is user GUI acceptance, not a claim that the automation walkthrough succeeded.
2. Read the live database head, business table counts, active jobs, queue state and configured services again. The September 13 reset is not evidence that the database is still empty.
3. If any business data exists, obtain the user's choice of preserving/migrating it before any switch. There is no current authorization to discard it. This restoration does not contain a general v2-to-native business-data converter.
4. Agree a maintenance window. Stop API, Worker and Beat for the actual switch; no old/new Worker concurrency is required.

## Backup and preparation

- Create a fresh complete PostgreSQL dump, retain application/environment/master-key backup using the existing protected process, record checksum and restore successfully to a distinctly named temporary database. Compare migration head, table counts, representative foreign-key relationships and settings with the backup-time inventory. Record commands, exit status and checks without printing secrets. This implementation task has not executed backup/restore.
- Create a distinctly named native target database and run the native branch migrations into it; leave the original v2 database intact.
- Import only compatible shared settings through an explicit column allowlist: workspace name, Creator/Game intervals, match threshold and SMTP rate. Do not carry over unsupported v2 channel/activity configuration as if native code consumed it.
- Preserve `service_secrets` ciphertext/nonce only when the encryption implementation, associated-data/service naming and master key are confirmed compatible. Test decryption without printing plaintext. Keep the old database/master key untouched; if incompatible, use an explicit secret re-entry or controlled conversion, not guessing.
- Recompute connection/health state instead of presenting old last-success values as fresh provider verification. A retained X secret does not imply this native baseline supports X collection.
- Run local-only health, authentication, profile editing/reset and Match snapshot checks on the staged native stack. Do not send email.

## Switch and rollback

During the approved window, select the new image and new database connection together, start API/Worker/Beat, and verify health/authentication and reads before distributing a cloud-targeted native DMG. Pin the old image digest, client artifact/checksum, environment, queue namespace and original database as an immutable rollback set. If verification fails, stop native, restore the previous application/environment/database selection and verify the old service. Preserve new native writes for an explicit reconciliation decision; rollback must not silently discard them or replay them into v2. Do not merge queues from the two lineages.

Package as a new internal release without overwriting Electron assets or native historical releases. Verify embedded service address, minimum macOS version, architecture, mounted-DMG launch, signing mode, SHA-256 and the uploaded GitHub asset. Local source tests alone are not publication evidence.
