#!/usr/bin/env python3
"""dtbo_touch_panel_binding.py — 哪个触摸控制器配哪块屏。

    python tools/dtbo_touch_panel_binding.py <dtbo.img>

读法：触摸节点（synaptics_tcm@0 / goodix_berlin@0）的 `panel` 属性是一个
phandle，指向某块面板的 DTS 节点。把 phandle 反解回节点名，就得到绑定关系：

    synaptics_tcm@0 -> phandle 0x122 -> ..._prim_dsc_cmd  (1224,2912)  内屏
    goodix_berlin@0 -> phandle 0x123 -> ..._sec_dsc_cmd   (1208,1392)  外屏

这条关系决定了 recovery 想在外屏出图时该加载哪个触摸驱动、
以及 TW_INPUT_BLACKLIST 该屏蔽谁。
"""
import struct
import sys

sys.path.insert(0, __file__.rsplit("\\", 1)[0])
from dtbo_panel_scan import walk, be32  # noqa: E402


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

        # phandle -> node path
        phandles = {}
        for path, props in nodes.items():
            raw = props.get("phandle") or props.get("linux,phandle")
            if raw and len(raw) == 4:
                phandles[struct.unpack(">I", raw)[0]] = path

        # panel node -> resolution
        sizes = {}
        for path, props in nodes.items():
            if "qcom,mdss-dsi-panel-width" in props:
                panel = path.split("/")[3] if path.count("/") >= 3 else path
                sizes[panel] = (be32(props["qcom,mdss-dsi-panel-width"]),
                                be32(props.get("qcom,mdss-dsi-panel-height", b"")))

        for path, props in sorted(nodes.items()):
            tail = path.split("/")[-1]
            if not tail.startswith(("synaptics_tcm@", "goodix_berlin@")):
                continue
            if "__local_fixups__" in path:
                continue

            compatible = props.get("compatible", b"").split(b"\x00")[0].decode("latin-1")
            panel = props.get("panel")
            if not panel or len(panel) < 4:
                # The base touch node (fragment@63/64) carries no panel link;
                # a later fragment adds it to the same node name.
                continue
            phandle = struct.unpack(">I", panel[:4])[0]
            target = phandles.get(phandle, "<unresolved>")
            panel_name = target.split("/")[3] if "/" in target else target
            print("%-18s %-20s phandle 0x%03x -> %-34s %s" % (
                tail, compatible or "(patched)", phandle, panel_name,
                sizes.get(panel_name, "")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
