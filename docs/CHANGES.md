# 改动点记载

> 目的：随时能出「内屏版」和「单外屏版」两个 recovery，并且知道每个版本改了哪里、为什么改、
> 验证到哪一步。**这份文件是改动清单，操作步骤见 [VARIANTS.md](VARIANTS.md)。**
>
> 基线（`manifest.toml` 里也是这几个）：
>
> | 代码库 | 基线 |
> |---|---|
> | skyward | v0.1.2，`c9deaf026eaf83fe2b9141dd656c256ddf42c8c1` |
> | TWRP `bootable/recovery` | `twrp-16.0`，`8a58fc3b586b8a908337fa87529cfbbb119ec7bb` |
> | bixi 设备树 | `twrp-16.0-kernel6.6.139`，`9b4b445004006fc2ffbdfefbf7fc7e7758cf129a` |
> | 原厂包 | `OS3.0.304.0.WOHCNXM`（fastboot 包，`recovery.img` sha256 `bc32c5fa…`） |

---

## 0. 先划清边界

| 目标 | 结论 | 为什么 |
|---|---|---|
| fastboot 界面显示在外屏 | ❌ | 那是 bootloader（abl）画的，改 ROM/recovery 都够不到 |
| recovery 显示在外屏 | ✅ | recovery 是 Linux 用户态程序，自己打开 `/dev/dri/card0` 做 modeset |
| recovery 双屏同显 | ❌ | 两个后端都是单 CRTC；要做得多 CRTC，不是本次范围 |
| 开机的两屏 logo | ⚠️ 两块都会收到 | 所以选了一块屏之后，**另一块要主动关背光**，否则一直亮着 |

**最容易误判的一条**：改设备树（DTBO）让某块屏“默认”没用。两块屏都是 DSI，运行时都
`Connected`，选哪块是 recovery 代码里的循环决定的，不是设备树。

---

## 1. 两个变体

| | `bixi`（内屏版） | `bixi-cover`（单外屏版） |
|---|---|---|
| 配置文件 | `devices/bixi.toml` | `devices/bixi-cover.toml` |
| `[display] panel` | `1224x2912` | `1208x1392` |
| `[display] backlight` | `panel0-backlight` | `panel1-backlight` |
| `[display] backlights_off` | `["panel1-backlight"]` | `["panel0-backlight"]` |
| `[touch] device` | `synaptics` | `goodix` |
| `[modules] load` | `["synaptics_tcm2"]` | `["goodix_core"]` |
| `[display] width/height` | 1224×2912 | 1208×1392 |
| `[display] density` | 520（原厂值） | 440（外屏近方形，原厂值偏大） |
| `[display] diagonal` | 6.86 | 4.01 |
| `[display] corner_radius` | 省略（0） | 62 |
| 触摸 IC | Synaptics TouchComm | Goodix Berlin |
| 面板节点 | `…_prim_dsc_cmd` | `…_sec_dsc_cmd` |
| DSI 连接器 | DSI-1 | DSI-2 |

除上表这些键，两份配置**必须逐字相同**。`ci/check-variants.py` 会解析两份 TOML、去掉这些键
再比较，防止维护时只改了一边。

> `codename` 两份都写 `bixi`：它表示机器，不表示变体。变体靠**配置文件名**区分，
> 产物名里也带 `bixi` / `bixi-cover`。

---

## 2. skyward 侧改动

补丁：`0003`（选屏 + 背光 + 两处容错）、`0004`（触摸 + 另一块屏关背光）、`0005`（bixi 配置测试）、
`0006`（短屏上“按住行”的裁切）、`0007`（去掉 stock 的 adb 属性）。

### S1 选屏：`[display] panel`

| | |
|---|---|
| 文件 | `crates/skyward-ui/src/surface.rs`、`crates/skyward-config/src/lib.rs` |
| 原行为 | `KmsSurface::open()` 遍历 connector，取第一个 `is_panel && Connected` |
| 现行为 | `open_on(path, cfg.display.panel)`：按连接器名（`DSI-2`）或面板原生分辨率（`1208x1392`）命中；不写则退回原行为 |
| 为什么 | 两块都是 DSI，原逻辑永远拿 DSI-1（内屏）。改设备树无效 |
| 影响 | 两个变体都靠它；不写 `panel` 的 21 个现有机型零影响 |

