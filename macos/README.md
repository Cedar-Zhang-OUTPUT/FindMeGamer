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

Build, stage, launch, and verify the app bundle with the intended service URL:

```sh
SERVICE_BASE_URL=https://workspace.example.com ./script/build_and_run.sh --verify
```

When `SERVICE_BASE_URL` is omitted, the runner uses `http://127.0.0.1:8000`. The runner writes
that address to the staged app's `Info.plist` as `FMGAPIBaseURL`, which the app reads at launch.

Enter the Workspace Access Key in the app. Enter SMTP and provider credentials only in Settings.
Never commit credentials to this repository. If the service becomes unavailable, the existing
workspace stays visible in read-only offline mode; use Retry when connectivity returns.

The local runner produces an unsigned app for development. Coworker distribution through a
signed and notarized build belongs to the deployment and release plan.
