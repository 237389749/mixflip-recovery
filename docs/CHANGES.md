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

补丁：`0003`（选屏 + 背光 + 两处容错）、`0004`（触摸 + 另一块屏关背光）、`0005`（bixi 配置测试）。

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
- `0005` 加三个测试：两份配置的面板/背光/触摸/密度，以及 bixi 启动所需的服务清单。

---

## 3. TWRP 侧改动

补丁：`0001`（`bootable/recovery`）、`0002`（设备树）。

### T1 `twrpminui` 按名字选连接器

| | |
|---|---|
| 文件 | `twrpminui/graphics_drm.cpp` |
| 改动 | 新增 `find_connector_by_name()`；读 `twrp.drm.connector`，支持 `DSI-2` / `1208x1392`；未设置或匹配不到时保持原优先级回退 |
| 为什么 | `find_main_monitor()` 按 `{LVDS, eDP, DSI}` 类型优先级取第一个，两块都是 DSI |
| 验证 | 真实 TWRP 16 源码上 `git apply` + **`g++ -fsyntax-only` 通过**（CI 每次跑） |
| 修复 | `DSI-0` 是 `connector_type_id == 0`，旧写法把 0 当成“没给名字”，会匹配失败；已改为独立的 `by_type` |

编译验证只证明语法/头文件/类型正确，**不证明链接进 TWRP 后行为正确**，更不证明真机点亮。

### T2 设备树配合

| 文件 | 改动 | 为什么 |
|---|---|---|
| `Android.bp` | `bixi-cover-display-cleanup` 加 `libcutils` | 用 `property_get` 读选屏属性 |
| `display/bixi_cover_display_cleanup.c` | 按属性判断 recovery 是否画在外屏；是则改为清理**内屏**的 CRTC，并**不** `force_disable` 外屏 VCI | 原程序专为“外屏不显示”设计，会把你要用的那块屏断电 |
| `recovery/root/init.recovery.qcom.rc` | 追加 `insmod goodix_core.ko` | 外屏触摸是 Goodix；原来只加载内屏的 Synaptics |
| `system.prop` | `twrp.drm.connector=DSI-1` | 默认仍是内屏，行为不变 |

⚠️ **TWRP 的“单外屏版”目前不完整，不要直接刷**。还差三处（未实现）：

1. `BoardConfig.mk`：`TW_BRIGHTNESS_PATH` 从 `panel0-backlight` 改成 `panel1-backlight`；
2. `init.recovery.qcom.rc`：`panel0=200 / panel1=0` 反过来（否则外屏被 init 写成 0，TWRP 又去写内屏背光 → 外屏黑）；
3. `TW_INPUT_BLACKLIST`：现在拉黑 `goodix_ts`（外屏触摸），外屏版要反过来拉黑 Synaptics。

这三处不改，就是经典的“recovery 起来了、adb 正常、日志正常、就是黑屏”。

---

## 4. 验证矩阵

| 项 | 状态 | 怎么验的 |
|---|---|---|
| skyward 改动编译（Android 目标） | ✅ | `cargo clippy -p skyward -p skyward-ui -p skyward-config --target aarch64-linux-android -- -D warnings` |
| skyward-config 测试 | ⚠️ 未在 Linux 跑过 | 本机 Windows：16 passed / 15 failed（基线 9/15；那 15 个是 `Path::is_absolute()` 不认 `/data`，与改动无关）。Linux 全绿要等 CI 第一次跑 |
| 两份 bixi 配置解析 | ✅ | 0005 的三个测试 + `skyward-pack` 启动时 `DeviceConfig::load` |
| 两个变体只差规定键 | ✅ | `ci/check-variants.py` |
| 补丁在干净树上应用 | ✅ | CI 每次从 `manifest.toml` 的 commit 重新 clone 再 apply |
| TWRP `graphics_drm.cpp` 语法编译 | ✅ | g++ `-fsyntax-only` + 真 TWRP 16 源码 + 桩头文件 |
| TWRP 完整编译进 recovery.img | ❌ | 需要 AOSP 树；见 [CI.md](CI.md) 的全量构建路线 |
| DRM 提交/点亮/触摸/背光真机行为 | ❌ | 没有真机回灌；只能按 [VARIANTS.md](VARIANTS.md) 的顺序上机验 |
| `panel0/panel1` 背光归属 | ⚠️ 推定 | 从 DT 推的，必须上机 `echo` 一次确认 |
| `goodix` / `synaptics` 的 evdev 名字 | ⚠️ 推定 | TWRP 的 `TW_INPUT_BLACKLIST="goodix_ts"` 证明 Goodix 侧；用子串匹配降低拼写风险 |

---

## 5. 补丁怎么重新生成

补丁不是手写的，是 `git diff` 出来的。改完代码后：

```bash
# skyward：基线 c9deaf0，三个 commit 分别对应 0003/0004/0005
git -C .work/skyward diff c9deaf0 <commit-0003> > patches/0003-skyward-draw-on-a-named-panel.patch
git -C .work/skyward diff <commit-0003> <commit-0004> > patches/0004-skyward-read-the-chosen-panels-touch.patch
git -C .work/skyward diff <commit-0004> <commit-0005> -- . ':(exclude)devices' > patches/0005-skyward-bixi-device-tests.patch

# TWRP
git -C .work/recovery diff > patches/0001-twrpminui-name-the-panel-on-foldables.patch
```

生成后**必须**在干净树上 `git apply --check`，再跑一次 CI 的 clippy 和语法编译。
`devices/` 永远不进补丁：设备配置属于这个仓库，不属于上游。