实现要点：

- `Wanted::{Connector, Size}` + 两个纯函数 `parse` / `matches`，不碰 DRM，所以能在电脑上测；
- **先弱读再强读**：`get_connector(h, false)` 拿 modes，命中后才 `true`，避免为了看分辨率去 probe 另一块屏；
- **匹配不到就报错并列出实际面板**，不静默退回第一块。折机上静默退回等于画到用户看不见的那块屏。

### S2 背光：`[display] backlight`

| | |
|---|---|
| 文件 | `crates/skyward/src/ui.rs` `Backlight::open` |
| 原行为 | 固定找 `panel0-backlight`（内屏），找不到取排序第一个 |
| 现行为 | 配置里点名哪个就用哪个；名字不存在则**回退并告警**，不让 UI 因为一个名字起不来 |
| 为什么 | 只改选屏不改背光 → 画在外屏、点亮内屏 → **外屏全黑，日志全绿** |

### S3 `normal_max()` 容错

原实现硬依赖 `/sys/module/msm_drm/parameters/dsi_display0`。bixi 的内核是 mainline 风格
msm 驱动，没有这个参数，原代码直接 `?` 失败，UI 起不来。

现在：拿不到参数（或参数格式不对、DT 节点不存在、没有 normal-max 属性）就把
`max_brightness` 当作正常上限。对 13 Ultra / 17 Ultra 走原路径，数值不变。

### S4 `resonance()` 单位容错

`qcom-hv-haptics` 的 `lra_frequency_hz` 是**整数 Hz + " Hz"**；17 Ultra 的驱动是**裸数字、十分之一 Hz**。
原代码按后者解析，bixi 会得到 172.4 → 17.24 Hz。现在看结尾有没有 `Hz` 判单位，裸数字保持原语义。

### S5 `skyward-preview --device`

原代码硬编码 `devices/nezha.toml`。现在可以 `--device bixi` / `--device bixi-cover`，
在电脑上按两块屏各自的尺寸/密度把页面渲染成 PNG，**不用真机就能看排版**。
（`skyward-preview` 依赖 unix-only 的 crate，Windows 编不了；这正是要 CI 的原因。）

### S6 触摸：`[touch] device`

| | |
|---|---|
| 文件 | `crates/skyward/src/input.rs`、`crates/skyward-config/src/lib.rs` |
| 原行为 | 取**第一个** `DIRECT + 多点触摸` 的 `/dev/input` 设备 |
| 现行为 | 配置里给名字片段（`synaptics` / `goodix`），取名字包含它的那个；都不匹配才回退第一个并告警 |
| 为什么 | bixi 一块屏一个触摸 IC，两个驱动都加载时谁先枚举谁被选中。**这是两个版本必须区分的第二个维度**，只改显示不改触摸 = 摸外屏没反应、摸内屏控制外屏 |

另外每个变体只加载自己那块屏的触摸驱动（`[modules] load`）：驱动在面板不存在时可能 probe 失败，
`finit_module` 会返回错误，而 skyward 把加载失败当致命错误 —— 会在画出第一帧之前就退出。
“两块都加载、运行时再选”听起来更灵活，代价是没内屏的机器可能连外屏都起不来。

### S7 另一块屏关背光：`[display] backlights_off`

| | |
|---|---|
| 文件 | `crates/skyward/src/ui.rs` `Backlight::open` |
| 原行为 | 只操作选中的那块屏，另一块保持 bootloader 留下的亮度 |
| 现行为 | 启动时把列表里的背光写 0 |
| 为什么 | 两块屏开机都会收到 bootloader 的连续开机画面；只关背光不够“省电”，但足够不让另一块亮着 |

⚠️ 只关背光，**没有关另一块屏的 CRTC 和 VCI**。那块屏仍然在 scanout（黑画面）、仍然供电。
彻底断电要像 `bixi-cover-display-cleanup` 那样操作 regulator debugfs，skyward 不跑那个程序。
这是已知限制，不是遗漏。

### S8 bixi 配置与测试

