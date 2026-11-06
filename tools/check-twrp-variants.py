#!/usr/bin/env python3
"""Check that the bixi TWRP tree builds the variant it is told to.

    python tools/check-twrp-variants.py [device tree] [--make <make.exe>]

The tree has one source and two builds: the inner panel (default) and the
cover panel (BIXI_COVER_SCREEN=1). This reads BoardConfig.mk the way make
does — by asking make itself, with a generated probe makefile that includes
the real file and prints the variables that vary — and checks each variant:

  - TW_BRIGHTNESS_PATH points at its own panel's backlight;
  - exactly one of TW_WHITELIST_INPUT / TW_INPUT_BLACKLIST is set, naming
    goodix_ts for the cover build and blacklisting it for the inner one;
  - TARGET_SYSTEM_PROP ends with the variant's panel property file, and that
    file names the matching connector.

It also checks the two panel property files name different connectors and
that system.prop sets none, so no two files can disagree about the panel.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The tree to check: the one checked out beside this repository, or a path
# given on the command line (CI checks out the device tree as `device/`).
DEFAULT_TREE = ROOT / "twrp_device_xiaomi_sm8750_bixi"

VARIABLES = [
    "BIXI_IS_COVER",
    "TW_BRIGHTNESS_PATH",
    "TW_WHITELIST_INPUT",
    "TW_INPUT_BLACKLIST",
    "TARGET_SYSTEM_PROP",
]

EXPECTED = {
    "inner": {
        "BIXI_IS_COVER": "0",
        "TW_BRIGHTNESS_PATH": "/sys/class/backlight/panel0-backlight/brightness",
        "TW_WHITELIST_INPUT": "",
        "TW_INPUT_BLACKLIST": '"goodix_ts"',
        "panel PROP": "panel-inner.prop",
        "connector": "DSI-1",
    },
    "cover": {
        "BIXI_IS_COVER": "1",
        "TW_BRIGHTNESS_PATH": "/sys/class/backlight/panel1-backlight/brightness",
        "TW_WHITELIST_INPUT": '"goodix_ts"',
        "TW_INPUT_BLACKLIST": "",
        "panel PROP": "panel-cover.prop",
        "connector": "DSI-2",
    },
}


def probe(tree: Path, make: str, cover: bool) -> dict[str, str]:
    """What make says the variables are, with BoardConfig.mk as it is.

    The probe makefile has to sit beside the tree: BoardConfig.mk starts with
    DEVICE_PATH := device/xiaomi/bixi and everything else references that
    relative path, so including it from a temporary folder elsewhere makes
    every $(DEVICE_PATH)/... resolve to nothing.
    """
    mk = tree / ".probe.mk"
    lines = ["include BoardConfig.mk"]
    for name in VARIABLES:
        lines.append(f"$(info {name}=$({name}))")
    lines.append("all:")
    # An empty recipe: `true` is not a program on every host.
    lines.append("\t@:")
    mk.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        command = [make, "-f", mk.name]
        if cover:
            command.append("BIXI_COVER_SCREEN=1")
        result = subprocess.run(command, capture_output=True, text=True, cwd=tree)
    finally:
        mk.unlink(missing_ok=True)
    if result.returncode != 0:
        raise SystemExit(f"make failed:\n{result.stdout}\n{result.stderr}")

    found = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            found[key.strip()] = value.strip()
    return found


def read_connector(prop: Path) -> str | None:
    for line in prop.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("twrp.drm.connector="):
            return line.split("=", 1)[1].strip()
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "tree",
        nargs="?",
        default=str(DEFAULT_TREE),
        help="the device tree to check (default: the one beside this repository)",
    )
    parser.add_argument("--make", default=os.environ.get("MAKE", "make"))
    args = parser.parse_args()

    tree = Path(args.tree).resolve()
    if not (tree / "BoardConfig.mk").is_file():
        raise SystemExit(f"{tree} holds no BoardConfig.mk")

    failed = False

    for variant, cover in (("inner", False), ("cover", True)):
        got = probe(tree, args.make, cover)
        want = EXPECTED[variant]
        print(f"{variant}{' (BIXI_COVER_SCREEN=1)' if cover else ''}:")
        for name in VARIABLES:
            have, expect = got.get(name, ""), want.get(name, "")
            if name == "TARGET_SYSTEM_PROP":
                # A list; the variant's own file has to be in it and the
                # other variant's must not be.
                other = "panel-cover.prop" if variant == "inner" else "panel-inner.prop"
                if expect in have and other not in have:
                    print(f"  ok   {name} names {want['panel PROP']} and not {other}")
                else:
                    print(f"FAIL {name} is {have!r}; expected {want['panel PROP']} and no {other}")
                    failed = True
                continue
            if have == expect:
                print(f"  ok   {name}={have or '(unset)'}")
            else:
                print(f"FAIL {name} is {have!r}, expected {expect!r}")
                failed = True

    # The two property files must name different panels, and system.prop none:
    # a property set twice would leave the value to read order.
    inner = read_connector(tree / "panel-inner.prop")
    cover = read_connector(tree / "panel-cover.prop")
    base = read_connector(tree / "system.prop")
    for name, value in (("panel-inner.prop", inner), ("panel-cover.prop", cover)):
        expect = EXPECTED["inner" if "inner" in name else "cover"]["connector"]
        if value == expect:
            print(f"ok   {name} names {value}")
        else:
            print(f"FAIL {name} names {value!r}, expected {expect!r}")
            failed = True
    if inner == cover:
        print(f"FAIL both property files name {inner!r}")
        failed = True
    if base is not None:
        print(f"FAIL system.prop also names {base!r}; only one file may")
        failed = True
    else:
        print("ok   system.prop names no panel, so nothing competes")

    if failed:
        print("FAILED: the tree does not build the variant it is told to")
        return 1
    print("PASS: both variants build from one tree, differing only where they may")
    return 0


if __name__ == "__main__":
    sys.exit(main())
