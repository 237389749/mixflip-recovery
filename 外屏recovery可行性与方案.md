# 能不能在 flip 外屏显示 recovery？—— bixi (MIX Flip 2) 实测与落地方案

> 过程记录，保留当时的推理。最新的改动清单、两个变体和补丁编号见
> [docs/CHANGES.md](docs/CHANGES.md) 与 [docs/VARIANTS.md](docs/VARIANTS.md)；本文的补丁细节可能已过时。

> 结论先行，证据随后。所有关于面板、触摸、DRM 的事实都取自本机工作区里的原厂镜像
> （`bixi_images_OS3.0.304.0` 的 `dtbo.img` / `vendor_boot.img` / `super` 解包）和
> TWRP-16.0 真实源码（`bootable/recovery` twrp-16.0 分支），不是推测。

---

## 一、结论

**能，而且是"改一个连接器选择"的工程量**，不是重写 recovery。

但这句"能"要拆成四件事，它们的难度完全不同：

| 事项 | 能不能 | 现在的状态 | 需要做什么 |
|---|---|---|---|
| 外屏**点亮并出图** | ✅ 能 | 做不到；现在 recovery 固定画在内屏 | 让 minui 选中外屏那个 DSI 连接器 |
| 外屏**能触摸** | ✅ 能 | 驱动已打包但没加载 | 补一行 `insmod goodix_core.ko` |
| UI **在外屏上排得下** | ⚠️ 能，但要调 | 未验证 | 1208×1392 是近方形，密度要重算 |
| **内屏同时**也出图（双屏） | ❌ 不行 | twrpminui 只驱动一个 CRTC | 要自己改 DRM 后端，属重构 |

一句话：**外屏 recovery 是可达的；外屏+内屏同时显示 recovery 不是**——TWRP 16 的
twrpminui 后端从设计上就是单面板的（下面有源码证据）。

---

## 二、现有工作区为什么是"内屏 recovery"

`twrp_device_xiaomi_sm8750_bixi` 这个树本身没问题，它的目标一直是内屏：

- `BoardConfig.mk` 注释写着 `Recovery UI: stock inner display is 1224x2912`
- `TW_BRIGHTNESS_PATH := /sys/class/backlight/panel0-backlight/brightness`（panel0 = 内屏）
- `init.recovery.qcom.rc` 里 `write /sys/class/backlight/panel1-backlight/brightness 0` 把外屏背光关掉
- 还专门写了 `bixi-cover-display-cleanup`，把外屏的 DRM pipeline 拆掉 + 强制关掉外屏 VCI 电源
  （`pm_humu_l8`），目的就是"别让外屏留着开机 logo"

所以"外屏不显示 recovery"不是 bug，是这棵树**主动选的行为**。

---

## 三、硬件真相（从原厂镜像里挖出来的）

### 3.1 两块屏都是 DSI 连接器

从 `dtbo.img`（`bixi_images_OS3.0.304.0`）解析出的 FDT：

| 项 | 内屏 | 外屏 |
|---|---|---|
| panel 节点 | `qcom,mdss_dsi_o8_42_02_0a_prim_dsc_cmd` | `qcom,mdss_dsi_o8_42_02_0a_sec_dsc_cmd` |
| 分辨率 | **1224 × 2912** | **1208 × 1392** |
| 刷新率档位 | 120 / 90 / 60 / 40 / 30 / 24 Hz | 120 / 60 Hz |
| DSC | 2 LM，slice 612×32，8bpp | 2 LM，slice 604×12，8bpp |
| DSI 连接器序号 | DSI-1 | DSI-2 |
| 触摸控制器 | **synaptics_tcm2** (`synaptics_tcm@0`) | **goodix_core** (`goodix_berlin@0`) |

"用两块不同的触摸 IC"这件事是从 DT 的 `panel` phandle 解出来的，很确定：

