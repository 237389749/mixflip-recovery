#!/usr/bin/env python3
"""Check that a packed recovery carries its own variant's configuration.

    python tools/check-image-variant.py <recovery.img> --pack <skyward-pack> --config devices/bixi-cover.toml

`skyward-pack recovery` writes `--config` into the ramdisk verbatim, so the
image must contain exactly that file. Everything else in a packed image is
the same for both variants: the stock ramdisk, the `skyward` binary, the two
fonts, and the adb properties. A job that packed its sibling's configuration
would still pass the adb check, still be 104857600 bytes, and still end in an
AVB footer -- it would only show up on the phone as the wrong panel going
dark. This is the check that notices before flashing.

Exit status is 1 when the image carries a different file, so CI can use it.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib

ENTRY = "skyward/device.toml"


def run(pack: str, *args: str) -> bytes:
    result = subprocess.run([pack, *args], capture_output=True)
    if result.returncode != 0:
        raise SystemExit(
            f"{pack} {' '.join(args)} failed ({result.returncode}): "
            f"{result.stderr.decode('utf-8', 'replace')}"
        )
    return result.stdout


def first_difference(embedded: bytes, wanted: bytes, wanted_name: str) -> str:
    """The first line that differs, for a message a human can act on."""
    got = embedded.decode("utf-8", "replace").splitlines()
    want = wanted.decode("utf-8", "replace").splitlines()
    for number, (a, b) in enumerate(zip(got, want), start=1):
        if a != b:
            return f"line {number}: the image has {a!r}, {wanted_name} has {b!r}"
    longer, shorter = (got, want) if len(got) > len(want) else (want, got)
    return f"line {min(len(got), len(want)) + 1}: {shorter!r} ends here, {longer!r} continues"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image")
    parser.add_argument("--pack", default="skyward-pack", help="the packer to read the image with")
    parser.add_argument("--config", required=True, help="the configuration the image should carry")
    parser.add_argument("--entry", default=ENTRY, help=f"where the configuration lives in the ramdisk (default {ENTRY})")
    args = parser.parse_args()

    listing = run(args.pack, "list", args.image).decode("utf-8", "replace")
    entries = {line.split(None, 4)[-1].strip() for line in listing.splitlines() if line and not line.startswith("header")}
    if args.entry not in entries:
        print(f"FAIL the ramdisk holds no {args.entry}: the recovery would start without a device configuration")
        return 1

    embedded = run(args.pack, "cat", args.image, args.entry)
    with open(args.config, "rb") as f:
        wanted = f.read()

    if embedded != wanted:
        print(f"FAIL {args.image} carries a {args.entry} that is not {args.config}")
        print(f"     {first_difference(embedded, wanted, args.config)}")
        print("     The panel, the backlight it lights and the touch device it loads all come from this file.")
        return 1

    config = tomllib.loads(wanted.decode("utf-8"))
    display = config.get("display", {})
    touch = config.get("touch", {})
    print(f"ok   {args.entry} is byte for byte {args.config}")
    print(f"ok   the image draws on {display.get('panel')} with {display.get('backlight')}, and reads {touch.get('device')}")
    print(f"PASS: {args.image} is the {display.get('panel')} variant")
    return 0


if __name__ == "__main__":
    sys.exit(main())