- `devices/bixi.toml`、`devices/bixi-cover.toml`：本仓库提供，不打进补丁（上游 CI 没有原厂包，
  把 `bixi.toml` 提交上游会让它的 devices 矩阵变红）；
- 两份配置的 `[modules] load` 不同：各自只加载自己那块屏的触摸驱动（理由见 S6）；
- `0005` 加三个测试：两份配置的面板/背光/触摸/模块/密度，以及 bixi 启动所需的服务清单。

### S9 短屏上“按住行”的裁切

| | |
|---|---|
| 文件 | `crates/skyward-ui/src/app.rs` `row_part` |
| 原行为 | 只按整页宽高裁，不看当前 canvas 实际只画了哪一段行（band） |
| 现行为 | 同时裁到 `canvas.held()` / `canvas.cols()`；整行不在 band 里就不画按压态，等它进入再画 |
| 为什么 | 页是分 band 画的；1208×1392 的外屏上，按住一行靠近 band 边缘时 `crop` 越界，`assert` 直接把进程 abort |
| 怎么发现 | `skyward-preview --device bixi-cover` 跑到 `70-erase` 页时 exit 134。**这是外屏尺寸第一次被真跑就抓到的 bug**，内屏 1224×2912 上不触发 |
| 影响 | 两个变体都受益；只在短屏/band 边缘触发 |

### S10 去掉 stock 的 adb 属性

| | |
|---|---|
| 文件 | `crates/skyward-pack/src/main.rs` |
| 原行为 | 只在 `prop.default` 末尾追加 `ro.secure=0` 等，stock 原有的 `ro.secure=1` / `ro.adb.secure=1` / `ro.debuggable=0` 还在，靠“同一文件后面的行覆盖前面的”生效 |
| 现行为 | 先用 `without()` 把这 6 个属性（3 个 build version + 3 个 adb）删掉，再追加 0/0/1；结果里没有重复行 |
| 为什么 | 外屏可能全黑，adb 是唯一入口；把“能不能 root”压在一个未在本机验证的 init 行为上不值得 |
| 验证 | `cargo test -p skyward-pack` 7 passed；重新打包后 `prop.default` 只剩 `ro.secure=0` / `ro.adb.secure=0` / `ro.debuggable=1`，`check-recovery-adb.py` PASS |

### P1 默认 adb / root（上游行为，本仓库负责核验）

不是我们写的补丁，但外屏可能全黑，这条是“能不能用”的前提，所以列进改动记载并加了自动检查：

| | |
|---|---|
| 谁做的 | `skyward-pack` 先删掉 stock 里相反的值，再追加 `ro.secure=0` / `ro.adb.secure=0` / `ro.debuggable=1`（0007） |
| 启动链 | 原厂 `init.rc` 的 `service adbd … user root`；`sys.usb.config=adb` 时 `start adbd`；skyward 在加载配置/起 UI **之前**就把 `sys.usb.config` 设成 `adb` |
| 结果 | 插 USB 即 `adb`，无授权弹窗，`adb shell` 是 uid 0 |
| `su` | 原厂 ramdisk 没有 `su`，toybox 也没编；不需要，`adb shell` 本身是 root |
| 核验 | `tools/check-recovery-adb.py` 检查打出来的镜像（adbd、属性最后一行、init 规则）；CI 的 `image` job 出包后自动跑 |
| 细节 | [ADB_AND_ROOT.md](ADB_AND_ROOT.md) |

---

## 3. TWRP 侧改动

补丁：`0001`（`bootable/recovery`）、`0002` + `0002b`（设备树，按顺序打）。

`0002b` 建立在 `0002` 之上：`0002` 是“让 recovery 能按名字选屏”，`0002b` 是“同一棵树出两个版本”。
单独打 `0002b` 会失败，这是有意为之——它改的正是 `0002` 引入的那几行。

### T1 `twrpminui` 按名字选连接器

