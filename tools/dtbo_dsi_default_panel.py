#!/usr/bin/env python3
"""dtbo_dsi_default_panel.py — qcom,dsi-display-{primary,secondary} 绑的默认面板。

    python tools/dtbo_dsi_default_panel.py <dtbo.img>

两块屏在 DT 里都有 `qcom,dsi-default-panel`，但**原厂两者都指向同一个
参考面板**（`qcom,mdss_dsi_nt37801_wqhd_plus_vid`，phandle 0x118）——
也就是说，DT 里并没有把 o8_prim / o8_sec 硬绑到 primary/secondary 上，
真正选哪块 panel 是运行期决定的。这一点对"能不能只让外屏出图"很关键：
内核侧没有把面板归属写死，recovery 里选哪个 connector 是我们自己说了算。

真实的面板归属要另外找：`qcom,mdss-dsi-display-timings` 下的分辨率
（见 dtbo_panel_scan.py）和触摸节点的 `panel` phandle
（见 dtbo_touch_panel_binding.py）。
"""
import struct
import sys

sys.path.insert(0, __file__.rsplit("\\", 1)[0])
from dtbo_panel_scan import walk  # noqa: E402


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1

    dtb = open(argv[1], "rb").read()
    magic, total, hdr_size, ent_size, ent_count, ent_off, page = \
        struct.unpack(">8I", dtb[:32])[:7]

    for i in range(ent_count):
        off = ent_off + i * ent_size
        _, dtb_off, _, _ = struct.unpack(">4I", dtb[off:off + 16])
        nodes = walk(dtb, dtb_off)

        phandles = {}
        for path, props in nodes.items():
            raw = props.get("phandle") or props.get("linux,phandle")
            if raw and len(raw) == 4:
                phandles[struct.unpack(">I", raw)[0]] = path

        for path, props in sorted(nodes.items()):
            data = props.get("qcom,dsi-default-panel")
            if not data:
                continue
            phandle, = struct.unpack(">I", data[:4])
            if phandle == 0:
                # Pre-overlay placeholder; the real value comes in later.
                continue
            label = props.get("label", b"").split(b"\x00")[0].decode("latin-1")
            print("%-46s label=%-12s default-panel phandle 0x%03x -> %s" % (
                path.split("__overlay__/")[-1], label or "-", phandle,
                phandles.get(phandle, "<unresolved>").split("/")[-1]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