```
synaptics_tcm@0   panel -> phandle 0x122 -> dsi_o8_42_02_0a_prim_dsc_cmd  (1224,2912)
goodix_berlin@0   panel -> phandle 0x123 -> dsi_o8_42_02_0a_sec_dsc_cmd   (1208,1392)
```

用 `tools/dtbo_touch_panel_binding.py` 可以随时重跑这条结论。

顺带一个反直觉的点：`qcom,dsi-display-primary` 和 `-secondary` 的
`qcom,dsi-default-panel` **都指向同一个参考面板**（`nt37801_wqhd_plus_vid`，
phandle 0x118）。也就是说 DT 并没有把 o8_prim / o8_sec 写死给哪个 connector，
**选哪块屏是运行期的事**——这正好是 recovery 能自由选 connector 的前提。

这也解释了现有树里那句 `TW_INPUT_BLACKLIST := "goodix_ts"`——就是**专门屏蔽外屏触摸**。
（`goodix_core.ko` 的 input 设备名是 `goodix_ts`，`synaptics_tcm2.ko` 的是 `synaptics_tcm`。）

### 3.2 两个现有变量对不上

现有树里 `TW_BRIGHTNESS_PATH` 是 `panel0-backlight`、`TW_INPUT_BLACKLIST` 是 `goodix_ts`。
按 DT 推，panel0=内屏、panel1=外屏，那么"内屏 + 屏蔽 goodix"这对组合只有在
**goodix 接的是内屏**时才自洽。我没有原厂 kernel 的 backlight 节点绑定表
（原厂 kernel 里搜不到 `panel0-backlight` 字符串，说明这是 DTB 里 `label` 拼出来的名字，
本地无法静态确认），**所以动手前请先 dump 一份**：

```bash
adb shell ls -l /sys/class/backlight/
adb shell cat /sys/class/drm/card0-DSI-*/status
adb shell 'for f in /sys/class/drm/card0-DSI-*/modes; do echo "== $f"; head -1 $f; done'
```

期望：两个 `connected`，`DSI-1` 首选模式 `1224x2912`，`DSI-2` 首选模式 `1208x1392`。
这一步同时确认了"哪个 connector 是哪块屏"，是后面所有配置的锚点。

---

## 四、卡点在哪：twrpminui 的连接器选择

TWRP-16.0（`bootable/recovery` twrp-16.0）实际编译的是 **twrpminui**，不是老的 `minui`。
两者的能力差别很大：

| | `minui/graphics_drm.cpp`（老，未被编译） | `twrpminui/graphics_drm.cpp`（实际编译） |
|---|---|---|
| 连接器 | `DRM_MAX` 个，支持 `DRM_MAIN` / `DRM_SEC` | **只有 1 个** `main_monitor_connector` |
| 能否指定 | `HasMultipleConnectors()` / `Blank(blank, DRM_SEC)` | **没有任何 flag、property、cmdline 开关** |

证据：`twrpminui/libtwrpminui_defaults.go` 里 `globalSrcs()` 只在
`external/libdrm/Android.*` 存在时把 `graphics_drm.cpp` 加进来，而
`twrpminui/Android.bp` 的 `srcs` 里没有它；反过来 `minui/Android.bp` 的 `libminui`
虽有 `graphics_drm.cpp`，但 `libtwrpminui` 不依赖 `libminui`。
（顺带：`TW_THEME` 在 twrp-16.0 里**根本没有被读取**，只剩 `variables.h` 一个
`TW_THEME_VERSION` 宏；真正的密度来自 `ro.sf.lcd_density`。）

twrpminui 选屏逻辑就这一处（`find_main_monitor()`）：

```c
unsigned kConnectorPriority[] = {
    DRM_MODE_CONNECTOR_LVDS,
    DRM_MODE_CONNECTOR_eDP,
    DRM_MODE_CONNECTOR_DSI,
};
// 按类型优先级找第一个 connected 且有 mode 的
```

