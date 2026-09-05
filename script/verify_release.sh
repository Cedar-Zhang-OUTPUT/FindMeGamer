#!/usr/bin/env bash
set -euo pipefail
if [[ "$-" == *x* ]]; then
  set +x
fi

fail() {
  echo "release-verify: $*" >&2
  exit 1
}

ipv4_is_public() {
  local address="$1"
  local first second third fourth octet
  [[ "$address" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || return 1
  IFS='.' read -r first second third fourth <<<"$address"
  for octet in "$first" "$second" "$third" "$fourth"; do
    [[ "$octet" =~ ^(0|[1-9][0-9]{0,2})$ ]] || return 1
    (( 10#$octet <= 255 )) || return 1
  done
  first=$((10#$first))
  second=$((10#$second))
  [[ "$first" -ne 0 && "$first" -ne 10 && "$first" -ne 127 && "$first" -lt 224 ]] || return 1
  [[ "$first" -ne 169 || "$second" -ne 254 ]] || return 1
  [[ "$first" -ne 172 || "$second" -lt 16 || "$second" -gt 31 ]] || return 1
  [[ "$first" -ne 192 || "$second" -ne 168 ]] || return 1
  [[ "$first" -ne 100 || "$second" -lt 64 || "$second" -gt 127 ]] || return 1
  [[ "$first" -ne 198 || "$second" -lt 18 || "$second" -gt 19 ]] || return 1
}

validate_https_origin() {
  local value="$1"
  local allow_example_invalid="$2"
  local host port host_lower label port_value
  local -a labels
  [[ ! "$value" =~ [[:cntrl:]] ]] || return 1
  [[ "$value" =~ ^https://([A-Za-z0-9.-]+)(:([0-9]{1,5}))?$ ]] || return 1
  host="${BASH_REMATCH[1]}"
  port="${BASH_REMATCH[3]}"
  [[ ${#host} -le 253 && "$host" != .* && "$host" != *. && "$host" != *..* ]] || return 1
  IFS='.' read -r -a labels <<<"$host"
  for label in "${labels[@]}"; do
    [[ ${#label} -ge 1 && ${#label} -le 63 ]] || return 1
    [[ "$label" =~ ^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?$ ]] || return 1
  done
  if [[ "$host" =~ ^[0-9.]+$ ]]; then
    ipv4_is_public "$host" || return 1
  fi
  if [[ -n "$port" ]]; then
    port_value=$((10#$port))
    [[ "$port_value" -ge 1 && "$port_value" -le 65535 ]] || return 1
  fi
  host_lower="$(printf '%s' "$host" | tr '[:upper:]' '[:lower:]')"
  case "$host_lower" in
    localhost | *.localhost)
      return 1
      ;;
    *.invalid)
      [[ "$allow_example_invalid" == "yes" && "$host_lower" == "example.invalid" ]] || return 1
      ;;
  esac
}

[[ $# -eq 1 || $# -eq 2 ]] || fail "usage: $0 release/FindMeGamer-<x.y.z>.<zip|dmg> [--allow-adhoc]"
archive="$1"
allow_adhoc="no"
if [[ $# -eq 2 ]]; then
  [[ "$2" == "--allow-adhoc" ]] || fail "unknown verification option"
  allow_adhoc="yes"
fi
[[ -f "$archive" && ! -L "$archive" ]] || fail "release archive must be a regular non-symlink file"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd "$script_dir/.." && pwd)"
release_dir="${repository_root}/release"
archive_parent="$(cd "$(dirname "$archive")" && pwd -P)" || fail "release archive parent is invalid"
archive_name="$(basename "$archive")"
[[ "$archive_parent" == "$release_dir" ]] || fail "release archive must be inside the repository release directory"
[[ "$archive_name" =~ ^FindMeGamer-((0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*))\.(zip|dmg)$ ]] ||
  fail "release archive name is invalid"
archive_version="${BASH_REMATCH[1]}"
archive_format="${BASH_REMATCH[5]}"
sidecar="${archive}.sha256"
[[ -f "$sidecar" && ! -L "$sidecar" ]] || fail "release checksum sidecar must be a regular non-symlink file"

test_mode="${FMG_RELEASE_TEST_MODE:-0}"
[[ "$test_mode" == "0" || "$test_mode" == "1" ]] || fail "release test mode must be 0 or 1"
if [[ "$test_mode" == "1" ]]; then
  codesign_bin="${FMG_CODESIGN_BIN:?FMG_CODESIGN_BIN is required in test mode}"
  xcrun_bin="${FMG_XCRUN_BIN:?FMG_XCRUN_BIN is required in test mode}"
  spctl_bin="${FMG_SPCTL_BIN:?FMG_SPCTL_BIN is required in test mode}"
  plutil_bin="${FMG_PLUTIL_BIN:?FMG_PLUTIL_BIN is required in test mode}"
  ditto_bin="${FMG_DITTO_BIN:?FMG_DITTO_BIN is required in test mode}"
  shasum_bin="${FMG_SHASUM_BIN:?FMG_SHASUM_BIN is required in test mode}"
  hdiutil_bin="${FMG_HDIUTIL_BIN:-/usr/bin/hdiutil}"
else
  [[ -z "${FMG_CODESIGN_BIN:-}${FMG_XCRUN_BIN:-}${FMG_SPCTL_BIN:-}${FMG_PLUTIL_BIN:-}${FMG_DITTO_BIN:-}${FMG_SHASUM_BIN:-}${FMG_HDIUTIL_BIN:-}" ]] ||
    fail "command overrides are allowed only in release test mode"
  codesign_bin="/usr/bin/codesign"
  xcrun_bin="/usr/bin/xcrun"
  spctl_bin="/usr/sbin/spctl"
  plutil_bin="/usr/bin/plutil"
  ditto_bin="/usr/bin/ditto"
  shasum_bin="/usr/bin/shasum"
  hdiutil_bin="/usr/bin/hdiutil"
fi

[[ "$(wc -l <"$sidecar" | tr -d ' ')" == "1" ]] || fail "release checksum sidecar format is invalid"
IFS=' ' read -r expected_hash expected_name extra <"$sidecar" || fail "release checksum sidecar is unreadable"
[[ "$expected_hash" =~ ^[0-9a-f]{64}$ && "$expected_name" == "$archive_name" && -z "$extra" ]] ||
  fail "release checksum sidecar format is invalid"
actual_hash="$("$shasum_bin" -a 256 "$archive" 2>/dev/null | awk '{print $1}')" || fail "release checksum could not be computed"
[[ "$actual_hash" == "$expected_hash" ]] || fail "release checksum mismatch"
echo "PASS checksum"

umask 077
temporary_base="${TMPDIR:-/tmp}"
verification_dir="$(mktemp -d "${temporary_base%/}/fmg-release-verify.XXXXXX")" ||
  fail "private verification directory could not be created"
[[ -d "$verification_dir" && ! -L "$verification_dir" && "$verification_dir" == "${temporary_base%/}/fmg-release-verify."* ]] ||
  fail "private verification path is invalid"
mounted=0
cleanup() {
  cleanup_status=$?
  trap - EXIT INT TERM
  if [[ "$mounted" == "1" ]]; then
    "$hdiutil_bin" detach "${verification_dir}/mounted" >/dev/null || cleanup_status=1
  fi
  if [[ -d "$verification_dir" && ! -L "$verification_dir" && "$verification_dir" == "${temporary_base%/}/fmg-release-verify."* ]]; then
    rm -rf -- "$verification_dir"
  fi
  exit "$cleanup_status"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

payload_dir="$verification_dir"
if [[ "$archive_format" == "dmg" ]]; then
  "$hdiutil_bin" verify "$archive" >/dev/null || fail "disk image verification failed"
  payload_dir="${verification_dir}/mounted"
  mkdir "$payload_dir"
  "$hdiutil_bin" attach "$archive" -readonly -nobrowse -mountpoint "$payload_dir" >/dev/null || fail "disk image mount failed"
  mounted=1
  [[ -L "${payload_dir}/Applications" && "$(readlink "${payload_dir}/Applications")" == "/Applications" &&
    -f "${payload_dir}/Read Me.txt" ]] || fail "disk image installation instructions are missing"
else
  "$ditto_bin" -x -k "$archive" "$verification_dir" >/dev/null 2>&1 || fail "release archive extraction failed"
fi
shopt -s nullglob dotglob
top_level=("$payload_dir"/*)
shopt -u nullglob dotglob
if [[ "$archive_format" == "zip" ]]; then
  [[ ${#top_level[@]} -eq 1 && "${top_level[0]}" == "${payload_dir}/FindMeGamer.app" ]] || fail "release archive top-level shape is invalid"
fi
app_bundle="${payload_dir}/FindMeGamer.app"
[[ -d "$app_bundle" && ! -L "$app_bundle" ]] || fail "release app bundle is missing"
app_binary="${app_bundle}/Contents/MacOS/FindMeGamer"
info_plist="${app_bundle}/Contents/Info.plist"
[[ -f "$app_binary" && ! -L "$app_binary" && -x "$app_binary" ]] || fail "release executable is missing"
shopt -s nullglob dotglob
macos_payload=("${app_bundle}/Contents/MacOS"/*)
shopt -u nullglob dotglob
[[ ${#macos_payload[@]} -eq 1 && "${macos_payload[0]}" == "$app_binary" ]] ||
  fail "release executable payload is invalid"
[[ -f "$info_plist" && ! -L "$info_plist" ]] || fail "release plist is missing"
"$plutil_bin" -lint "$info_plist" >/dev/null 2>&1 || fail "release plist is invalid"

plist_value() {
  "$plutil_bin" -extract "$1" raw -o - "$info_plist" 2>/dev/null
}
api_base_url="$(plist_value FMGAPIBaseURL)" || fail "release API base URL is missing"
if [[ "$allow_adhoc" == "yes" ]]; then
  if [[ "$api_base_url" != "http://127.0.0.1:8000" && "$api_base_url" != "http://localhost:8000" ]]; then
    validate_https_origin "$api_base_url" yes || fail "release API base URL is invalid"
  fi
else
  validate_https_origin "$api_base_url" no || fail "release API base URL is invalid"
fi
[[ "$(plist_value CFBundleIdentifier)" == "com.findmegamer.desktop" &&
  "$(plist_value CFBundleDisplayName)" == "Find Me Gamer" &&
  "$(plist_value CFBundleName)" == "Find Me Gamer" &&
  "$(plist_value CFBundleIconFile)" == "AppIcon" &&
  "$(plist_value CFBundleExecutable)" == "FindMeGamer" &&
  "$(plist_value CFBundlePackageType)" == "APPL" &&
  "$(plist_value LSMinimumSystemVersion)" == "14.0" &&
  "$(plist_value NSPrincipalClass)" == "NSApplication" &&
  "$(plist_value CFBundleShortVersionString)" == "$archive_version" &&
  "$(plist_value CFBundleVersion)" == "$archive_version" ]] || fail "release bundle metadata is invalid"

app_icon="${app_bundle}/Contents/Resources/AppIcon.icns"
[[ -s "$app_icon" && ! -L "$app_icon" ]] || fail "release App icon is missing"
[[ "$(/usr/bin/head -c 4 "$app_icon")" == "icns" ]] || fail "release App icon is invalid"

"$codesign_bin" --verify --deep --strict "$app_bundle" >/dev/null 2>&1 || fail "release signature verification failed"
if [[ "$allow_adhoc" == "yes" ]]; then
  echo "PASS ad hoc release verification (trust and notarization acceptance skipped)"
else
  "$spctl_bin" -a -vv --type execute "$app_bundle" >/dev/null 2>&1 || fail "Gatekeeper assessment failed"
  "$xcrun_bin" stapler validate "$app_bundle" >/dev/null 2>&1 || fail "stapled ticket validation failed"
  echo "PASS Developer ID, Gatekeeper, and stapled ticket verification"
fi
printf 'Verified: %s\n' "$archive"