| | |
|---|---|
| 文件 | `twrpminui/graphics_drm.cpp` |
| 改动 | 新增 `find_connector_by_name()`；读 `twrp.drm.connector`，支持 `DSI-2` / `1208x1392`；未设置或匹配不到时保持原优先级回退 |
| 为什么 | `find_main_monitor()` 按 `{LVDS, eDP, DSI}` 类型优先级取第一个，两块都是 DSI |
| 验证 | 真实 TWRP 16 源码上 `git apply` + **`g++ -fsyntax-only` 通过**（CI 每次跑） |
| 修复 | `DSI-0` 是 `connector_type_id == 0`，旧写法把 0 当成“没给名字”，会匹配失败；已改为独立的 `by_type` |

编译验证只证明语法/头文件/类型正确，**不证明链接进 TWRP 后行为正确**，更不证明真机点亮。

### T2 设备树配合（0002）

| 文件 | 改动 | 为什么 |
|---|---|---|
| `Android.bp` | `bixi-cover-display-cleanup` 加 `libcutils` | 用 `property_get` 读选屏属性 |
| `display/bixi_cover_display_cleanup.c` | 按属性判断 recovery 是否画在外屏；是则改为清理**内屏**的 CRTC，并**不** `force_disable` 外屏 VCI | 原程序专为“外屏不显示”设计，会把你要用的那块屏断电 |
| `recovery/root/init.recovery.qcom.rc` | 追加 `insmod goodix_core.ko` | 外屏触摸是 Goodix；原来只加载内屏的 Synaptics |
| `system.prop` | `twrp.drm.connector=DSI-1` | 默认仍是内屏，行为不变 |

### T3 单外屏版：同一棵树出两个变体（0002b）

TWRP 侧以前只有内屏版。`0002b` 让它像 skyward 一样一棵树出两个版本，用 make 变量
`BIXI_COVER_SCREEN=1` 选外屏：

| 项 | 内屏版（默认） | 单外屏版（`BIXI_COVER_SCREEN=1`） |
|---|---|---|
| `TW_BRIGHTNESS_PATH` | `panel0-backlight` | `panel1-backlight` |
| 触摸 | `TW_INPUT_BLACKLIST="goodix_ts"` | `TW_WHITELIST_INPUT="goodix_ts"` |
| 选屏属性 | `panel-inner.prop`：`DSI-1` | `panel-cover.prop`：`DSI-2` |

三个关键设计：

1. **变体判断放在 `BoardConfig.mk` 最顶部**。make 的 `ifeq` 是立即求值，变量定义在下面就会
   拿到空值——`TARGET_SYSTEM_PROP` 那行正是这样。
2. **选屏属性单独成文件**，两份各写一个 `twrp.drm.connector`，`system.prop` 不写。
   否则两个文件设同一个属性，结果取决于 init 先读哪个——和 skyward 侧 `0007` 消除的是同一类问题。
3. **背光写入从 `.rc` 移到 `bixi_cover_display_cleanup.c`**。init 的 `.rc` **不经预处理**，
   `ifeq` 在里面无效；这个 C 程序本来就跑在 recovery 打开 card0 之前，而且 CI 会编译它。
   它读同一个 `twrp.drm.connector` 决定点亮哪块、关掉哪块，所以“画在哪”和“亮在哪”由同一个值决定，
   不可能不一致。

验证：

```text
$ python tools/check-twrp-variants.py --make <ndk>/bin/make.exe
inner:  BIXI_IS_COVER=0  panel0  TW_INPUT_BLACKLIST="goodix_ts"  panel-inner.prop
cover:  BIXI_IS_COVER=1  panel1  TW_WHITELIST_INPUT="goodix_ts"  panel-cover.prop
ok   panel-inner.prop names DSI-1
ok   panel-cover.prop names DSI-2
ok   system.prop names no panel, so nothing competes
PASS: both variants build from one tree, differing only where they may
```

`bixi_cover_display_cleanup.c` 也用 `-Wall -Wextra -Werror` 编译过（Android NDK clang，C11）。
CI 的 `twrp` job 每一步都会重跑这两项，外加 0001 的 `g++ -fsyntax-only`。

⚠️ 仍然**没有**全量 TWRP 构建：没有 AOSP 树。所以“补丁贴得上、两个变体变量解析正确、
C 程序能编译”之外，链接与真机行为未验证。外屏版 TWRP 的完整刷机序列见
[VARIANTS.md](VARIANTS.md)。

---

## 4. 验证矩阵

