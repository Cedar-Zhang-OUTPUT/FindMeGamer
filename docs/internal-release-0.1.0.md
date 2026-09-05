# Internal release 0.1.0

This is the pre-deployment, local-service macOS build for company testing.
The app connects to `http://127.0.0.1:8000`, requires a running backend on the
same Mac, and contains no service credentials or sample data. AWS deployment
and live cloud acceptance are separate follow-up work.

## Included changes

- The completed client and backend are integrated on one release branch.
- Creator email discovery supports Gemini fallback, multiple addresses,
  address purposes, and explicit recipient selection.
- Analyze and Match recover from transient polling failures; Outreach refreshes
  delivery status while a batch is queued or sending.
- Scheduled re-analysis records queue failures at the time they occur, rather
  than using the earlier scheduling cutoff. This prevents invalid completion
  timestamps and lets remaining jobs continue.
- Container integration uses the current DeepSeek JSON-object protocol and all
  six Creator Map-Reduce schemas. It covers Library, Match, captured outbound
  emails, Yes/No confirmation, duplicate prevention, and worker/Redis recovery.
- An ad-hoc signed universal DMG supports macOS 14+ on Apple Silicon and Intel.
  Installation steps are in [the macOS guide](../macos/README.md).

## Verification record

- Backend full suite: **1,680 passed, 3 skipped**. The skips are opt-in real-Redis
  cases; their three test modules were then run with an isolated
  `REAL_REDIS_URL`: **25 passed, no skips**.
- Scheduler and seed regression modules: **21 passed**; the queue-failure test
  reproduced the timestamp error before the production fix.
- Client suite on the merged source: **219 passed**; warnings-as-errors build
  passed.
- Fake provider contracts: **8 passed**, comprising six real-Gateway HTTP schema
  checks and two SMTP capture/no-network checks.
- Production-shaped container E2E: **passed in 70 seconds**, including health,
  Analyze, Library, Match, Outreach/Yes-No, duplicate prevention, Worker restart,
  Beat scheduling, and Redis recovery. Test containers, volumes, and image tags
  were removed after the run.
- DMG: checksum, read-only mount, bundle metadata, strict ad-hoc signature,
  and native LaunchServices launch passed on the build Mac. Both `arm64` and
  `x86_64` slices declare macOS 14.0 as their minimum system version. No Intel
  Mac was available for a separate runtime test.
- Apple's `swift-stdlib-tool` identifies and embeds the required Swift
  compatibility runtime under `Contents/Frameworks`; the app includes its
  relative runtime search path, so colleagues do not need Xcode installed.
- Independent code review found no blocking issues within the internal Demo
  scope. The source history was checked for accidental credentials and local
  data before upload.

The initial client test attempt reported one failure whose detail was truncated
by the command output. Subsequent complete runs passed; this remains a test
stability follow-up, not a reproduced application defect.

Synthetic provider/SMTP tests verify the application workflow. They do not
verify current external credentials, model availability, real SMTP delivery,
cloud DNS/TLS, or Apple's trust assessment on another Mac. This build is
ad-hoc signed and is not notarized; managed Macs may need IT approval for the
per-app Open Anyway exception.

DMG SHA-256:
`30d6c29607a854021eed7b7369fcfd98023b255b5b2bc326231311deb19af5a4`