两块屏都是 DSI → 落到"DSI 类型里第一个连上的那个"，**谁先枚举到就画谁**。
bixi 上是 DSI-1（内屏）。这就是为什么现在只能内屏出来。

`get_kernel_video_mode()` 也救不了：它只认 `video=Virtual-1:WxH`（virtio-gpu 专用）。

---

## 五、落地方案

核心是给 twrpminui 加一个"按名字选连接器"的口子，然后用属性选屏。
我把它做成了两个可以直接 `git apply` 的补丁（都通过了 `git apply --check`）：

- `patches/0001-twrpminui-name-the-panel-on-foldables.patch` — 改 `bootable/recovery`
- `patches/0002-bixi-let-the-recovery-choose-its-panel.patch` — 改 `twrp_device_xiaomi_sm8750_bixi`

### 5.1 补丁 0001：twrpminui 支持指定面板

加 `find_connector_by_name()`，并让 `find_main_monitor()` 先看属性：

```
twrp.drm.connector = DSI-2        # 按连接器序号（和 /sys/class/drm/card0-DSI-2 一致）
twrp.drm.connector = 1208x1392    # 或者按面板原生分辨率
```

**不设或设错 → 完全退回现在的行为**，所以对别的机型零风险。核心逻辑：

```c
char requested_connector[PROPERTY_VALUE_MAX] = {};
if (property_get("twrp.drm.connector", requested_connector, "") > 0) {
    main_monitor_connector =
            find_connector_by_name(fd, resources, requested_connector);
    if (main_monitor_connector == nullptr) {
        printf("twrp.drm.connector=%s matched no connected panel; falling back\n",
               requested_connector);
    }
}
while (!main_monitor_connector && i < ARRAY_SIZE(kConnectorPriority)) { ... }
```

同时把原来的 `do/while` 改成 `while`，否则"属性已经命中"时那个 `do` 还会多跑一次。

> 顺手记一个坑：`graphics_drm.cpp` 原本用 `android::base::GetBoolProperty`，
> 但 `property_get` 来自 `<cutils/properties.h>`，补丁里一并加了这行 include。

### 5.2 补丁 0002：设备树跟着改

四处改动，各自独立可回退：

1. **`system.prop`** 增加 `twrp.drm.connector=DSI-1`（默认维持现状；要外屏就改 `DSI-2`）
2. **`init.recovery.qcom.rc`** 补 `insmod /vendor/lib/modules/goodix_core.ko`
   —— 驱动本来就在 `recovery/root/vendor/lib/modules/` 里，只是没人加载它
3. **`bixi_cover_display_cleanup.c`** 改成"清理**另一块**屏"
   —— 这段原本硬编码"拆 DSI-2 + 关外屏 VCI"。如果外屏变成 recovery 的显示面，
   这段会把 UI 拆了。现在它读 `twrp.drm.connector`，反过来清理内屏，
   并且**不再动 `pm_humu_l8`**（那是给外屏供电的）
4. **`Android.bp`** 给那个 cc_binary 加 `shared_libs: ["libcutils"]`（为了 `property_get`）

### 5.3 触摸

补丁 0002 只解决"驱动在跑"。**还要把黑名单去掉**，否则 TWRP 仍然不理它：

```make
# BoardConfig.mk
# TW_INPUT_BLACKLIST := "goodix_ts"      ← 删掉/注释这一行
```

这条我没有放进补丁，因为它和"外屏到底是不是 goodix"绑在一起，
必须先按 §3.2 的命令确认再改。

可能还要配旋转，取决于外屏在 DT 里的物理朝向：

```make
# BoardConfig.mk（二者取其一，实测决定）
TW_ROTATION := 0
# 或
TW_ROTATION := 90
```