| 项 | 状态 | 怎么验的 |
|---|---|---|
| skyward 改动编译（Android 目标） | ✅ | `cargo clippy -p skyward -p skyward-ui -p skyward-config --target aarch64-linux-android -- -D warnings` |
| skyward 整个 workspace（Linux） | ✅ | CI：`cargo clippy --workspace --all-targets -D warnings` + `cargo test --workspace` 全绿 |
| skyward-config 测试 | ✅ | Linux CI 全绿；本机 Windows 是 16 passed / 15 failed（基线 9/15，失败同为 `Path::is_absolute()` 的路径语义） |
| 两份 bixi 配置解析 | ✅ | 0005 的三个测试 + `skyward-pack` 启动时 `DeviceConfig::load` |
| 两个变体只差规定键 | ✅ | `ci/check-variants.py` |
| 外屏 1208×1392 的排版 | ✅ | CI 的 `skyward-preview --device bixi-cover` 把全部页面渲染成 PNG；第一次跑抓到 `70-erase` 的 crop abort，由 0006 修掉 |
| 补丁在干净树上应用 | ✅ | CI 每次从 `manifest.toml` 的 commit 重新 clone 再 apply |
| TWRP `graphics_drm.cpp` 语法编译 | ✅ | g++ `-fsyntax-only` + 真 TWRP 16 源码 + 桩头文件 |
| TWRP 两个变体的 make 变量 | ✅ | `tools/check-twrp-variants.py`，用真 make 展开 `BoardConfig.mk` |
| TWRP 显示程序编译 | ✅ | Android NDK clang，`-Wall -Wextra -Werror`，C11 |
| TWRP 完整编译进 recovery.img | ❌ | 需要 AOSP 树；见 [CI.md](CI.md) 的全量构建路线 |
| skyward 镜像打包 | ⚠️ 机制已验证 / CI 未跑 | 本机 Windows 用真实原厂 `recovery.img` + 临时配置跑通 packer（104857600 字节、`AVBf`、991 entries）；CI 的 `image` job 仍需 `STOCK_BIXI_URL` |
| 默认 adb / root（镜像层） | ✅ | `tools/check-recovery-adb.py` 对烟测镜像 PASS：adbd 在、`ro.*` 最后一行 0/0/1、init 以 root 起 adbd |
| 默认 adb / root（真机） | ❌ | 需上机 `adb devices` / `adb shell id` 确认 |
| DRM 提交/点亮/触摸/背光真机行为 | ❌ | 没有真机回灌；只能按 [VARIANTS.md](VARIANTS.md) 的顺序上机验 |
| `panel0/panel1` 背光归属 | ⚠️ 推定 | 从 DT 推的，必须上机 `echo` 一次确认 |
| `goodix` / `synaptics` 的 evdev 名字 | ⚠️ 推定 | TWRP 的 `TW_INPUT_BLACKLIST="goodix_ts"` 证明 Goodix 侧；用子串匹配降低拼写风险 |

---

## 5. 补丁怎么重新生成

补丁不是手写的，是 `git diff` 出来的。改完代码后：

```bash
# skyward：基线 c9deaf0，各 commit 依次对应 0003–0007
git -C .work/skyward diff c9deaf0 <commit-0003> > patches/0003-skyward-draw-on-a-named-panel.patch
git -C .work/skyward diff <commit-0003> <commit-0004> > patches/0004-skyward-read-the-chosen-panels-touch.patch
git -C .work/skyward diff <commit-0004> <commit-0005> -- . ':(exclude)devices' > patches/0005-skyward-bixi-device-tests.patch
git -C .work/skyward diff <commit-0005> <commit-0006> > patches/0006-skyward-keep-a-held-row-inside-the-band.patch
git -C .work/skyward diff <commit-0006> <commit-0007> > patches/0007-skyward-pack-take-the-stock-adb-properties-out.patch

# TWRP
git -C .work/recovery diff > patches/0001-twrpminui-name-the-panel-on-foldables.patch
```

生成后**必须**在干净树上 `git apply --check`，再跑一次 CI 的 clippy 和语法编译。
`devices/` 永远不进补丁：设备配置属于这个仓库，不属于上游。
