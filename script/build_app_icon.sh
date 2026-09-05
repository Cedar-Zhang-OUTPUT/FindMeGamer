#!/usr/bin/env bash
set -euo pipefail

# Repackage the existing logo without redrawing or cropping its artwork.
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd "$script_dir/.." && pwd)"
source_png="$repository_root/macos/Design/FindMeGamer-Logo-Concept.png"
output_dir="$repository_root/macos/AppIcon"
output_icon="$output_dir/AppIcon.icns"

[[ -f "$source_png" ]] || { echo "App icon source is missing" >&2; exit 1; }
dimensions="$(/usr/bin/sips -g pixelWidth -g pixelHeight "$source_png")"
width="$(printf '%s\n' "$dimensions" | awk '/pixelWidth:/ {print $2}')"
height="$(printf '%s\n' "$dimensions" | awk '/pixelHeight:/ {print $2}')"
[[ "$width" =~ ^[0-9]+$ && "$height" == "$width" && "$width" -ge 1024 ]] || {
  echo "App icon source must be square and at least 1024 pixels" >&2
  exit 1
}

icon_work_dir="$(mktemp -d "${TMPDIR:-/tmp}/fmg-app-icon.XXXXXX")"
cleanup() {
  if [[ -d "$icon_work_dir" && ! -L "$icon_work_dir" && "${icon_work_dir##*/}" == fmg-app-icon.* ]]; then
    rm -rf -- "$icon_work_dir"
  fi
}
trap cleanup EXIT
iconset="$icon_work_dir/AppIcon.iconset"
mkdir -p "$iconset" "$output_dir"

for points in 16 32 128 256 512; do
  /usr/bin/sips -z "$points" "$points" "$source_png" \
    --out "$iconset/icon_${points}x${points}.png" >/dev/null
  pixels=$((points * 2))
  /usr/bin/sips -z "$pixels" "$pixels" "$source_png" \
    --out "$iconset/icon_${points}x${points}@2x.png" >/dev/null
done
/usr/bin/iconutil -c icns "$iconset" -o "$output_icon"
chmod 644 "$output_icon"
echo "Generated $output_icon"
