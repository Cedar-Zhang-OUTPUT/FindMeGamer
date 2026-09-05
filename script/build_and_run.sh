#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-run}"
APP_NAME="FindMeGamer"
DISPLAY_NAME="Find Me Gamer"
BUNDLE_ID="com.findmegamer.desktop"
MIN_SYSTEM_VERSION="14.0"

case "$MODE" in
  run|--demo|--debug|--logs|--telemetry|--verify)
    ;;
  *)
    echo "usage: $0 [run|--demo|--debug|--logs|--telemetry|--verify]" >&2
    exit 2
    ;;
esac

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PACKAGE_DIR="$ROOT_DIR/macos"
APP_BUNDLE="$ROOT_DIR/dist/$APP_NAME.app"
APP_CONTENTS="$APP_BUNDLE/Contents"
APP_MACOS="$APP_CONTENTS/MacOS"
APP_BINARY="$APP_MACOS/$APP_NAME"
INFO_PLIST="$APP_CONTENTS/Info.plist"
API_BASE_URL="${SERVICE_BASE_URL:-http://127.0.0.1:8000}"
DEMO_MODE=false
if [[ "$MODE" == "--demo" ]]; then
  DEMO_MODE=true
fi

xml_escape() {
  printf '%s' "$1" | sed \
    -e 's/&/\&amp;/g' \
    -e 's/</\&lt;/g' \
    -e 's/>/\&gt;/g' \
    -e 's/"/\&quot;/g' \
    -e "s/'/\\&apos;/g"
}

API_BASE_URL_XML="$(xml_escape "$API_BASE_URL")"
APP_ICON="$PACKAGE_DIR/AppIcon/AppIcon.icns"
[[ -s "$APP_ICON" ]] || {
  echo "App icon is missing. Run bash script/build_app_icon.sh first." >&2
  exit 1
}

/usr/bin/pkill -x "$APP_NAME" >/dev/null 2>&1 || true

swift build --package-path "$PACKAGE_DIR"
BUILD_BIN_DIR="$(swift build --package-path "$PACKAGE_DIR" --show-bin-path)"
BUILD_BINARY="$BUILD_BIN_DIR/$APP_NAME"

rm -rf "$APP_BUNDLE"
mkdir -p "$APP_MACOS"
cp "$BUILD_BINARY" "$APP_BINARY"
chmod +x "$APP_BINARY"
mkdir -p "$APP_CONTENTS/Resources"
cp "$PACKAGE_DIR/Sources/FindMeGamer/Resources/studio-orbit-cover.png" "$APP_CONTENTS/Resources/"
cp "$APP_ICON" "$APP_CONTENTS/Resources/AppIcon.icns"

cat >"$INFO_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key>
  <string>$APP_NAME</string>
  <key>CFBundleIdentifier</key>
  <string>$BUNDLE_ID</string>
  <key>CFBundleName</key>
  <string>$DISPLAY_NAME</string>
  <key>CFBundleIconFile</key>
  <string>AppIcon</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>LSMinimumSystemVersion</key>
  <string>$MIN_SYSTEM_VERSION</string>
  <key>NSPrincipalClass</key>
  <string>NSApplication</string>
  <key>FMGAPIBaseURL</key>
  <string>$API_BASE_URL_XML</string>
  <key>FMGDemoMode</key>
  <$DEMO_MODE/>
</dict>
</plist>
PLIST

open_app() {
  /usr/bin/open -n "$APP_BUNDLE"
}

case "$MODE" in
  run|--demo)
    open_app
    ;;
  --debug)
    exec /usr/bin/lldb -- "$APP_BINARY"
    ;;
  --logs)
    open_app
    exec /usr/bin/log stream --info --style compact --predicate "process == \"$APP_NAME\""
    ;;
  --telemetry)
    open_app
    exec /usr/bin/log stream --info --style compact --predicate "subsystem == \"$BUNDLE_ID\""
    ;;
  --verify)
    open_app
    for _ in {1..50}; do
      if /usr/bin/pgrep -x "$APP_NAME" >/dev/null; then
        exit 0
      fi
      sleep 0.1
    done
    echo "$APP_NAME did not launch" >&2
    exit 1
    ;;
esac
