# Find Me Gamer for macOS

Find Me Gamer requires macOS 14 or later. On macOS 26 or later, the app uses native Liquid
Glass enhancements on selected surfaces; macOS 14 and 15 keep the standard native appearance.

From the repository root, synchronize the generated API contract before building:

```sh
./script/sync_openapi.sh
```

Run the macOS test suite with:

```sh
swift test --package-path macos
```

To browse every client area with deterministic local sample data and no backend, credentials,
network requests, or real email delivery, run:

```sh
./script/build_and_run.sh --demo
```

The app displays a blue Local Demo Data banner for this mode. Demo changes last only until the
app is closed.

Build, stage, launch, and verify the app bundle with the intended service URL:

```sh
SERVICE_BASE_URL=https://workspace.example.com ./script/build_and_run.sh --verify
```

When `SERVICE_BASE_URL` is omitted, the runner uses `http://127.0.0.1:8000`. The runner writes
that address to the staged app's `Info.plist` as `FMGAPIBaseURL`, which the app reads at launch.

Enter the Workspace Access Key in the app. Enter SMTP and provider credentials only in Settings.
Never commit credentials to this repository. If the service becomes unavailable, the existing
workspace stays visible in read-only offline mode; use Retry when connectivity returns.

## Internal DMG distribution

Build the internal ad hoc signed release, without a Developer ID or notarization:

```sh
./script/build_dmg.sh
./script/verify_release.sh release/FindMeGamer-0.1.0.dmg --allow-adhoc
(cd release && shasum -a 256 -c FindMeGamer-0.1.0.dmg.sha256)
```

The DMG contains `FindMeGamer.app`, an Applications shortcut,
and English installation instructions. Drag the app to Applications, eject the image, and
launch it. If macOS blocks the first launch, use **System Settings > Privacy & Security >
Open Anyway**, then confirm Open. Only approve the build received from the trusted team;
there is no need to disable Gatekeeper globally. Company device policies can restrict this
override. See [Apple's instructions](https://support.apple.com/en-us/102445).

The default is a universal Apple Silicon + Intel macOS 14+ client in real-service mode,
connected to `http://127.0.0.1:8000`. A backend must run on the same Mac; the DMG does not
include it, credentials, or sample data. Backend startup instructions are in
[`docs/local-real.md`](../docs/local-real.md). Use the Workspace Access Key from that
backend. Once the cloud service is deployed, rebuild with its HTTPS address:

```sh
APP_VERSION=0.1.1 SERVICE_BASE_URL=https://workspace.example.com ./script/build_dmg.sh
```

`RELEASE_ARCHITECTURES=native` builds only the current Mac architecture. Set
`SWIFT_SCRATCH_PATH` to an existing SwiftPM build directory to reuse build caches. Existing
versioned artifacts are never overwritten; choose a new version or move the prior artifacts
aside before rebuilding. Demo data remains an explicit development option through
`./script/build_and_run.sh --demo`.

The existing `script/build_release.sh` Developer ID + notarized ZIP workflow remains
available for wider distribution.

## Multi-email recipient safety

Creator Profiles preserve and display the service-provided email order, purpose, source, and
validation state. Outreach with one active address can proceed without an explicit selection.
When a Creator has multiple active addresses, the composer requires the user to choose exactly
one before preview or send; it never defaults to the first address and never sends to every
address. The server-rendered preview must confirm that exact selection before sending is enabled.
