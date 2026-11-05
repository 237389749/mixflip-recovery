#!/usr/bin/env python3
"""dtbo_dsc_topology.py — 两块屏的 DSC / layer-mixer 拓扑。

    python tools/dtbo_dsc_topology.py <dtbo.img> [panel 名过滤]

recovery 的 DRM 后端起不来时，最常见的原因是 LM 数量猜错（twrpminui 从
connector 的 `mode_properties` blob 里读 topology 名推 LM 数，读不到就退回
DEFAULT_NUM_LMS=2）。这里直接给出每块屏的真实 topology 和 DSC 参数，
用来到真机上核对：

    adb shell 'cat /sys/kernel/debug/dri/0/DSI-2/…'   # 或 dumpsys 的 sde 节点
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
    filters = argv[2:]
    magic, total, hdr_size, ent_size, ent_count, ent_off, page = \
        struct.unpack(">8I", dtb[:32])[:7]

    for i in range(ent_count):
        off = ent_off + i * ent_size
        _, dtb_off, _, _ = struct.unpack(">4I", dtb[off:off + 16])
        nodes = walk(dtb, dtb_off)

        for path, props in sorted(nodes.items()):
            if "qcom,mdss-dsi-panel-width" not in props:
                continue
            if "timing@" not in path:
                continue
            if filters and not any(f in path for f in filters):
                continue

            width = be32(props["qcom,mdss-dsi-panel-width"])
            height = be32(props.get("qcom,mdss-dsi-panel-height", b""))
            fps = be32(props.get("qcom,mdss-dsi-panel-framerate", b""))

            topology = props.get("qcom,display-topology")
            topo = [struct.unpack(">I", topology[j:j + 4])[0]
                    for j in range(0, len(topology) - len(topology) % 4, 4)] \
                if topology else None

            def one(name):
                raw = props.get(name)
                return be32(raw) if raw else None

            print("%-18s %-22s %4dx%-5d @%-3s topo=%-10s slice=%sx%s bpp=%s" % (
                path.split("/")[3].replace("qcom,mdss_dsi_", ""),
                path.split("/")[-1], width, height, fps, topo,
                one("qcom,mdss-dsc-slice-width"),
                one("qcom,mdss-dsc-slice-height"),
                one("qcom,mdss-dsc-bit-per-pixel")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
