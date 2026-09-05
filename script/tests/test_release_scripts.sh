#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
build_script="${repository_root}/script/build_release.sh"
verify_script="${repository_root}/script/verify_release.sh"
entitlements="${repository_root}/macos/FindMeGamer.entitlements"

[[ -x "$build_script" ]] || { echo "missing executable script/build_release.sh" >&2; exit 1; }
[[ -x "$verify_script" ]] || { echo "missing executable script/verify_release.sh" >&2; exit 1; }
[[ -f "$entitlements" ]] || { echo "missing macos/FindMeGamer.entitlements" >&2; exit 1; }

/usr/bin/plutil -lint "$entitlements" >/dev/null
python3 - "$entitlements" <<'PY'
import plistlib
import sys

with open(sys.argv[1], "rb") as stream:
    assert plistlib.load(stream) == {}
PY
[[ "$(grep -Fxc '/release/' "${repository_root}/.gitignore")" -eq 1 ]]
rg -Fq -- '--package-path "$package_dir" -c release' "$build_script"
rg -Fq -- '--options runtime' "$build_script"
rg -Fq -- '--timestamp' "$build_script"
rg -Fq 'notarytool submit' "$build_script"
rg -Fq 'stapler staple' "$build_script"
rg -Fq 'spctl' "$build_script"

python3 - "$repository_root" "$build_script" "$verify_script" "$entitlements" <<'PY'
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import stat
import subprocess
import sys
import tempfile


root, build_script, verify_script, entitlements = map(Path, sys.argv[1:])
release_dir = root / "release"
version = "1.2.3"
archive = release_dir / f"FindMeGamer-{version}.zip"
sidecar = Path(str(archive) + ".sha256")


def run(command: list[str], environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=root,
        env=environment,
        text=True,
        capture_output=True,
        timeout=45,
    )


def remove_artifacts() -> None:
    for candidate in (archive, sidecar):
        if candidate.exists() or candidate.is_symlink():
            candidate.unlink()


