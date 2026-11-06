# 两个版本：怎么选、怎么出、刷错会怎样

## 1. 选哪个

| 你的机器 | 刷哪个 |
|---|---|
| 内屏正常，recovery 只想在内屏用 | `bixi`（内屏版） |
| 内屏坏了 / 拆了 / 排线断了，只看外屏 | `bixi-cover`（单外屏版） |
| 内屏还在，但你想在外屏用 recovery（合盖操作） | `bixi-cover`，先读 §4 |

单外屏版**不会**因为“检测到内屏”就自动切回内屏。它是显式按面板原生分辨率 `1208x1392` 选连接器的。

## 2. 怎么出

### 2.1 CI（推荐）

推一个 tag（或手动 `workflow_dispatch`），`build` workflow 会为两个变体各出一个 zip：

```
skyward-<version>-bixi-OS3.0.304.0.WOHCNXM.zip
skyward-<version>-bixi-cover-OS3.0.304.0.WOHCNXM.zip
```

CI 需要原厂 `recovery.img` 的下载地址（变量 `STOCK_BIXI_URL`），设置方法见 [CI.md](CI.md)。
没有设置时，CI 仍会编译两个变体的二进制、跑测试、渲染预览 PNG，只是不打包镜像。

### 2.2 本地

见 [README](../README.md) 的“快速开始”。打包镜像这一步在 Windows 上做不了：
`skyward-pack recovery` 会调用 `DeviceConfig::load`，而它用 `Path::is_absolute()` 判断
Android 的 `/data/...`，Windows 语义下会失败。**这一条只能 Linux/CI 做。**

### 2.3 TWRP 侧的两个变体

TWRP 是另一条路线（见 [CHANGES.md](CHANGES.md) §3）。同一棵设备树出两个版本，只差一个
make 变量：

```bash
# 内屏版（默认，行为和现在一样）
lunch twrp_bixi-bp2a-eng && m recoveryimage

# 单外屏版
lunch twrp_bixi-bp2a-eng && BIXI_COVER_SCREEN=1 m recoveryimage
```

两者差三处：`TW_BRIGHTNESS_PATH`、`TW_WHITELIST_INPUT`/`TW_INPUT_BLACKLIST`、
以及装进镜像的 `panel-cover.prop`/`panel-inner.prop`（各写一个 `twrp.drm.connector`）。
背光点亮由 `bixi-cover-display-cleanup` 按这个属性决定，所以“画在哪”和“亮在哪”永远一致。

校验（不需要 AOSP 树）：

```bash
python tools/check-twrp-variants.py <设备树路径>
```

⚠️ TWRP 全量构建仍需 AOSP 树，本仓库没有验证过链接和真机行为。skyward 是更稳的那条路。

## 3. 刷

```bash
# 内屏版
fastboot flash recovery skyward-...-bixi-OS3.0.304.0.WOHCNXM.img
# 单外屏版
fastboot flash recovery skyward-...-bixi-cover-OS3.0.304.0.WOHCNXM.img
fastboot reboot recovery
```

回滚：同版本原厂 `recovery.img`（`manifest.toml` 里有 sha256）刷回去即可。recovery 分区
不碰 userdata。

> **刷之前，能 adb 就先确认背光归属**（原厂 recovery 或现在的 TWRP 都行）：
>
> ```bash
> adb shell 'echo 100 > /sys/class/backlight/panel1-backlight/brightness'
> ```
>
> 亮的是外屏 → `panel1` 是外屏，`bixi-cover` 的 `backlight` / `backlights_off` 正确；
> 亮的是内屏 → 两个变体的这两项都要对调，否则外屏版会“把要画的屏关掉、去点亮另一块”——黑屏。

## 4. 单外屏版刷在“内屏还在”的机器上，会怎样

先给结论：**能起、能画在外屏、不会 bootloop；但内屏不会自动熄灭到“断电”，触摸也只会走外屏。**
逐层说：

### 4.1 选屏：仍然选外屏，不会退回内屏

`panel = "1208x1392"` 是按面板原生分辨率匹配。内屏在不在都不影响匹配结果。

- 外屏正常 → 画在外屏；
- 外屏不在/驱动没起来 → 启动直接失败，日志里是
  `no connected panel is 1208x1392; the panels are [...]`，**不会**偷偷画到内屏。
  这是故意的：折机上“退回第一块屏”等于画到用户看不见的地方。

### 4.2 内屏：不亮，但也没断电

