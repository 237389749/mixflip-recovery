#!/usr/bin/env python3
"""dtbo_panel_scan.py — 列出 dtbo.img 里所有面板及其原生分辨率。

    python tools/dtbo_panel_scan.py <dtbo.img> [名字过滤...]

dtbo 的 FDT 结构是大端，且节点名之后要 4 字节对齐；这两点做错就会解析出
0 个节点。这里按 fdt_header 的 off_dt_struct / off_dt_strings 走一遍。
"""
import struct
import sys


def align4(x):
    return (x + 3) & ~3


def walk(dtb, base):
    (magic, total, off_struct, off_strings, off_rsv, ver, lastc, cpuid,
     size_strings, size_struct) = struct.unpack(">10I", dtb[base:base + 40])
    if magic != 0xd00dfeed:
        raise ValueError("no FDT magic at 0x%x" % base)

    sblk = dtb[base + off_struct: base + off_struct + size_struct]
    strings = dtb[base + off_strings: base + off_strings + size_strings]

    def name_of(off):
        end = strings.find(b"\x00", off)
        return strings[off:end].decode("latin-1")

    pos, path, nodes = 0, [], {}
    while pos + 4 <= len(sblk):
        tag, = struct.unpack(">I", sblk[pos:pos + 4])
        pos += 4
        if tag == 1:                      # FDT_BEGIN_NODE
            end = sblk.find(b"\x00", pos)
            path.append(sblk[pos:end].decode("latin-1"))
            pos = align4(end + 1)
        elif tag == 2:                    # FDT_END_NODE
            if path:
                path.pop()
        elif tag == 3:                    # FDT_PROP
            plen, nameoff = struct.unpack(">II", sblk[pos:pos + 8])
            pos += 8
            value = sblk[pos:pos + plen]
            pos = align4(pos + plen)
            nodes.setdefault("/".join(p for p in path if p), {})[name_of(nameoff)] = value
        elif tag == 4:                    # FDT_NOP
            continue
        elif tag == 9:                    # FDT_END
            break
        else:
            raise ValueError("bad FDT tag %d at %d" % (tag, pos))
    return nodes


def be32(value):
    return struct.unpack(">I", value.ljust(4, b"\x00")[:4])[0]


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1

    dtb = open(argv[1], "rb").read()
    filters = argv[2:]

    magic, total, hdr_size, ent_size, ent_count, ent_off, page = \
        struct.unpack(">8I", dtb[:32])[:7]
    print("dt_table magic=%08x entries=%d" % (magic, ent_count))

    for i in range(ent_count):
        off = ent_off + i * ent_size
        size, dtb_off, dtb_id, rev = struct.unpack(">4I", dtb[off:off + 16])
        nodes = walk(dtb, dtb_off)
        print("entry %d  id=%08x rev=%d  nodes=%d" % (i, dtb_id, rev, len(nodes)))

        for key, props in nodes.items():
            if "qcom,mdss-dsi-panel-width" not in props:
                continue
            if filters and not any(f in key for f in filters):
                continue
            width = be32(props["qcom,mdss-dsi-panel-width"])
            height = be32(props.get("qcom,mdss-dsi-panel-height", b""))
            fps = be32(props.get("qcom,mdss-dsi-panel-framerate", b""))
            print("    %-72s %4d x %-5d @%s" % (key, width, height, fps or "?"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