def calls(log: Path) -> list[dict[str, object]]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def rearchive(source: Path, destination: Path) -> None:
    if destination.exists():
        destination.unlink()
    subprocess.run(
        ["/usr/bin/ditto", "-c", "-k", "--keepParent", str(source), str(destination)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    Path(str(destination) + ".sha256").write_text(
        f"{digest}  {destination.name}\n", encoding="utf-8"
    )


fake_tool_source = r'''#!/usr/bin/env python3
import json, os, pathlib, shutil, subprocess, sys

tool = pathlib.Path(sys.argv[0]).name
arguments = sys.argv[1:]
log = pathlib.Path(os.environ["FMG_RELEASE_FAKE_LOG"])
with log.open("a", encoding="utf-8") as stream:
    stream.write(json.dumps({"tool": tool, "args": arguments}) + "\n")
mode = os.environ.get("FMG_RELEASE_FAKE_MODE", "ok")

if tool == "swift":
    if "--show-bin-path" in arguments:
        print(os.environ["FMG_RELEASE_FAKE_BIN_DIR"])
        raise SystemExit(0)
    raise SystemExit(7 if mode == "build-failure" else 0)

if tool == "security":
    if mode == "identity-missing":
        print('  1) OTHER "Developer ID Application: Other Corp (OTHER)"')
    else:
        identity = os.environ["DEVELOPER_ID_APPLICATION"]
        print(f'  1) HASH "{identity}"')
    raise SystemExit(0)

if tool == "codesign":
    if "--verify" in arguments:
        raise SystemExit(13 if mode == "bundle-verification-failure" else 0)
    raise SystemExit(12 if mode == "signing-failure" else 0)

if tool == "xcrun":
    if arguments[:2] == ["notarytool", "history"]:
        if mode == "profile-failure":
            raise SystemExit(14)
        print('{"history": []}')
        raise SystemExit(0)
    if arguments[:2] == ["notarytool", "submit"]:
        print('{"status": "Rejected"}' if mode == "notary-rejection" else '{"status": "Accepted"}')
        raise SystemExit(0)
    if arguments[:2] == ["stapler", "staple"]:
        if mode == "staple-failure":
            raise SystemExit(15)
        app = pathlib.Path(arguments[-1])
        marker = app / "Contents" / "_CodeSignature" / "notary-ticket"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("stapled", encoding="utf-8")
        raise SystemExit(0)
    if arguments[:2] == ["stapler", "validate"]:
        if mode == "ticket-failure":
            raise SystemExit(16)
        marker = pathlib.Path(arguments[-1]) / "Contents" / "_CodeSignature" / "notary-ticket"
        raise SystemExit(0 if marker.is_file() else 17)
    raise SystemExit(18)

if tool == "spctl":
    raise SystemExit(19 if mode == "gatekeeper-failure" else 0)

if tool == "plutil":
    if mode == "plist-failure":
        raise SystemExit(20)
    completed = subprocess.run(["/usr/bin/plutil", *arguments], check=False)
    raise SystemExit(completed.returncode)

if tool == "ditto":
    completed = subprocess.run(["/usr/bin/ditto", *arguments], check=False)
    raise SystemExit(completed.returncode)

if tool == "lipo":
    if arguments[0] == "-create":
        shutil.copy2(arguments[1], arguments[-1])
    elif arguments[1:] != ["-verify_arch", "arm64", "x86_64"]:
        raise SystemExit(22)
    raise SystemExit(0)

if tool == "hdiutil":
    if arguments[0] == "create":
        if mode == "dmg-failure":
            raise SystemExit(21)
        source = arguments[arguments.index("-srcfolder") + 1]
        raise SystemExit(subprocess.run(["/usr/bin/ditto", "-c", "-k", source, arguments[-1]]).returncode)
    if arguments[0] == "verify":
        raise SystemExit(0)
    if arguments[0] == "attach":
        destination = arguments[arguments.index("-mountpoint") + 1]
        raise SystemExit(subprocess.run(["/usr/bin/ditto", "-x", "-k", arguments[1], destination]).returncode)
    if arguments[0] == "detach":
        raise SystemExit(0)

if tool == "shasum":
    completed = subprocess.run(["/usr/bin/shasum", *arguments], check=False)
    raise SystemExit(completed.returncode)

raise SystemExit(99)
'''


with tempfile.TemporaryDirectory(prefix="fmg-release-test.") as temporary:
    test_root = Path(temporary)
    tools = test_root / "tools"
    tools.mkdir()
    tool_paths: dict[str, Path] = {}
    for name in ("swift", "security", "codesign", "xcrun", "spctl", "plutil", "ditto", "shasum", "hdiutil", "lipo"):
        path = tools / name
        path.write_text(fake_tool_source, encoding="utf-8")
        path.chmod(0o700)
        tool_paths[name] = path

    binary_dir = test_root / "bin"
    binary_dir.mkdir()
    binary = binary_dir / "FindMeGamer"
    binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    binary.chmod(0o700)
    log = test_root / "commands.log"

    base_environment = os.environ.copy()
    base_environment.update(
        {
            "FMG_RELEASE_TEST_MODE": "1",
            "FMG_SWIFT_BIN": str(tool_paths["swift"]),
            "FMG_SECURITY_BIN": str(tool_paths["security"]),
            "FMG_CODESIGN_BIN": str(tool_paths["codesign"]),
            "FMG_XCRUN_BIN": str(tool_paths["xcrun"]),
            "FMG_SPCTL_BIN": str(tool_paths["spctl"]),
            "FMG_PLUTIL_BIN": str(tool_paths["plutil"]),
            "FMG_DITTO_BIN": str(tool_paths["ditto"]),
            "FMG_SHASUM_BIN": str(tool_paths["shasum"]),
            "FMG_RELEASE_FAKE_LOG": str(log),
            "FMG_RELEASE_FAKE_BIN_DIR": str(binary_dir),
            "SERVICE_BASE_URL": "https://service.example.com",
            "APP_VERSION": version,
            "DEVELOPER_ID_APPLICATION": "Developer ID Application: Demo Corp (TEAMID)",
            "NOTARY_PROFILE": "find-me-gamer-notary",
            "WORKSPACE_ACCESS_KEY": "WORKSPACE-SECRET-CANARY",
            "DEEPSEEK_API_KEY": "PROVIDER-SECRET-CANARY",
            "SMTP_PASSWORD": "SMTP-SECRET-CANARY",
        }
    )

    def build(mode: str = "ok", *, adhoc: bool = False) -> subprocess.CompletedProcess[str]:
        remove_artifacts()
        log.write_text("", encoding="utf-8")
        environment = base_environment | {"FMG_RELEASE_FAKE_MODE": mode}
        if adhoc:
            environment["ADHOC_RELEASE"] = "1"
            environment["SERVICE_BASE_URL"] = "https://example.invalid"
            environment.pop("DEVELOPER_ID_APPLICATION", None)
            environment.pop("NOTARY_PROFILE", None)
        return run([str(build_script)], environment)

    developer = build()
    assert developer.returncode == 0, developer.stderr
    assert archive.is_file() and sidecar.is_file()
    preserved_archive = archive.read_bytes()
    preserved_sidecar = sidecar.read_bytes()
    overwrite = run([str(build_script)], base_environment)
    assert overwrite.returncode != 0
    assert archive.read_bytes() == preserved_archive and sidecar.read_bytes() == preserved_sidecar
    expected_digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    assert sidecar.read_text(encoding="utf-8") == f"{expected_digest}  {archive.name}\n"
    recorded = calls(log)
    observable = developer.stdout + developer.stderr + log.read_text(encoding="utf-8")
    for secret in ("WORKSPACE-SECRET-CANARY", "PROVIDER-SECRET-CANARY", "SMTP-SECRET-CANARY"):
        assert secret not in observable and secret.encode() not in archive.read_bytes()

    def index_of(predicate) -> int:
        return next(index for index, call in enumerate(recorded) if predicate(call))

    identity_index = index_of(lambda call: call["tool"] == "security")
    profile_index = index_of(lambda call: call["tool"] == "xcrun" and call["args"][:2] == ["notarytool", "history"])
    build_index = index_of(lambda call: call["tool"] == "swift" and "--show-bin-path" not in call["args"])
    swift_calls = [call for call in recorded if call["tool"] == "swift"]
    assert swift_calls and all("--package-path" in call["args"] and "-c" in call["args"] for call in swift_calls)
    assert all(call["args"][call["args"].index("-c") + 1] == "release" for call in swift_calls)
    sign_calls = [call for call in recorded if call["tool"] == "codesign" and "--sign" in call["args"]]
    assert identity_index < build_index and profile_index < build_index
    assert len(sign_calls) == 2
    assert all("--options" in call["args"] and "runtime" in call["args"] for call in sign_calls)
    assert all("--timestamp" in call["args"] and "--entitlements" in call["args"] for call in sign_calls)
    assert sign_calls[0]["args"][-1].endswith("/Contents/MacOS/FindMeGamer")
    assert sign_calls[1]["args"][-1].endswith("/FindMeGamer.app")
    submit_index = index_of(lambda call: call["tool"] == "xcrun" and call["args"][:2] == ["notarytool", "submit"])
    staple_index = index_of(lambda call: call["tool"] == "xcrun" and call["args"][:2] == ["stapler", "staple"])
    ticket_index = index_of(lambda call: call["tool"] == "xcrun" and call["args"][:2] == ["stapler", "validate"])
    verify_index = index_of(lambda call: call["tool"] == "codesign" and "--verify" in call["args"])
    gatekeeper_index = index_of(lambda call: call["tool"] == "spctl")
    final_zip_index = max(index for index, call in enumerate(recorded) if call["tool"] == "ditto" and "-c" in call["args"])
    assert submit_index < staple_index < ticket_index < verify_index < gatekeeper_index < final_zip_index
    submit = recorded[submit_index]["args"]
    assert "--wait" in submit and "--keychain-profile" in submit
    assert submit[submit.index("--keychain-profile") + 1] == "find-me-gamer-notary"

    extracted = test_root / "extracted"
    subprocess.run(["/usr/bin/ditto", "-x", "-k", str(archive), str(extracted)], check=True)
    app = extracted / "FindMeGamer.app"
    assert (app / "Contents" / "_CodeSignature" / "notary-ticket").is_file()
    with (app / "Contents" / "Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    assert info == {
        "CFBundleDisplayName": "Find Me Gamer",
        "CFBundleExecutable": "FindMeGamer",
        "CFBundleIdentifier": "com.findmegamer.desktop",
        "CFBundleName": "Find Me Gamer",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
        "FMGAPIBaseURL": "https://service.example.com",
        "FMGDemoMode": False,
        "LSMinimumSystemVersion": "14.0",
        "NSPrincipalClass": "NSApplication",
    }

    log.write_text("", encoding="utf-8")
    verified = run([str(verify_script), str(archive)], base_environment)
    assert verified.returncode == 0, verified.stderr
    verify_calls = calls(log)
    assert any(call["tool"] == "codesign" and "--deep" in call["args"] and "--strict" in call["args"] for call in verify_calls)
    assert any(call["tool"] == "spctl" and "--type" in call["args"] and "execute" in call["args"] for call in verify_calls)
    assert any(call["tool"] == "xcrun" and call["args"][:2] == ["stapler", "validate"] for call in verify_calls)

    original_sidecar = sidecar.read_bytes()
    sidecar.write_text("0" * 64 + f"  {archive.name}\n", encoding="utf-8")
    log.write_text("", encoding="utf-8")
    checksum_failure = run([str(verify_script), str(archive)], base_environment)
    assert checksum_failure.returncode != 0
    assert not any(call["tool"] == "ditto" for call in calls(log))
    sidecar.write_bytes(original_sidecar)

    assert run([str(verify_script), str(archive), "--unexpected"], base_environment).returncode != 0
    sidecar.unlink()
    assert run([str(verify_script), str(archive)], base_environment).returncode != 0
    remove_artifacts()

    for bad_environment in (
        {key: value for key, value in base_environment.items() if key != "SERVICE_BASE_URL"},
        {key: value for key, value in base_environment.items() if key != "DEVELOPER_ID_APPLICATION"},
        {key: value for key, value in base_environment.items() if key != "NOTARY_PROFILE"},
        base_environment | {"SERVICE_BASE_URL": "http://service.example.com"},
        base_environment | {"SERVICE_BASE_URL": "https://service.example.com/path"},
        base_environment | {"APP_VERSION": "1.2"},
    ):
        result = run([str(build_script)], bad_environment)
        assert result.returncode != 0 and not archive.exists() and not sidecar.exists()
    assert run([str(build_script), "unexpected"], base_environment).returncode != 0

    for failure_mode in (
        "build-failure",
        "identity-missing",
        "profile-failure",
        "signing-failure",
        "notary-rejection",
        "staple-failure",
        "ticket-failure",
        "bundle-verification-failure",
        "gatekeeper-failure",
        "plist-failure",
    ):
        failed = build(failure_mode)
        assert failed.returncode != 0, failure_mode
        assert not archive.exists() and not sidecar.exists(), failure_mode
        assert "SECRET-CANARY" not in failed.stdout + failed.stderr

    binary.unlink()
    absent_binary = build()
    assert absent_binary.returncode != 0 and not archive.exists() and not sidecar.exists()
    binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    binary.chmod(0o700)

    adhoc = build(adhoc=True)
    assert adhoc.returncode == 0, adhoc.stderr
    adhoc_calls = calls(log)
    assert any(call["tool"] == "codesign" and "-" in call["args"] for call in adhoc_calls)
    assert not any(call["tool"] in {"security", "spctl"} for call in adhoc_calls)
    assert not any(call["tool"] == "xcrun" for call in adhoc_calls)
    adhoc_verified = run(
        [str(verify_script), str(archive), "--allow-adhoc"], base_environment
    )
    assert adhoc_verified.returncode == 0, adhoc_verified.stderr

    # Verification rejects malformed ZIPs and unexpected top-level payloads.
    archive.write_bytes(b"not a zip")
    sidecar.write_text(
        hashlib.sha256(archive.read_bytes()).hexdigest() + f"  {archive.name}\n",
        encoding="utf-8",
    )
    assert run([str(verify_script), str(archive), "--allow-adhoc"], base_environment).returncode != 0

    remove_artifacts()
    adhoc = build(adhoc=True)
    assert adhoc.returncode == 0
    metadata_root = test_root / "metadata-root"
    subprocess.run(["/usr/bin/ditto", "-x", "-k", str(archive), str(metadata_root)], check=True)
    metadata_plist = metadata_root / "FindMeGamer.app" / "Contents" / "Info.plist"
    with metadata_plist.open("rb") as stream:
        metadata = plistlib.load(stream)
    metadata["CFBundleVersion"] = "9.9.9"
    with metadata_plist.open("wb") as stream:
        plistlib.dump(metadata, stream)
    rearchive(metadata_root / "FindMeGamer.app", archive)
    assert run([str(verify_script), str(archive), "--allow-adhoc"], base_environment).returncode != 0

    remove_artifacts()
    adhoc = build(adhoc=True)
    assert adhoc.returncode == 0
    malformed_root = test_root / "unexpected-root"
    if malformed_root.exists():
        shutil.rmtree(malformed_root)
    subprocess.run(["/usr/bin/ditto", "-x", "-k", str(archive), str(malformed_root)], check=True)
    (malformed_root / "unexpected.txt").write_text("unexpected", encoding="utf-8")
    archive.unlink()
    subprocess.run(
        ["/usr/bin/ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(malformed_root / "FindMeGamer.app"), str(archive)],
        check=True,
    )
    # Append a real extra top-level member after the app archive.
    subprocess.run(["/usr/bin/zip", "-q", str(archive), "unexpected.txt"], cwd=malformed_root, check=True)
    sidecar.write_text(
        hashlib.sha256(archive.read_bytes()).hexdigest() + f"  {archive.name}\n",
        encoding="utf-8",
    )
    assert run([str(verify_script), str(archive), "--allow-adhoc"], base_environment).returncode != 0

    remove_artifacts()
    symlink_target = test_root / "archive-target"
    symlink_target.write_bytes(b"not a release")
    archive.symlink_to(symlink_target)
    sidecar.write_text("0" * 64 + f"  {archive.name}\n", encoding="utf-8")
    assert run([str(verify_script), str(archive), "--allow-adhoc"], base_environment).returncode != 0

    remove_artifacts()
    dmg = release_dir / f"FindMeGamer-{version}.dmg"
    dmg_environment = base_environment | {
        "FMG_HDIUTIL_BIN": str(tool_paths["hdiutil"]),
        "FMG_LIPO_BIN": str(tool_paths["lipo"]),
        "RELEASE_ARCHITECTURES": "universal",
    }
    dmg_environment.pop("SERVICE_BASE_URL")
    dmg_script = root / "script" / "build_dmg.sh"
    result = run(["bash", str(dmg_script)], dmg_environment)
    assert result.returncode == 0, result.stderr
    assert dmg.is_file() and Path(str(dmg) + ".sha256").is_file()
    dmg_contents = test_root / "dmg-contents"
    subprocess.run(["/usr/bin/ditto", "-x", "-k", str(dmg), str(dmg_contents)], check=True)
    assert os.readlink(dmg_contents / "Applications") == "/Applications"
    assert "Open Anyway" in (dmg_contents / "Read Me.txt").read_text()
    with (dmg_contents / "FindMeGamer.app" / "Contents" / "Info.plist").open("rb") as stream:
        dmg_info = plistlib.load(stream)
    assert dmg_info["FMGAPIBaseURL"] == "http://127.0.0.1:8000"
    assert dmg_info["FMGDemoMode"] is False
    assert "NSAllowsArbitraryLoads" not in dmg_info.get("NSAppTransportSecurity", {})
    universal_calls = [call for call in calls(log) if call["tool"] == "swift"][-4:]
    assert all("arm64-apple-macosx14.0" in call["args"] for call in universal_calls[:2])
    assert all("x86_64-apple-macosx14.0" in call["args"] for call in universal_calls[2:])
    assert any(call["tool"] == "lipo" and "-verify_arch" in call["args"] for call in calls(log))
    checked_dmg = run([str(verify_script), str(dmg), "--allow-adhoc"], dmg_environment)
    assert checked_dmg.returncode == 0, checked_dmg.stderr
    digest_before = dmg.read_bytes()
    assert run(["bash", str(dmg_script)], dmg_environment).returncode != 0
    assert dmg.read_bytes() == digest_before
    dmg.unlink()
    Path(str(dmg) + ".sha256").unlink()
    for extra in (
        {"FMG_RELEASE_FAKE_MODE": "dmg-failure"},
        {"SERVICE_BASE_URL": "http://44.233.174.193:8000"},
    ):
        failed = run(["bash", str(dmg_script)], dmg_environment | extra)
        assert failed.returncode != 0 and not dmg.exists(), failed.stderr

    if release_dir.exists() and not any(release_dir.iterdir()):
        release_dir.rmdir()

print("PASS: fake Developer ID/notary and ad hoc release contracts")
PY

echo "PASS: release script contract"
