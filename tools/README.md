# dtbo 分析脚本

用来从原厂 `dtbo.img` 里静态确认"哪块屏是哪个面板 / 哪个触摸控制器配哪块屏"。
都是在 Windows 上直接跑的纯 Python 3（只用标准库），输入一个 `dtbo.img` 路径。

这些脚本是我在回答"能不能在外屏显示 recovery"时为了拿到硬事实而写的，
留在仓库里是因为**换固件版本后需要重新跑一遍**——面板名、分辨率、phandle
都可能变。

```powershell
python tools\dtbo_panel_scan.py      <dtbo.img>   # 所有面板 + 分辨率
python tools\dtbo_dsc_topology.py    <dtbo.img>   # 两块屏的 DSC / LM 拓扑
python tools\dtbo_touch_panel_binding.py <dtbo.img>  # 触摸 IC 绑定到哪块屏
python tools\dtbo_dsi_default_panel.py   <dtbo.img>  # dsi-display-{primary,secondary} 的默认面板
```

`dtbo.img` 本体在：

```
bixi_images_OS3.0.304.0\bixi_images_OS3.0.304.0.WOHCNXM_16.0\images\dtbo.img
```

## 为什么需要自己解析

`libfdt` 的 FDT 结构在 dtbo 里是**大端**，而且节点名之后要按 4 字节对齐
（`align4(name_end + 1)`）。这两个细节任一做错，解析出来就是 0 个节点或
一堆垃圾 tag——网上不少脚本就是栽在这里。

## 2026-11 实测结果（OS3.0.304.0.WOHCNXM）

| | 内屏 | 外屏 |
|---|---|---|
| panel | `qcom,mdss_dsi_o8_42_02_0a_prim_dsc_cmd` | `qcom,mdss_dsi_o8_42_02_0a_sec_dsc_cmd` |
| 分辨率 | 1224 × 2912 | 1208 × 1392 |
| 刷新档位 | 120/90/60/40/30/24 | 120/60 |
| DSC | 2 LM，612×32，8bpp | 2 LM，604×12，8bpp |
| 触摸 IC | `synaptics_tcm2` (`synaptics_tcm@0`) | `goodix_core` (`goodix_berlin@0`) |
| 触摸→面板 | phandle 0x122 → prim | phandle 0x123 → sec |

## recovery 镜像检查（不是 dtbo）

`check-recovery-adb.py` 检查**打出来的 recovery 镜像**是否默认开 adb、是否 root：

```powershell
python tools\check-recovery-adb.py <recovery.img> --pack <skyward-pack.exe>
```

它读 ramdisk 里的 `system/bin/adbd`、`prop.default`、`init.rc`，确认：

- adbd 存在，服务以 `user root` 运行；
- `ro.secure` / `ro.adb.secure` / `ro.debuggable` 的**最后一行**是 0/0/1；
- `sys.usb.config=adb` 时会 `start adbd`。

CI 的 `image` job 出包后会自动跑它。为什么没有 `su`、为什么不需要，见
[../docs/ADB_AND_ROOT.md](../docs/ADB_AND_ROOT.md)。