- 启动时 `backlights_off = ["panel0-backlight"]` 把内屏背光写 0，所以**看不见**；
- 但 recovery 只驱动一个 CRTC，内屏原来的 CRTC 没有被拆，bootloader 的连续开机画面还在上面 scanout。
  也就是说：面板仍然供电、仍然在刷新一张静态图，只是背光为 0。长时间用会多耗一点电，不会烧屏（OLED 黑画面不发光）；
- 如果你用的是没有 `backlights_off` 的旧构建，内屏会**亮着开机 logo**，外屏同时在跑 recovery —— 看起来像“两个系统”。

> 要彻底断电，得像 `bixi-cover-display-cleanup` 那样 `force_disable` 外屏/内屏的 VCI regulator。
> skyward 不跑那个程序；这是已知限制。

### 4.3 触摸：只加载、只读外屏那颗 Goodix

`[modules] load = ["goodix_core"]` + `[touch] device = "goodix"`，所以：

- 合盖状态摸外屏 → 正常；
- 展开状态摸内屏 → **没有反应**：内屏的 `synaptics_tcm2` 根本没加载，不是“加载了但不读”；
- 如果内核把 Goodix 的 evdev 名字拼成别的（不含 `goodix`），会回退到“第一个多点触摸设备”并打一行
  `no touch device is named "goodix"; taking /dev/input/eventX`。只有厂商栈额外把 Synaptics
  拉起来时，才可能选中内屏那颗，表现为“摸内屏控制外屏、摸外屏没反应”。**上机第一件事就是看这行日志。**

> 为什么不在两个版本里都加载两个驱动：驱动在面板不存在时可能 probe 失败，`finit_module` 返回错误，
> skyward 会把它当致命错误直接退出。单外屏机器上没有内屏，加载 Synaptics 是给自己埋雷。

### 4.4 不会 bootloop

`refMD` 里那个“拆了内屏就 bootloop”是 **framework 层**的问题（`device_state`、首帧布局、
`DisplayManager` 拿不到内屏）。recovery 没有 framework，不读折叠状态，也不等内屏，所以不受影响。
这也是为什么 recovery 这条路能绕开 ROM 的坑。

### 4.5 内屏真的拆了（不是坏了）

- 如果 DSI-1 变成 `Disconnected`：单外屏版照样按 `1208x1392` 选 DSI-2；
- 如果 DSI-1 还在、只是面板不亮（排线还连着）：单外屏版也不管它，照选 DSI-2；
- 内屏版（`bixi`）在这种情况下会启动失败，日志列出实际面板 —— 这是预期行为，不是 bug。

### 4.6 电量、发热、充电

recovery 的充电/电量显示不依赖另一块屏。内屏多亮一块会增加功耗；单外屏版本已经把它背光关掉，
剩下的是面板 scanout 的功耗，量级远小于亮屏。

## 5. 上机检查顺序

```bash
# 1. 选中的是哪块、分辨率对不对
adb shell 'logcat -d | grep -E "^display |no connected panel is"'
# 期望：DSI-2 ... 1208x1392 ...（单外屏版）

# 2. 哪块屏亮着
adb shell 'cat /sys/class/backlight/*/brightness'
# 期望：panel1 非 0，panel0 = 0

# 3. 触摸选中了谁
adb shell 'logcat -d | grep -E "^input |no touch device is named"'
# 期望：goodix_ts 被选中，没有 fallback 告警

# 4. 内屏是不是还在 scanout（可选）
adb shell 'cat /sys/class/drm/card0-DSI-1/status; cat /sys/class/drm/card0-DSI-1/modes | head -1'
```

## 6. 出问题怎么回

| 现象 | 先看 | 大概率原因 |
|---|---|---|
| 外屏黑，adb 正常 | 背光 `panel1` 是不是 0 | 背光路径没换 / init 把 panel1 写成 0 |
| 外屏亮但没画面 | `logcat` 里 `display` 行 | 选中的不是 DSI-2，或 DRM 提交失败 |
| 摸外屏没反应 | `input` 行 | 触摸选中了内屏那颗（fallback） |
| 摸内屏控制外屏 | 同上 | 正常现象（触摸没选对外屏） |
| 启动就退出/黑屏 | `no connected panel is` | `panel` 值与实际模式不符（换固件后分辨率变了） |
| 两块都亮 | `panel0` 亮度 | 旧构建没有 `backlights_off`，或内屏 VCI 没断 |
