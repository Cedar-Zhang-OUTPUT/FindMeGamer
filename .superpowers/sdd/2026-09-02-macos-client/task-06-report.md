# Task 6 implementation report

## Outcome and scope

Implemented the shared changed-Job polling engine against immutable base
`8807c8efa759b9f3711131c634b62b11a069b330`. Production additions are limited
to `AppClock.swift` and `JobPoller.swift`; test additions are limited to
`Support/ManualClock.swift` and `JobPollerTests.swift`. No existing production
file, API service, OpenAPI/generated file, domain model, AppSession, UI, package
manifest, backend file, or build runner changed.

The required commit subject is `feat: poll shared cloud jobs`. Its exact commit
SHA and the immutable base-to-HEAD package byte count/SHA-256 are reported in
the post-commit handoff. They cannot be embedded in a file within that same
single commit without changing the identifiers they describe.

## TDD evidence

### RED

Before production files existed, the deterministic ManualClock and behavior
tests were added and the binding command was run:

```text
swift test --package-path macos --filter JobPollerTests
```

The command failed at compile time for the expected missing production
contract: `AppClock`, `JobChangeBatch`, and `JobPoller` were not in scope. The
output specifically reported `cannot find type 'AppClock' in scope`, `cannot
find type 'JobChangeBatch' in scope`, and repeated `cannot find 'JobPoller' in
scope`. This was the genuine missing-type RED required by the brief.

### GREEN and test refinement

After the smallest production implementation, Swift 6 first identified two
test coordination mistakes: an actor initializer captured itself while
assigning its consumer task, and two actor values were read inside a boolean
autoclosure. The event probe was made a lock-protected Sendable test helper and
the actor values were awaited separately. The next run exercised production
behavior: seven tests passed; Stop/Restart read the prior event immediately
after the second API call entered, before stream delivery. The test was changed
to wait on the consumer-visible second event rather than scheduling order.

Final focused result:

```text
Suite JobPollerTests passed
Test run with 8 tests in 1 suite passed
```

The focused suite was then run ten additional times with `--skip-build`; all
10/10 runs passed without wall-clock sleeps or scheduling-dependent failure.

## Production design

`AppClock` is a public Sendable protocol with one cancellable `sleep(for:)`.
`ContinuousAppClock` delegates directly to `ContinuousClock.sleep(for:)`; it
uses no timer, RunLoop, detached task, Date arithmetic, or Foundation clock.

`JobPoller` is an actor with a nonisolated `AsyncStream<JobChangeBatch>`. It has
one internal work task and explicit idle/syncing/sleeping phases. `start()` is
idempotent and schedules an immediate sync. `refreshNow()` schedules from idle,
cancels and replaces a pending sleep, or records one boolean follow-up while a
request is in flight. It never launches a parallel list request. `stop()`
increments a generation, cancels pending work, and preserves committed cursor
and active registry. All worker completions check task cancellation plus the
actor generation/running state before committing.

Each logical sync starts from the last committed opaque cursor, always passes
`status: nil`, drains every `hasMore` page in order, passes each page cursor
unchanged, and accumulates changes and first-seen profile IDs off-actor. Only a
complete successful drain reaches the actor commit. Later-page error or
cancellation produces no partial event, cursor update, or active-registry
change. Successful nonempty changes produce exactly one logical batch.

The active registry is keyed by an enum that distinguishes Analysis UUIDs from
Match UUIDs. Queued/running insert; succeeded/failed/superseded remove. Empty
pages leave the registry unchanged. The emitted `hasActiveJobs` reflects this
complete registry after the entire batch. A known active registry schedules one
exact three-second sleep after either success or transient failure; an idle
registry schedules none.

Batch Profile IDs are de-duplicated in first page/element encounter order.
Match task and Game IDs are derived only from Match changes and de-duplicated in
first-change order. No Campaign discriminator or ID was invented.

The stream termination handler captures the poller weakly and asynchronously
calls `stop()`. Worker tasks also capture the poller weakly. Poller deinit
cancels its worker and finishes the continuation, so no poller/stream/worker
retain cycle or View/feature-model reference exists.

## Deterministic test evidence

The purpose-built API actor records literal `(changedAfter, status)` calls and
maximum concurrency, returns scripted pages/errors/cancellation, and can hold a
request behind a cancellation-ignoring continuation gate. Its other protocol
methods are test-only `fatalError("unused")`; no network or provider is touched.

The focused tests prove:

- duplicate `start()` produces one immediate `(nil, nil)` request and maximum
  concurrency one;
- queued work requests exactly `.seconds(3)`, an empty incremental page retains
  it, a terminal change emits `hasActiveJobs == false`, and a 30-second manual
  advance produces no API churn;
- a two-page sync preserves exact item order, emits once, de-duplicates literal
  Profile/Match/Game UUIDs, passes a punctuation/Unicode cursor byte-for-byte,
  and commits only the final cursor for Refresh;
- both an ordinary error and `CancellationError` on page two emit no partial
  batch and the next manual Refresh restarts from the prior committed cursor,
  not the failed page cursor;
- Refresh cancels a pending sleep, starts immediately, coalesces three Refresh
  requests behind a held API call into one follow-up, retains max concurrency
  one, and uses the newly committed cursor;
- Stop cancels a sleep, a 30-second advance does not poll, an API completion
  deliberately released after Stop cannot emit or commit its stale cursor, and
  a second restart immediately uses the preserved committed cursor;
- cancelling the only stream consumer cancels pending polling; later clock
  advance produces no call;
- ManualClock records requested durations, advances only under explicit
  control, removes cancelled waiters, and resumes cancellation with
  `CancellationError`.

`ManualClock` is an actor. Each waiter has a monotonic test ID, Duration
deadline, and checked throwing continuation. `advance(by:)` resumes only due
waiters; the task cancellation handler removes and throws exactly the matching
waiter. All test waits are bounded Task.yield loops that throw rather than hang.
No test sleeps for real time.

## Full verification

- Focused JobPoller suite: 8 tests / 1 suite, 0 failures; repeated 10/10.
- Full Swift suite: 67 tests / 7 suites, 0 failures, 0.120 s.
- `swift build --package-path macos -Xswiftc -warnings-as-errors`: exit 0.
  Existing generated-target OpenAPI diagnostics remain under its pre-existing
  warning exception; Task 6/Core/App sources compiled strictly.
- All four changed Swift files pass `swift format lint --strict` and
  `git diff --check`.
- Scope audit finds only the four required code/test files plus this report.
- No secret/token string, runtime provider call, backend access, generated
  output, build product, or temporary file is tracked.

## Safe app launch and cleanup

`SERVICE_BASE_URL='invalid://local-verification'
./script/build_and_run.sh --verify` built and launched the real app bundle while
ensuring startup could not contact a backend or access a saved workspace key.
Bundle inspection returned `CFBundleIdentifier = com.findmegamer.desktop`,
`LSMinimumSystemVersion = 14.0`, and the intentionally invalid verification
URL. The exact launched PID was `37169`; `/bin/kill 37169` terminated only that
process, `kill -0` then failed, and `pgrep -x FindMeGamer` found no remainder.
The unchanged runner retains its normal localhost API default.

## Bounded concerns

None within the stable company-internal Demo boundary. WebSockets, persistent
local Job storage, background launch agents, public-scale fanout, extreme
cursor/volume defenses, Campaign polling, automatic mutation retry, and feature
UI/model wiring remain intentionally out of scope.
