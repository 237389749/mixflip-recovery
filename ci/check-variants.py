#!/usr/bin/env python3
"""The two bixi configurations must differ only where a variant is allowed to.

The inner and cover builds are one phone with one recovery; the only things
that may differ are the panel it draws on, that panel's backlight, the
backlight left dark, the panel's geometry, and the touch controller read.
Everything else -- services, modules, firmware, backup, wipe -- is the same
phone and must stay byte-identical, or one variant will quietly lose a fix
the other has.

Run from the repository root; exits non-zero and prints the drift when the
two files disagree anywhere else.
"""

from __future__ import annotations

import copy
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = {
    "bixi": ROOT / "devices" / "bixi.toml",
    "bixi-cover": ROOT / "devices" / "bixi-cover.toml",
}

# Keys a variant may set differently. Anything not listed here is shared.
VARIANT_KEYS = {
    ("display", "panel"),
    ("display", "backlight"),
    ("display", "backlights_off"),
    ("display", "width"),
    ("display", "height"),
    ("display", "density"),
    ("display", "diagonal"),
    ("display", "corner_radius"),
    ("touch", "device"),
    ("modules", "load"),
}

# What each variant must actually say, so a copy-paste edit that changes the
# panel but forgets the touch controller (or the reverse) is caught too.
EXPECTED = {
    "bixi": {
        "display.panel": "1224x2912",
        "display.backlight": "panel0-backlight",
        "display.backlights_off": ["panel1-backlight"],
        "display.width": 1224,
        "display.height": 2912,
        "display.density": 520,
        "touch.device": "synaptics",
        "modules.load": ["synaptics_tcm2"],
    },
    "bixi-cover": {
        "display.panel": "1208x1392",
        "display.backlight": "panel1-backlight",
        "display.backlights_off": ["panel0-backlight"],
        "display.width": 1208,
        "display.height": 1392,
        "display.density": 440,
        "touch.device": "goodix",
        "modules.load": ["goodix_core"],
    },
}


def load(name: str) -> dict:
    with FILES[name].open("rb") as f:
        return tomllib.load(f)


def without_variant_keys(doc: dict) -> dict:
    stripped = copy.deepcopy(doc)
    for section, key in VARIANT_KEYS:
        stripped.get(section, {}).pop(key, None)
    return stripped


def value(doc: dict, dotted: str, default=None):
    node = doc
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def main() -> int:
    docs = {name: load(name) for name in FILES}
    failed = False

    for name, doc in docs.items():
        codename = doc.get("device", {}).get("codename")
        if codename != "bixi":
            print(f"FAIL {name}: codename is {codename!r}, not 'bixi'; the variant is the file name")
            failed = True

    inner = without_variant_keys(docs["bixi"])
    cover = without_variant_keys(docs["bixi-cover"])
    if inner != cover:
        print("FAIL the two configurations differ outside the variant keys:")
        for section in sorted(set(inner) | set(cover)):
            if inner.get(section) != cover.get(section):
                print(f"  [{section}]")
                print(f"    bixi:       {inner.get(section)!r}")
                print(f"    bixi-cover: {cover.get(section)!r}")
        failed = True

    for name, wanted in EXPECTED.items():
        for dotted, want in wanted.items():
            got = value(docs[name], dotted)
            if got != want:
                print(f"FAIL {name}: {dotted} is {got!r}, expected {want!r}")
                failed = True

    # The panel drawn on must never be listed as one to turn off; the config
    # parser checks this too, but a failure here says which file.
    for name, doc in docs.items():
        display = doc.get("display", {})
        if display.get("backlight") in display.get("backlights_off", []):
            print(f"FAIL {name}: {display['backlight']!r} is both drawn on and turned off")
            failed = True

    if failed:
        return 1

    print("ok  devices/bixi.toml and devices/bixi-cover.toml differ only in:")
    for section, key in sorted(VARIANT_KEYS):
        inner_value = value(docs["bixi"], f"{section}.{key}", "<unset>")
        cover_value = value(docs["bixi-cover"], f"{section}.{key}", "<unset>")
        print(f"    [{section}] {key}: {inner_value!r} vs {cover_value!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
