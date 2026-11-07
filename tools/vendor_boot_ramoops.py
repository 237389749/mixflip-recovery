#!/usr/bin/env python3
"""Show the ramoops region a vendor_boot image's device trees describe.

    python tools/vendor_boot_ramoops.py <vendor_boot.img>

`pstore`'s `ramoops` backend keeps the kernel log in reserved memory that a
reboot does not clear, so a phone that will not boot can still say why: run
the recovery, read `/sys/fs/pstore`. Whether that is possible at all is
decided by the device tree the kernel is handed -- no node, no pstore, and
the log of the failed boot is gone.

A vendor_boot image carries one device tree per board revision, so every FDT
in it is read and their ramoops regions are required to agree: a region that
moves between boards leaves the log where one board cannot read it.

The output is meant to be pasted into docs/BOOTLOG.md when the firmware
changes, so the numbers there stay the ones this image actually has.
"""

from __future__ import annotations

import struct
import sys

MAGIC = b"\xd0\x0d\xfe\xed"
MiB = 1024 * 1024
SIZES = ("console-size", "pmsg-size", "record-size", "ftrace-size")


def align4(position: int) -> int:
    return (position + 3) & ~3


def parse(blob: bytes, at: int) -> list[tuple[str, str, bytes]]:
    """Every (node path, property name, value) of the FDT that starts at `at`."""
    magic, total, off_struct, off_strings, _rsv, version, _comp, _cpu, size_strings, size_struct = struct.unpack_from(">10I", blob, at)
    if magic != 0xD00DFEED or version not in (16, 17):
        raise ValueError(f"not an FDT (magic {magic:#x}, version {version})")
    if at + total > len(blob) or off_struct + size_struct > total or off_strings + size_strings > total:
        raise ValueError("an FDT whose sections run past its own length")

    block = blob[at + off_struct : at + off_struct + size_struct]
    names = blob[at + off_strings : at + off_strings + size_strings]
    position, path, out = 0, [], []
    while position + 4 <= len(block):
        (tag,) = struct.unpack_from(">I", block, position)
        position += 4
        if tag == 1:  # FDT_BEGIN_NODE
            end = block.index(b"\0", position)
            path.append(block[position:end].decode("latin-1"))
            position = align4(end + 1)
        elif tag == 2:  # FDT_END_NODE
            if path:
                path.pop()
        elif tag == 3:  # FDT_PROP
            length, name_offset = struct.unpack_from(">II", block, position)
            position += 8
            name = names[name_offset : names.index(b"\0", name_offset)].decode("latin-1")
            out.append(("/".join(path), name, block[position : position + length]))
            position = align4(position + length)
        elif tag == 4:  # FDT_NOP
            continue
        elif tag == 9:  # FDT_END
            break
        else:
            raise ValueError(f"unknown FDT tag {tag} at {position - 4}")
    return out


def ramoops(nodes: list[tuple[str, str, bytes]]) -> tuple[str, dict[str, bytes]] | None:
    """The path and properties of the node whose compatible names ramoops."""
    paths = sorted({path for path, name, value in nodes if name == "compatible" and b"ramoops" in value})
    if not paths:
        return None
    props = {name: value for path, name, value in nodes if path == paths[0]}
    return paths[0], props


def size_text(value: bytes) -> str:
    number = struct.unpack(">I", value)[0]
    return f"{number:#010x} ({number // MiB} MiB)" if number % MiB == 0 else f"{number:#010x} ({number} bytes)"


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    blob = open(sys.argv[1], "rb").read()

    found: list[tuple[int, str, dict[str, bytes]]] = []
    position = 0
    while True:
        at = blob.find(MAGIC, position)
        if at < 0:
            break
        position = at + 4
        try:
            nodes = parse(blob, at)
        except (ValueError, struct.error, IndexError):
            continue  # four stray bytes that look like a magic, not a tree
        # An FDT with a handful of properties is a coincidence; a real one for
        # this platform has thousands, which is also the parser's self-check.
        if len(nodes) < 1000:
            continue
        region = ramoops(nodes)
        if region is not None:
            found.append((at, *region))

    if not found:
        print(f"FAIL no device tree in {sys.argv[1]} names a ramoops region")
        print("     pstore has nowhere to keep the log of a boot that failed")
        return 1

    for number, (at, path, props) in enumerate(found, start=1):
        reg = props.get("reg", b"")
        print(f"dt #{number} at {at:#010x}: {len(props)} properties on {path}")
        if len(reg) >= 16:
            cells = struct.unpack(f">{len(reg) // 4}I", reg)
            base, length = (cells[0] << 32) | cells[1], (cells[2] << 32) | cells[3]
            print(f"    reg          = {base:#018x} + {length // MiB} MiB")
        for key in SIZES:
            value = props.get(key)
            print(f"    {key:<13}= {size_text(value) if value else 'absent (the kernel default applies)'}")

    def signature(props: dict[str, bytes]) -> tuple:
        return tuple(props.get(key) for key in ("reg",) + SIZES)

    if any(signature(props) != signature(found[0][2]) for _, _, props in found[1:]):
        print(f"FAIL the {len(found)} device trees name different ramoops regions")
        print("     the log would be left where another board revision cannot read it")
        return 1

    console = found[0][2].get("console-size")
    print(f"\nPASS {len(found)} device trees agree: one ramoops region" + (f", console {size_text(console)}" if console else ""))
    print("     /sys/fs/pstore holds the kernel log of a boot that failed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