`ro.twrp.touch.rotation` 也可以运行时覆盖。twrpminui 的坐标映射是
`(sensor_rotation - gr_rotation) % 360`，所以改 `TW_ROTATION` 会同时影响
"画面方向"和"触摸方向"，两者是绑定的，不要分开调。

### 5.4 密度（这条最容易漏）

1208×1392 是近方形。现有 `TW_THEME := portrait_hdpi` 在 twrp-16.0 里**不生效**，
真正决定排版的是 `ro.sf.lcd_density`（`gui2_display.cpp` 读它并 clamp 到 120~640）。
原厂值 520 是给 1224×2912 用的；放到 1208 宽的近方形屏上，横向只剩约 371dp，
TWRP 主题里那些固定宽度的行会挤。建议先试 420~460：

```prop
ro.sf.lcd_density=440
```

---

## 六、验证顺序（每步都能单独判定成败）

```bash
# 1. 哪块屏是哪个 connector（改任何配置之前先做这一步）
adb shell 'for d in /sys/class/drm/card0-DSI-*; do echo "== $d"; cat $d/status; head -1 $d/modes; done'

# 2. 补丁 0001 装上了没：日志里应该出现这一行
adb shell 'cat /tmp/recovery.log | grep -E "Chose connector|Using drm graphics|width:"'

# 3. 清理程序是否按新逻辑走（外屏模式下应看到 VCI 保留）
adb shell cat /tmp/bixi-cover-display.log
#    外屏模式期望： "cover panel is the recovery screen; VCI left powered"

# 4. 触摸驱动起来了没
adb shell 'getevent -pl 2>/dev/null | grep -E "goodix|synaptics"'
adb shell 'cat /proc/bus/input/devices | grep -A2 -iE "goodix|synaptics"'

# 5. TWRP 自己看到的 UI 尺寸
adb shell 'cat /tmp/recovery.log | grep -iE "framebuffer|drm graphics"'
```

判据：
- 第 2 步出现 `Chose connector <id> (type 16 id 2) by DSI-2` → 选屏生效
- 第 3 步出现 `VCI left powered` → 清理逻辑没有误杀外屏
- 第 4 步能列出 `goodix` 的 input 设备 → 触摸可及

---

## 七、如果不想动 TWRP 源码

有三条退路，按代价排序：

**A. 用 `skyward`（工作区里已有）**
`skyward/crates/skyward-ui/src/surface.rs` 的 `KmsSurface::open()` 是遍历
`res.connectors()` 取第一个 `is_panel() && State::Connected`——**和 TWRP 同一个问题**，
但它只有一个函数要改（`is_panel` 里已经区分了 DSI/eDP/LVDS），
而且 `devices/*.toml` 是纯数据配置，加个 `bixi.toml`
（`[display] width=1208 height=1392 density=...`）就能试外屏布局，
不用跑 AOSP 全量编译。**要快速验证"外屏 UI 到底排不排得下"，这条路最省。**

**B. 只拿 recovery 当"无头工具"**
外屏不出图也能用：`adb`、`fastbootd`、`adb sideload`、脚本刷机全都不依赖 UI。
现有树已经把 adb 配好了（`ro.adb.secure=0`，`service.adb.tcp.port=5555`）。
只是"看不见界面"，不是"不能用"。

**C. 改外层而不是底层**
`gui2` 的排版几乎完全跟着 `ro.sf.lcd_density` 走（`gui2_display.cpp` 里
`display_dpi()` 只读这一个值）。也就是说**不碰 DRM、只调密度**，
就能让现有内屏 recovery 的 UI 缩成"外屏能装下"的尺寸——但图还是出在内屏，
对外屏无意义。所以这条只适合"想验证排版"，不能解决"外屏出图"。

---

## 八、必须提前知道的风险

1. **`bixi_cover_display_cleanup` 是把双刃剑。** 它的 `force_disable_cover_vci()`
   会写 `pm_humu_l8` 的 `force_disable`。一旦在外屏模式下保留这个调用，
   表现就是"recovery 启动了但屏幕黑的"——而且**从 adb 看一切正常**（进程在跑、
   日志在写）。这就是补丁 0002 里那个 `if (cover_is_recovery_screen) return` 的原因。

