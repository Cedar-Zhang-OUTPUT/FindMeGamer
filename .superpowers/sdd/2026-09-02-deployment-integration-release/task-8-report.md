# Deployment Task 8 report

## Scope and base

- Immutable base: `ac17fd06c3bb125803b92161b069c9021a067998`
- Scope: package and verify the existing SwiftPM macOS executable as a signed,
  notarized coworker ZIP, with an explicit local ad hoc validation path.

## TDD RED

The focused release contract was created and made executable before either
production release script or the entitlements file existed:

```text
$ bash script/tests/test_release_scripts.sh
missing executable script/build_release.sh
task8_RED_exit=1
```

No signing identity, Keychain, network, app, or release artifact was touched.

## GREEN implementation

- `script/build_release.sh` validates a strict HTTPS origin and three-component
  release version, preflights the exact Developer ID identity and named
  notarytool Keychain profile, builds the SwiftPM release executable, and
  stages a fresh private `FindMeGamer.app` with the existing bundle contract.
- The executable is signed before the app. Developer ID signing uses Hardened
  Runtime, secure timestamp, and the checked-in empty entitlement dictionary.
  The private submission ZIP is created before notarization; only after an
  Accepted result does the script staple and validate the ticket, strictly
  verify the signature, run Gatekeeper assessment, and build the final
  post-staple coworker ZIP.
- Final ZIP and basename-bearing SHA-256 sidecar are published through a
  private same-filesystem directory, with overwrite refusal and trap removal
  of any partial final publication. Staging cleanup is limited to validated
  private `mktemp` paths. The existing `dist/FindMeGamer.app` is never read or
  mutated.
- `script/verify_release.sh` checks the sidecar before private extraction,
  requires exactly one top-level app and executable, validates every required
  plist value and archive-name version, and always performs strict deep
  codesign verification. Real artifacts additionally require Gatekeeper and a
  stapled ticket; `--allow-adhoc` visibly skips only those trust/notary checks.
- `macos/FindMeGamer.entitlements` is a valid empty plist dictionary, and the
  only ignore-rule change is exact `/release/`.

## TDD GREEN and fake evidence

The completed focused test uses strict argv-recording fakes for Swift,
Security, codesign, xcrun/notarytool/stapler, Gatekeeper, plist, ditto, and
checksum commands. The fakes do not access a real signing identity, Keychain
profile, network, or application. They exercise:

- exact identity/profile preflight before build, both release-mode Swift
  invocations, executable-before-app signing, runtime/timestamp/entitlements,
  and notary → staple → ticket → strict signature → Gatekeeper → final ZIP
  ordering;
- missing/invalid inputs, HTTP/path URL, invalid version, unknown argument,
  build failure, absent executable, identity/profile failure, signing failure,
  notary rejection, staple/ticket failure, plist/signature/Gatekeeper failure,
  and refusal to overwrite preserved final files;
- checksum-before-extraction, checksum mismatch, missing sidecar, malformed
  ZIP, version-mismatched bundle metadata, symlink input, and unexpected
  top-level payload;
- a Developer artifact containing the fake stapled-ticket effect in the final
  ZIP, exact bundle metadata, deterministic archive name/sidecar, and an ad hoc
  path with no Security, notarytool, stapler, or Gatekeeper calls.

Workspace/provider/SMTP canaries are inherited by every fake but are absent
from argv, output, and the built archive.

Final focused suite, twice:

```text
$ bash script/tests/test_release_scripts.sh
PASS: fake Developer ID/notary and ad hoc release contracts
PASS: release script contract
$ bash script/tests/test_release_scripts.sh
PASS: fake Developer ID/notary and ad hoc release contracts
PASS: release script contract
```

## Real local ad hoc verification

The documented real local path built, staged, ad hoc signed, archived,
checksummed, privately extracted, and strictly verified the actual SwiftPM app:

```text
$ ADHOC_RELEASE=1 SERVICE_BASE_URL=https://example.invalid APP_VERSION=0.1.0 ./script/build_release.sh
PASS ad hoc bundle signature
PASS release artifact published
$ ./script/verify_release.sh release/FindMeGamer-0.1.0.zip --allow-adhoc
PASS checksum
PASS ad hoc release verification (trust and notarization acceptance skipped)
```

The exact generated `release/FindMeGamer-0.1.0.zip` and adjacent sidecar were
then removed with `unlink`, and the now-empty exact release directory was
removed. No other artifact was deleted.

## Broader verification and gates

- `swift test --package-path macos`: **184 tests in 20 suites passed**.
- `swift build --package-path macos -c release`: completed successfully. The
  generated OpenAPI nullable warnings are the repository's known generated
  target warnings; the build completed.
- Task 1–7 operator/Compose tests, `integration/run.sh --contract`, and the
  fake-backed Task 7 operator test passed. The existing debug runner's Bash
  syntax and bundle-name/identifier/API-key structure checks passed without
  launching an application.
- `bash -n` passed for all new scripts. `plutil -lint` passed and independent
  decoding proved the entitlement root is an empty dictionary. Forbidden
  sandbox/network/get-task-allow/unsigned-memory/library-validation entitlement
  scans passed.
- Exact scope, executable modes, exact `/release/` ignore rule,
  secret/private-key, command-argument, destructive-target, release/certificate
  artifact, and `git diff --check` gates passed. ShellCheck and shfmt are not
  installed.

No real Developer ID signing, notarization, Gatekeeper acceptance, Keychain
access, network, provider, AWS, SMTP, app launch, or production mutation was
performed. No binding concerns remain.
