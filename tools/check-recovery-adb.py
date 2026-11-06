#!/usr/bin/env python3
"""Check that a packed recovery keeps adb on, as root, with no prompt.

    python tools/check-recovery-adb.py <recovery.img> [--pack <skyward-pack>]

Skyward's packer appends the properties that make adbd keep root and let any
computer in, and leaves the stock init that starts adbd as root. This checks
the image that came out, rather than trusting the source:

  - system/bin/adbd is in the ramdisk;
  - prop.default's *last* ro.secure / ro.adb.secure / ro.debuggable lines
    are 0 / 0 / 1 (a later line overrides an earlier one, which is how the
    stock values are replaced);
  - init.rc defines `service adbd` with `user root` and starts it when
    sys.usb.config is adb.

There is no `su` binary in a stock recovery ramdisk, and none is needed:
adbd's service already runs as root, so `adb shell` is a root shell. The
check reports a su binary if one is there, but does not require it.

Exit status is 1 when a check fails, so CI can use it on the packed image.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

ADBD = "system/bin/adbd"
PROP = "prop.default"
INIT = "system/etc/init/hw/init.rc"


def run(pack: str, *args: str) -> str:
    result = subprocess.run([pack, *args], capture_output=True)
    if result.returncode != 0:
        raise SystemExit(f"{pack} {' '.join(args)} failed ({result.returncode}): {result.stderr.decode('utf-8', 'replace')}")
    return result.stdout.decode("utf-8", "replace")


def last_value(props: str, name: str) -> str | None:
    value = None
    for line in props.splitlines():
        if line.startswith(name + "="):
            value = line[len(name) + 1 :].strip()
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image")
    parser.add_argument("--pack", default=os.environ.get("SKYWARD_PACK", "skyward-pack"))
    args = parser.parse_args()

    listing = run(args.pack, "list", args.image)
    entries = {line.split(None, 4)[-1].strip() for line in listing.splitlines() if line and not line.startswith("header")}

    failed = False

    if ADBD in entries:
        print(f"ok   {ADBD} is in the ramdisk")
    else:
        print(f"FAIL {ADBD} is missing: adb cannot start")
        failed = True

    props = run(args.pack, "cat", args.image, PROP)
    for name, want in (("ro.secure", "0"), ("ro.adb.secure", "0"), ("ro.debuggable", "1")):
        got = last_value(props, name)
        if got == want:
            print(f"ok   {name}={got} (last line)")
        else:
            print(f"FAIL {name} is {got!r}, expected {want!r} as the last line")
            failed = True

    init = run(args.pack, "cat", args.image, INIT)
    if "service adbd " in init:
        print("ok   init.rc defines the adbd service")
    else:
        print("FAIL init.rc does not define the adbd service")
        failed = True
    # The service's own block: adbd runs as root, so the shell adb opens is root.
    block = init.split("service adbd ", 1)[1].split("\nservice ", 1)[0] if "service adbd " in init else ""
    if "user root" in block:
        print("ok   adbd runs as root")
    else:
        print("FAIL adbd does not run as root")
        failed = True
    if "start adbd" in init and "sys.usb.config=adb" in init:
        print("ok   init.rc starts adbd when sys.usb.config is adb")
    else:
        print("FAIL init.rc does not start adbd on sys.usb.config=adb")
        failed = True

    su = sorted(e for e in entries if e.rsplit("/", 1)[-1] == "su")
    if su:
        print(f"note a su binary is present: {su}")
    else:
        print("note no su binary; adbd is already root, so `adb shell` is root")

    if failed:
        print("FAILED: the image does not keep adb on as root")
        return 1
    print("PASS: adb is on by default, as root, with no authorization prompt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