2. **UFS / 分区本身与外屏无关。** 显示层坏了不影响刷机能力，所以这个实验
   不会把你锁死——真黑了还是 `fastboot` 刷回去。

3. **`persist.sys.multi_display_type` 之类的属性在这里全都不适用。** 那些是
   framework 层（SystemUI / WMS）的东西，recovery 里根本没有 framework。
   refMD 里关于属性层的整套结论（`CWB_Inject_Breakage.md` 的 CWB 崩溃等等）
   对 recovery 场景**一条都不适用**——别把那套经验搬过来。

4. **`refMD` 里的 displayId 结论也不能直接套。** flip1 上"外屏=displayId 0"
   是 framework 的 DisplayManager 行为，recovery 只认 DRM connector，没有 displayId 概念。

5. **双屏同时显示做不到。** 如果你要的是"合着能看、打开也能看"，
   TWRP 16 的 twrpminui 不提供这个能力，得改 DRM 后端到多 CRTC
   （老 `minui` 有 `DRM_SEC` 的雏形，但那份代码在 twrp-16.0 里没被编译）。

---

## 九、附：补丁清单

```
patches/
├── 0001-twrpminui-name-the-panel-on-foldables.patch   # bootable/recovery
└── 0002-bixi-let-the-recovery-choose-its-panel.patch  # twrp_device_xiaomi_sm8750_bixi
```

应用方式：

```bash
# 在 TWRP 源码树根目录
repo init -u https://github.com/TWRP-Test/platform_manifest_twrp_aosp -b twrp-16.0 --depth=1
repo sync
git clone <bixi tree> -b twrp-16.0 device/xiaomi/bixi

# 0001 打在 bootable/recovery 里
cd bootable/recovery && git apply ../../patches/0001-twrpminui-name-the-panel-on-foldables.patch && cd ../..

# 0002 打在设备树里
cd device/xiaomi/bixi && git apply ../../../patches/0002-bixi-let-the-recovery-choose-its-panel.patch && cd ../../..

# 要外屏就把默认值改掉
sed -i 's/^twrp.drm.connector=DSI-1/twrp.drm.connector=DSI-2/' device/xiaomi/bixi/system.prop
# 并把 goodix 从黑名单里拿掉（确认 goodix 确实是外屏触摸之后）
sed -i 's/^TW_INPUT_BLACKLIST/# TW_INPUT_BLACKLIST/' device/xiaomi/bixi/BoardConfig.mk

export ALLOW_MISSING_DEPENDENCIES=true
source build/envsetup.sh
lunch twrp_bixi-bp2a-eng
m recoveryimage
```

---

## 十、我没有验证的部分（诚实交代）

- **没能真机跑**：会话里没有接设备（`adb devices` 为空）。
  本文所有硬件结论来自原厂镜像静态解析，不是实测。
- **`panel0`/`panel1` 背光节点的归属**没坐实：原厂 kernel 里搜不到这两个字符串，
  它们是 DTB 的 `label` 拼出来的。§3.2 的 dump 命令就是补这一刀。
- **`goodix_core.ko` 在 recovery 环境下能否正常 probe**（它依赖
  `xiaomi_touch.ko`，且要走 SPI + `/odm/firmware/goodix_*_bixi.bin`）没有实测。
  固件在 ramdisk 里是有的（`recovery/root/odm/firmware/goodix_*`），
  但 SPI 时序、pinctrl 是否在 recovery 下被初始化过，要上机看 `dmesg`。
- **外屏 1208×1392 下 gui2 的实际排版**没跑过。这是唯一一个"技术上能做但可能
  难看到不能用"的点，建议先用 §7-A 的 skyward 路线快速目测。
