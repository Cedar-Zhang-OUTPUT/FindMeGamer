#!/bin/sh
set -eu
export COPYFILE_DISABLE=1
tag=${1:?Usage: build-release.sh fmg-vX.Y.Z OUTPUT_DIRECTORY}
out=${2:?Provide an output directory}
case "$tag" in fmg-v[0-9]*) ;; *) exit 2;; esac
root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
case "$out" in /*) ;; *) out="$PWD/$out";; esac
mkdir -p "$out"
task_tmp=$(mktemp -d)
trap 'rmdir "$task_tmp" 2>/dev/null || true' EXIT
cd "$root/cli"
for target in darwin_arm64 darwin_amd64 linux_arm64 linux_amd64; do
  os=${target%_*}; arch=${target#*_}
  GOOS=$os GOARCH=$arch CGO_ENABLED=0 "${GO:-go}" build -trimpath -ldflags "-s -w -X main.version=${tag#fmg-v}" -o "$task_tmp/fmg" ./cmd/fmg
  tar --no-xattrs -czf "$out/fmg_$target.tar.gz" -C "$task_tmp" fmg
done
rm "$task_tmp/fmg"
tar --no-xattrs --exclude='__pycache__' --exclude='*.pyc' -czf "$out/fmg-skills.tar.gz" -C "$root/skills" fmg-api fmg-research
cp "$root/cli/scripts/install.py" "$out/install.py"
cd "$out"
if command -v sha256sum >/dev/null 2>&1; then sha256sum fmg_*.tar.gz fmg-skills.tar.gz install.py > SHA256SUMS
else shasum -a 256 fmg_*.tar.gz fmg-skills.tar.gz install.py > SHA256SUMS; fi
printf 'Built local release assets at %s; nothing uploaded.\n' "$out"
