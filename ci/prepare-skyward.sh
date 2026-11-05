#!/usr/bin/env bash
# Put the three skyward patches on a clean checkout and install the two bixi
# configurations. Linux or macOS: the preview and the packer only build there.
#
#   ci/prepare-skyward.sh [directory]
#
# The default is .work/skyward. An existing checkout is reset to the pinned
# commit, so local changes in it are discarded; that is the point of a
# preparation script.
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
sky=${1:-${SKYWARD_DIR:-$root/.work/skyward}}

read -r url ref < <(python3 - "$root/manifest.toml" <<'PY'
import sys, tomllib
sky = tomllib.load(open(sys.argv[1], "rb"))["skyward"]
print(sky["url"], sky["ref"])
PY
)

if [ ! -d "$sky/.git" ]; then
    git clone "$url" "$sky"
fi
git -C "$sky" fetch --quiet origin "$ref"
git -C "$sky" checkout --quiet --force "$ref"
git -C "$sky" clean -fdq

for patch in "$root"/patches/000[3-6]-*.patch; do
    git -C "$sky" apply "$patch"
    echo "applied $(basename "$patch")"
done

cp "$root"/devices/*.toml "$sky/devices/"
echo "prepared $sky at $ref"
