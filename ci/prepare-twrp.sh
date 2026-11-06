#!/usr/bin/env bash
# Put the TWRP patches on clean checkouts of their two upstreams and, where
# libdrm's headers are installed, compile-check the patched DRM backend.
#
#   ci/prepare-twrp.sh [work directory]
#
# The default work directory is .work/twrp. The recovery checkout is shallow:
# only the pinned commit is fetched.
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
work=${1:-$root/.work/twrp}
mkdir -p "$work"

read -r recovery_url recovery_ref device_url device_ref < <(python3 - "$root/manifest.toml" <<'PY'
import sys, tomllib
m = tomllib.load(open(sys.argv[1], "rb"))
print(m["twrp_recovery"]["url"], m["twrp_recovery"]["ref"],
      m["twrp_device"]["url"], m["twrp_device"]["ref"])
PY
)

if [ ! -d "$work/recovery/.git" ]; then
    git init --quiet "$work/recovery"
fi
git -C "$work/recovery" fetch --quiet --depth 1 "$recovery_url" "$recovery_ref"
git -C "$work/recovery" checkout --quiet FETCH_HEAD
git -C "$work/recovery" apply "$root/patches/0001-twrpminui-name-the-panel-on-foldables.patch"
echo "applied 0001"

if [ ! -d "$work/device/.git" ]; then
    git init --quiet "$work/device"
fi
git -C "$work/device" fetch --quiet --depth 1 "$device_url" "$device_ref"
git -C "$work/device" checkout --quiet FETCH_HEAD
git -C "$work/device" apply "$root/patches/0002-bixi-let-the-recovery-choose-its-panel.patch"
echo "applied 0002"
git -C "$work/device" apply "$root/patches/0002b-bixi-cover-panel-variant.patch"
echo "applied 0002b"

if command -v g++ >/dev/null && [ -f /usr/include/libdrm/xf86drmMode.h ]; then
    g++ -std=gnu++17 -fsyntax-only \
        -D__unused=__attribute__\(\(unused\)\) \
        -I "$work/recovery/twrpminui/include" \
        -I "$work/recovery/twrpminui" \
        -I "$work/recovery/libpixelflinger/include" \
        -I /usr/include/libdrm \
        -I "$root/ci/stubs" \
        "$work/recovery/twrpminui/graphics_drm.cpp"
    echo "compiled graphics_drm.cpp (syntax only)"
else
    echo "skipped the syntax check: g++ or libdrm-dev is missing" >&2
fi
