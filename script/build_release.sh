#!/usr/bin/env bash
set -euo pipefail
if [[ "$-" == *x* ]]; then
  set +x
fi

fail() {
  echo "release-build: $*" >&2
  exit 1
}

xml_escape() {
  printf '%s' "$1" | sed \
    -e 's/&/\&amp;/g' \
    -e 's/</\&lt;/g' \
    -e 's/>/\&gt;/g' \
    -e 's/"/\&quot;/g' \
    -e "s/'/\\&apos;/g"
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

[[ $# -eq 0 ]] || fail "usage: SERVICE_BASE_URL=<https-origin> APP_VERSION=<x.y.z> $0"

adhoc_release="${ADHOC_RELEASE:-0}"
release_format="${RELEASE_FORMAT:-zip}"
release_architectures="${RELEASE_ARCHITECTURES:-native}"
test_mode="${FMG_RELEASE_TEST_MODE:-0}"
[[ "$adhoc_release" == "0" || "$adhoc_release" == "1" ]] || fail "ADHOC_RELEASE must be 0 or 1"
[[ "$release_format" == "zip" || "$release_format" == "dmg" ]] || fail "RELEASE_FORMAT must be zip or dmg"
[[ "$release_format" != "dmg" || "$adhoc_release" == "1" ]] || fail "DMG currently supports internal ad hoc releases"
[[ "$release_architectures" == "native" || "$release_architectures" == "universal" ]] || fail "RELEASE_ARCHITECTURES must be native or universal"
[[ "$test_mode" == "0" || "$test_mode" == "1" ]] || fail "release test mode must be 0 or 1"

service_base_url="${SERVICE_BASE_URL:-}"
app_version="${APP_VERSION:-}"
[[ "$app_version" =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ && ${#app_version} -le 64 ]] ||
  fail "APP_VERSION must contain exactly three decimal components"
if [[ "$adhoc_release" == "1" ]]; then
  if [[ "$service_base_url" != "http://127.0.0.1:8000" && "$service_base_url" != "http://localhost:8000" ]]; then
    validate_https_origin "$service_base_url" yes || fail "SERVICE_BASE_URL must be one safe HTTPS origin or local development port 8000"
  fi
else
  validate_https_origin "$service_base_url" no || fail "SERVICE_BASE_URL must be one safe HTTPS origin"
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd "$script_dir/.." && pwd)"
package_dir="${repository_root}/macos"
entitlements="${package_dir}/FindMeGamer.entitlements"
app_icon="${package_dir}/AppIcon/AppIcon.icns"
release_dir="${repository_root}/release"
archive_name="FindMeGamer-${app_version}.${release_format}"
final_archive="${release_dir}/${archive_name}"
final_sidecar="${final_archive}.sha256"
[[ -f "$entitlements" && ! -L "$entitlements" ]] || fail "release entitlements are missing"
[[ -s "$app_icon" && ! -L "$app_icon" ]] || fail "App icon is missing; run bash script/build_app_icon.sh"
[[ ! -e "$final_archive" && ! -L "$final_archive" && ! -e "$final_sidecar" && ! -L "$final_sidecar" ]] ||
  fail "final release artifact already exists"

if [[ "$test_mode" == "1" ]]; then
  swift_bin="${FMG_SWIFT_BIN:?FMG_SWIFT_BIN is required in test mode}"
  security_bin="${FMG_SECURITY_BIN:?FMG_SECURITY_BIN is required in test mode}"
  codesign_bin="${FMG_CODESIGN_BIN:?FMG_CODESIGN_BIN is required in test mode}"
  xcrun_bin="${FMG_XCRUN_BIN:?FMG_XCRUN_BIN is required in test mode}"
  spctl_bin="${FMG_SPCTL_BIN:?FMG_SPCTL_BIN is required in test mode}"
  plutil_bin="${FMG_PLUTIL_BIN:?FMG_PLUTIL_BIN is required in test mode}"
  ditto_bin="${FMG_DITTO_BIN:?FMG_DITTO_BIN is required in test mode}"
  shasum_bin="${FMG_SHASUM_BIN:?FMG_SHASUM_BIN is required in test mode}"
  hdiutil_bin="${FMG_HDIUTIL_BIN:-/usr/bin/hdiutil}"
  lipo_bin="${FMG_LIPO_BIN:-/usr/bin/lipo}"
else
  [[ -z "${FMG_SWIFT_BIN:-}${FMG_SECURITY_BIN:-}${FMG_CODESIGN_BIN:-}${FMG_XCRUN_BIN:-}${FMG_SPCTL_BIN:-}${FMG_PLUTIL_BIN:-}${FMG_DITTO_BIN:-}${FMG_SHASUM_BIN:-}${FMG_HDIUTIL_BIN:-}${FMG_LIPO_BIN:-}" ]] ||
    fail "command overrides are allowed only in release test mode"
  swift_bin="$(command -v swift)"
  security_bin="/usr/bin/security"
  codesign_bin="/usr/bin/codesign"
  xcrun_bin="/usr/bin/xcrun"
  spctl_bin="/usr/sbin/spctl"
  plutil_bin="/usr/bin/plutil"
  ditto_bin="/usr/bin/ditto"
  shasum_bin="/usr/bin/shasum"
  hdiutil_bin="/usr/bin/hdiutil"
  lipo_bin="/usr/bin/lipo"
fi

developer_identity=""
notary_profile=""
if [[ "$adhoc_release" == "0" ]]; then
  developer_identity="${DEVELOPER_ID_APPLICATION:-}"
  notary_profile="${NOTARY_PROFILE:-}"
  [[ -n "$developer_identity" && ${#developer_identity} -le 256 && ! "$developer_identity" =~ [[:cntrl:]] ]] ||
    fail "DEVELOPER_ID_APPLICATION is required"
  [[ -n "$notary_profile" && ${#notary_profile} -le 128 && ! "$notary_profile" =~ [[:cntrl:]] ]] ||
    fail "NOTARY_PROFILE is invalid"
  identity_listing="$("$security_bin" find-identity -v -p codesigning 2>/dev/null)" ||
    fail "Developer ID identity preflight failed"
  printf '%s\n' "$identity_listing" | grep -Fq -- "\"${developer_identity}\"" ||
    fail "the exact Developer ID Application identity is unavailable"
  unset identity_listing
  "$xcrun_bin" notarytool history --keychain-profile "$notary_profile" --output-format json \
    >/dev/null 2>&1 || fail "notary Keychain profile preflight failed"
  echo "PASS Developer ID and notary profile preflight"
fi

echo "Building release binary"
swift_options=()
if [[ -n "${SWIFT_SCRATCH_PATH:-}" ]]; then
  swift_options+=(--scratch-path "$SWIFT_SCRATCH_PATH")
fi
architectures=(native)
if [[ "$release_architectures" == "universal" ]]; then
  # Multi-architecture SwiftPM selects Xcode's build system, which cannot resolve
  # this package's OpenAPI plugin. Compile native SwiftPM slices, then use lipo.
  architectures=(arm64 x86_64)
fi
build_binaries=()
for architecture in "${architectures[@]}"; do
  architecture_options=()
  if [[ "$architecture" != "native" ]]; then
    architecture_options=(--triple "${architecture}-apple-macosx14.0")
  fi
  "$swift_bin" build --package-path "$package_dir" -c release ${swift_options[@]+"${swift_options[@]}"} \
    ${architecture_options[@]+"${architecture_options[@]}"} || fail "Swift release build failed"
  build_bin_dir="$("$swift_bin" build --package-path "$package_dir" -c release ${swift_options[@]+"${swift_options[@]}"} \
    ${architecture_options[@]+"${architecture_options[@]}"} --show-bin-path 2>/dev/null)" || fail "Swift release binary path lookup failed"
  [[ "$build_bin_dir" == /* && "$build_bin_dir" != *$'\n'* ]] || fail "Swift release binary path is invalid"
  build_binary="${build_bin_dir}/FindMeGamer"
  [[ -f "$build_binary" && ! -L "$build_binary" && -x "$build_binary" ]] || fail "Swift release executable is missing"
  build_binaries+=("$build_binary")
done

umask 077
temporary_base="${TMPDIR:-/tmp}"
staging_dir="$(mktemp -d "${temporary_base%/}/fmg-release.XXXXXX")" || fail "private release staging could not be created"
[[ -d "$staging_dir" && ! -L "$staging_dir" && "$staging_dir" == "${temporary_base%/}/fmg-release."* ]] ||
  fail "private release staging path is invalid"
publish_dir=""
published_archive=0
published_sidecar=0
cleanup() {
  cleanup_status=$?
  trap - EXIT INT TERM
  if [[ "$cleanup_status" -ne 0 ]]; then
    if [[ "$published_sidecar" == "1" && -f "$final_sidecar" && ! -L "$final_sidecar" ]]; then
      rm -f -- "$final_sidecar"
    fi
    if [[ "$published_archive" == "1" && -f "$final_archive" && ! -L "$final_archive" ]]; then
      rm -f -- "$final_archive"
    fi
  fi
  if [[ -n "$publish_dir" && -d "$publish_dir" && ! -L "$publish_dir" && "$publish_dir" == "${release_dir}/.FindMeGamer-${app_version}.publish."* ]]; then
    rm -rf -- "$publish_dir"
  fi
  if [[ -d "$staging_dir" && ! -L "$staging_dir" && "$staging_dir" == "${temporary_base%/}/fmg-release."* ]]; then
    rm -rf -- "$staging_dir"
  fi
  exit "$cleanup_status"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

app_bundle="${staging_dir}/FindMeGamer.app"
app_contents="${app_bundle}/Contents"
app_macos="${app_contents}/MacOS"
app_binary="${app_macos}/FindMeGamer"
info_plist="${app_contents}/Info.plist"
mkdir -p "$app_macos"
if [[ "$release_architectures" == "universal" ]]; then
  "$lipo_bin" -create "${build_binaries[@]}" -output "$app_binary" || fail "universal binary assembly failed"
  "$lipo_bin" "$app_binary" -verify_arch arm64 x86_64 || fail "universal binary slices are missing"
else
  cp "${build_binaries[0]}" "$app_binary"
fi
chmod 755 "$app_binary"
mkdir -p "$app_contents/Resources"
cp "$package_dir/Sources/FindMeGamer/Resources/studio-orbit-cover.png" "$app_contents/Resources/" ||
  fail "studio artwork packaging failed"
chmod 755 "$app_contents/Resources"
chmod 644 "$app_contents/Resources/studio-orbit-cover.png"
cp "$app_icon" "$app_contents/Resources/AppIcon.icns" || fail "App icon packaging failed"
chmod 644 "$app_contents/Resources/AppIcon.icns"
service_base_url_xml="$(xml_escape "$service_base_url")"
cat >"$info_plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDisplayName</key>
  <string>Find Me Gamer</string>
  <key>CFBundleExecutable</key>
  <string>FindMeGamer</string>
  <key>CFBundleIdentifier</key>
  <string>com.findmegamer.desktop</string>
  <key>CFBundleName</key>
  <string>Find Me Gamer</string>
  <key>CFBundleIconFile</key>
  <string>AppIcon</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>${app_version}</string>
  <key>CFBundleVersion</key>
  <string>${app_version}</string>
  <key>FMGAPIBaseURL</key>
  <string>${service_base_url_xml}</string>
  <key>FMGDemoMode</key>
  <false/>
  <key>LSMinimumSystemVersion</key>
  <string>14.0</string>
  <key>NSPrincipalClass</key>
  <string>NSApplication</string>
</dict>
</plist>
PLIST
chmod 755 "$app_bundle" "$app_contents" "$app_macos"
chmod 644 "$info_plist"
"$plutil_bin" -lint "$info_plist" >/dev/null 2>&1 || fail "staged bundle plist is invalid"

plist_value() {
  "$plutil_bin" -extract "$1" raw -o - "$info_plist" 2>/dev/null
}
[[ "$(plist_value CFBundleIdentifier)" == "com.findmegamer.desktop" &&
  "$(plist_value CFBundleDisplayName)" == "Find Me Gamer" &&
  "$(plist_value CFBundleIconFile)" == "AppIcon" &&
  "$(plist_value CFBundleExecutable)" == "FindMeGamer" &&
  "$(plist_value CFBundlePackageType)" == "APPL" &&
  "$(plist_value LSMinimumSystemVersion)" == "14.0" &&
  "$(plist_value NSPrincipalClass)" == "NSApplication" &&
  "$(plist_value CFBundleShortVersionString)" == "$app_version" &&
  "$(plist_value CFBundleVersion)" == "$app_version" &&
  "$(plist_value FMGAPIBaseURL)" == "$service_base_url" ]] || fail "staged bundle metadata is invalid"

# SwiftPM leaves back-deployment runtime libraries in the developer toolchain.
# Package the libraries Apple identifies so macOS 14 Macs do not need Xcode.
frameworks_dir="${app_contents}/Frameworks"
mkdir -p "$frameworks_dir"
chmod 755 "$frameworks_dir"
runtime_identity="${developer_identity:--}"
"$xcrun_bin" swift-stdlib-tool --copy --scan-executable "$app_binary" --platform macosx \
  --destination "$frameworks_dir" --sign "$runtime_identity" || fail "Swift runtime library packaging failed"
"$xcrun_bin" install_name_tool -add_rpath '@executable_path/../Frameworks' "$app_binary" ||
  fail "bundled Swift runtime search path could not be configured"

if [[ "$adhoc_release" == "1" ]]; then
  "$codesign_bin" --force --sign - --timestamp=none --entitlements "$entitlements" "$app_binary" \
    >/dev/null 2>&1 || fail "ad hoc executable signing failed"
  "$codesign_bin" --force --sign - --timestamp=none --entitlements "$entitlements" "$app_bundle" \
    >/dev/null 2>&1 || fail "ad hoc bundle signing failed"
  "$codesign_bin" --verify --deep --strict "$app_bundle" >/dev/null 2>&1 ||
    fail "ad hoc bundle verification failed"
  echo "PASS ad hoc bundle signature"
else
  "$codesign_bin" --force --sign "$developer_identity" --options runtime --timestamp \
    --entitlements "$entitlements" "$app_binary" >/dev/null 2>&1 || fail "Developer ID executable signing failed"
  "$codesign_bin" --force --sign "$developer_identity" --options runtime --timestamp \
    --entitlements "$entitlements" "$app_bundle" >/dev/null 2>&1 || fail "Developer ID bundle signing failed"
  notary_archive="${staging_dir}/FindMeGamer-notary.zip"
  notary_result="${staging_dir}/notary-result.json"
  "$ditto_bin" -c -k --keepParent "$app_bundle" "$notary_archive" >/dev/null 2>&1 ||
    fail "temporary notarization archive failed"
  "$xcrun_bin" notarytool submit "$notary_archive" --wait --keychain-profile "$notary_profile" \
    --output-format json >"$notary_result" 2>/dev/null || fail "notarization submission failed"
  jq -e '.status == "Accepted"' "$notary_result" >/dev/null 2>&1 || fail "notarization was not accepted"
  "$xcrun_bin" stapler staple "$app_bundle" >/dev/null 2>&1 || fail "ticket stapling failed"
  "$xcrun_bin" stapler validate "$app_bundle" >/dev/null 2>&1 || fail "stapled ticket validation failed"
  "$codesign_bin" --verify --deep --strict "$app_bundle" >/dev/null 2>&1 ||
    fail "strict Developer ID verification failed"
  "$spctl_bin" -a -vv --type execute "$app_bundle" >/dev/null 2>&1 ||
    fail "Gatekeeper assessment failed"
  echo "PASS notarization, ticket, signature, and Gatekeeper"
fi

if [[ -e "$release_dir" || -L "$release_dir" ]]; then
  [[ -d "$release_dir" && ! -L "$release_dir" ]] || fail "release output directory is invalid"
else
  mkdir -m 755 "$release_dir"
fi
publish_dir="$(mktemp -d "${release_dir}/.FindMeGamer-${app_version}.publish.XXXXXX")" ||
  fail "private publish staging could not be created"
[[ -d "$publish_dir" && ! -L "$publish_dir" && "$publish_dir" == "${release_dir}/.FindMeGamer-${app_version}.publish."* ]] ||
  fail "private publish staging path is invalid"
temporary_final_archive="${publish_dir}/${archive_name}"
temporary_final_sidecar="${temporary_final_archive}.sha256"
if [[ "$release_format" == "dmg" ]]; then
  ln -s /Applications "${staging_dir}/Applications"
  cat >"${staging_dir}/Read Me.txt" <<README
Find Me Gamer ${app_version} - Internal Preview

Requires macOS 14 Sonoma or later.

1. Drag FindMeGamer.app to Applications.
2. Eject this disk image and open Find Me Gamer from Applications.
3. If macOS blocks the first launch, open System Settings > Privacy & Security,
   choose Open Anyway for Find Me Gamer, and confirm Open. This internal build
   uses an ad hoc signature and is not notarized by Apple. Only use a build from
   your trusted team. Do not disable Gatekeeper globally.

This is the real-service client, not sample-data mode.
Service address: ${service_base_url}
For the local address, the backend must be running on the same Mac.
Enter the Workspace Access Key supplied with that backend. Without a running
backend, analysis, matching, and outreach will not work.
Provider and SMTP credentials belong in Settings; none are included in this app.

Source and releases: https://github.com/Cedar-Zhang-OUTPUT/FindMeGamer
README
  chmod 644 "${staging_dir}/Read Me.txt"
  "$hdiutil_bin" create -volname "Find Me Gamer ${app_version}" -srcfolder "$staging_dir" \
    -format UDZO -fs HFS+ "$temporary_final_archive" >/dev/null || fail "disk image creation failed"
  "$hdiutil_bin" verify "$temporary_final_archive" >/dev/null || fail "disk image verification failed"
else
  "$ditto_bin" -c -k --keepParent "$app_bundle" "$temporary_final_archive" >/dev/null 2>&1 ||
    fail "final post-staple archive failed"
fi
archive_hash="$("$shasum_bin" -a 256 "$temporary_final_archive" 2>/dev/null | awk '{print $1}')" ||
  fail "release checksum failed"
[[ "$archive_hash" =~ ^[0-9a-f]{64}$ ]] || fail "release checksum is invalid"
printf '%s  %s\n' "$archive_hash" "$archive_name" >"$temporary_final_sidecar"
[[ ! -e "$final_archive" && ! -L "$final_archive" && ! -e "$final_sidecar" && ! -L "$final_sidecar" ]] ||
  fail "final release artifact appeared during packaging"
mv "$temporary_final_archive" "$final_archive"
published_archive=1
mv "$temporary_final_sidecar" "$final_sidecar"
published_sidecar=1
echo "PASS release artifact published"
printf 'Artifact: %s\nChecksum: %s\n' "$final_archive" "$final_sidecar"
