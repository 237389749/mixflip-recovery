# 在 MIX Flip 外屏跑 Skyward recovery —— 可行性、改动与验证

> 过程记录。最新改动见 [docs/CHANGES.md](docs/CHANGES.md)：补丁已拆成 0003/0004/0005，
> `devices/bixi.toml` 移出补丁，且新增了触摸选择与另一块屏关背光。

> 承接上一份《外屏recovery可行性与方案.md》。你实测 bixi / ruyi 的 TWRP
> 外屏都不出图，这与那份分析的诊断一致（都是"取第一个 DSI 连接器"）。
> 这份文档转到 skyward 路线：它比 TWRP 好改得多，而且**排版可以不用真机验证**。

---

## 一、先说结论

| 问题 | 答案 |
|---|---|
| skyward 能在外屏出图吗？ | **能**，核心改动是把 `KmsSurface::open` 的"取第一个面板"改成"按配置选面板" |
| 和 TWRP 比，难度如何？ | **明显更低**。TWRP 要改 `twrpminui` 的 DRM 后端；skyward 只改一个函数 + 加一对配置项 |
| 外屏排版能不能不真机验证？ | **能**。`skyward-preview` 在电脑上把页面渲染成 PNG，尺寸/密度都来自设备配置 |
| 有没有比 TWRP 更麻烦的地方？ | **有**：背光。skyward 默认点 `panel0-backlight`，那是内屏 |
| bixi 还有什么坑？ | 它的内核是 mainline 风格的 msm 驱动，**没有 `dsi_display0` 模块参数**，现有 `normal_max()` 会直接失败 |

---

## 二、两个翻转设备和它们的两个面板

从原厂 `dtbo.img` 解出来的（方法和上一份文档一致）：

| | 内屏 | 外屏 |
|---|---|---|
| 面板节点 | `qcom,mdss_dsi_o8_42_02_0a_prim_dsc_cmd` | `qcom,mdss_dsi_o8_42_02_0a_sec_dsc_cmd` |
| 分辨率 | 1224 × 2912 | **1208 × 1392** |
| 刷新档位 | 120/90/60/40/30/24 | 120 / 60 |
| DSC | 2 LM，612×32，8bpp | 2 LM，604×12，8bpp |
| 触摸 IC | `synaptics_tcm2` | `goodix_core` |
| DSI 连接器 | DSI-1 | DSI-2 |
| 背光节点 | `panel0-backlight`（推定） | `panel1-backlight`（推定） |

**两块屏用不同的触摸 IC**，这一点从 DT 的 `panel` phandle 反解出来是确定的
（`synaptics_tcm@0`→0x122→prim，`goodix_berlin@0`→0x123→sec）。

两个"推定"是同一件事：`panel0/panel1` 到底哪个是内屏，**必须上机确认**，
见 §六 的第 1 步。原厂 kernel 里搜不到这两个字符串（它们是 DTB 的 label 拼的），
本地无法静态坐实。

---

## 三、skyward 为什么更好改

skyward 的 `KmsSurface::open()` 只做一条：

```rust
for &h in res.connectors() {
    let info = card.get_connector(h, true)?;
    if is_panel(info.interface()) && info.state() == Connected {
        panel = Some(info);
        break;                    // ← 第一个连上的内置面板
    }
}
```

和 TWRP 同样的病，但**没有第二处**。而且 `drm` crate 0.15 提供了
`connector::Info::interface_id()`，这比 TWRP 里靠 connector id 猜要精确得多。

更关键的一点：**`display.width/height` 只被 `skyward-preview` 用**，
真机 UI 尺寸来自实际 DRM 模式。这意味着改配置就能在电脑上渲染出
"外屏 1208×1392 长什么样"，**一个真机都不用碰**。

---

## 四、改动清单

补丁在 `patches/0003-skyward-draw-on-a-named-panel.patch`，基准是 skyward
`v0.1.2` 的 `devices/` 那套（21 个设备配置）。

### 4.1 `[display] panel` —— 选屏

```toml
[display]
panel = "1208x1392"     # 或者 "DSI-2"
```

两种写法都支持：

| 写法 | 含义 | 适用 |
|---|---|---|
| `DSI-2` | 连接器序号（= `/sys/class/drm/card0-DSI-2`） | 知道接线时最精确 |
| `1208x1392` | 面板原生分辨率 | 不依赖接线，换固件也不会错 |

**不写 → 完全退回现在的行为**（取第一个 connected），所以对现有 21 个设备零影响。

实现上拆成两个纯函数，`Wanted::parse` 和 `Wanted::matches`，都不碰 DRM，
因此**能在电脑上跑单元测试**（见 §五）。

### 4.2 `[display] backlight` —— 背光

```toml
backlight = "panel1-backlight"
```

这条比想象中重要：skyward 原本固定找 `panel0-backlight`，那是**内屏**的。
如果只改选屏不改背光，结果是"recovery 画在外屏上，但点亮的还是内屏"——
表现就是外屏全黑，而日志里一切正常。

### 4.3 `normal_max()` 的容错

原实现硬依赖 `/sys/module/msm_drm/parameters/dsi_display0`。我查了 bixi 的内核
（`MiCode/Xiaomi_Kernel_OpenSource` 的 `bixi-v-oss` 分支）：

```
drivers/gpu/drm/msm/msm_drv.c:  module_param(vram|dumpstate|modeset, ...)
```

**没有 `dsi_display0`**。它用的是 mainline 风格的 msm/dsi 驱动
（`dsi_cfg.c` 而非高通的 `dsi_display.c`）。也就是说原代码在 bixi 上会
直接 `?` 失败，UI 起不来。

改成：拿不到这个参数就认为 `max_brightness` 本身就是正常上限。
这不影响 13 Ultra / 17 Ultra（它们有这个参数，走原路径），但让 bixi 能用。

### 4.4 `resonance()` 的单位容错

高通 `qcom-hv-haptics` 的 `lra_frequency_hz_show` 输出是 **整数 Hz + " Hz"**：

```c
cl_f_lra = USEC_PER_SEC * 10 / chip->config.cl_t_lra_us;
return scnprintf(buf, PAGE_SIZE, "%d Hz\n", cl_f_lra);
```

而 skyward 原来按"裸数字、十分之一 Hz"解析（17 Ultra 的驱动是那样）。
bixi 的振动器正是 `qcom,hv-haptics`，所以会算出 172.4 → 17.24 Hz 这种荒谬值。

改成看有没有 `Hz` 尾巴来判单位，裸数字仍按十分之一（向后兼容）。

### 4.5 `skyward-preview` 支持 `--device`

```bash
cargo run --release -p skyward-preview -- target/preview --device bixi --lang zh-CN
```

原来是硬编码 `devices/nezha.toml`。

---

## 五、能验证到什么程度（本地已跑）

我在本机装了 Rust 工具链 + MSVC Build Tools + Windows SDK + Android NDK r27c，
把改动**真正编译了一遍**。

### 5.1 编译验证（Android 目标 = 真机目标）

```
cargo clippy -p skyward -p skyward-ui -p skyward-config \
    --target aarch64-linux-android -- -D warnings
    Finished `dev` profile
```

**零 warning、零 error，正是 skyward CI 的第一道关卡。** 覆盖了我改的全部
四个文件（`surface.rs` / `ui.rs` / `haptics.rs` / `config/lib.rs`）。

这一步抓到一个真 bug：`Mode::size()` 返回 `(u16, u16)`，我最初按 `(u32, u32)`
写，**编译不过**。这就是为什么要真的编译而不是"看一遍觉得对"：

```rust
error[E0271]: expected `{closure}` to return `(u32, u32)`, but it returns `(u16, u16)`
```

### 5.2 单元测试

`skyward-config`：

```
test result: FAILED. 13 passed; 15 failed; 0 ignored
```

对比基线（未改动的 skyward）：

```
test result: FAILED.  9 passed; 15 failed; 0 ignored
```

**通过数 +4，失败数完全不变。** 那 15 个失败是 Windows 的路径语义
（`Path::is_absolute()` 不认 `/data/...`），与本次改动无关，Linux CI 上不会出现。
新增的 4 个测试各自单独跑都过：

```
test tests::a_display_names_the_panel_it_draws_on ... ok
test tests::a_panel_named_is_rejected_unless_the_recovery_can_act_on_it ... ok
test tests::bixi_draws_on_its_cover_panel ... ok
test tests::bixi_names_every_program_its_bring_up_needs ... ok
```

`skyward-ui` 的测试**跑不了**：它的测试二进制要链接 `skyward-net`，
而那些 crate 是 unix-only。所以我把 `Wanted` 的解析/匹配逻辑
原样抽出来单独编译运行，17 条断言全过：

```
ok   DSI-2 parses
ok   1208x1392 parses
ok   "dsi-2" names no panel
ok   1208*1392 names no panel
ok   the cover panel is DSI-2
ok   the inner panel is DSI-1
ok   not every connector 2 is a panel
ok   a size matches any mode of that size
ok   a panel reporting nothing matches nothing
all passed
```

这验证的是**纯逻辑**，不是 DRM 交互。

### 5.3 补丁可用性

```
git apply --check 0003-skyward-draw-on-a-named-panel.patch   → clean
应用后重新 clippy --target aarch64-linux-android -- -D warnings → Finished
```

### 5.4 完全没验证的

- DRM 提交路径（选中的 connector 能不能真的点亮）
- `goodix_core.ko` 在 recovery 下能否 probe
- `[display] backlight` 的节点名是不是 `panel1-backlight`
- `skyward-preview` 的渲染结果——**这个工具在 Windows 上编译不了**
  （依赖 unix-only 的 `skyward-net`），要 Linux/macOS 才能跑，见 §七

---

## 六、上机验证顺序

```bash
# 1. 先确认两件事：哪个 connector 是哪块屏，哪个背光是哪块屏
adb shell 'for d in /sys/class/drm/card0-DSI-*; do echo "== $d"; cat $d/status; head -1 $d/modes; done'
adb shell 'ls /sys/class/backlight/'
adb shell 'cat /sys/class/backlight/*/max_brightness'
```

期望：DSI-1 = `1224x2912`，DSI-2 = `1208x1392`。

判断 `panel0/panel1` 归属的可靠办法：**点亮其中一个，看哪块屏亮**。

```bash
adb shell 'echo 100 > /sys/class/backlight/panel1-backlight/brightness'
```

如果亮的是外屏 → `panel1` 是外屏，配置里 `backlight = "panel1-backlight"` 正确。
反之改成 `panel0-backlight`。

```bash
# 2. 选屏是否生效：日志里应该有选中的面板
adb shell 'logcat -d | grep -E "display |no connected panel is"'

# 3. 触摸
adb shell 'cat /proc/bus/input/devices | grep -A2 -iE "goodix|synaptics"'

# 4. 背光没有被 normal_max 卡住
adb shell 'logcat -d | grep -iE "backlight|no backlight"'
```

---

## 七、先在电脑上看排版（推荐的第一步）

这条能省掉一次刷机，**但要在 Linux 或 macOS 上跑**：

```bash
cargo run --release -p skyward-preview -- target/preview --device bixi --lang zh-CN
```

> ⚠️ 我在 Windows 上试过，编译不过：`skyward-preview` 依赖 `skyward-net` 和
> `skyward-install`，它们用 `std::os::unix`、`rustix::fs`、`UnixAddr` 等
> unix-only 接口。这不是我改出来的问题，是这两个 crate 本来就只能在 unix 上编译。
> 所以这条路需要 WSL / 一台 Linux 机器 / 或者直接在 CI 里跑。

如果嫌麻烦，也可以直接用 GitHub Actions 跑一次 `--device bixi`，
把 PNG 当 artifact 取下来。

它会按 `bixi.toml` 的 `width/height/density`（1208×1392 @ 440）把每一页渲染成 PNG。
如果首页就挤得不能用，先调 `density`，不用上机。

密度怎么选：外屏 1208 px 宽，`dp = px / (density/160)`。

| density | 横向 dp | 说明 |
|---|---|---|
| 520（原厂） | 372 | 原厂值，为 1224×2912 调的，放到近方形屏上偏大 |
| 460 | 420 | |
| **440（当前配置）** | **440** | 折中，行宽能放下 |
| 400 | 483 | 字更小，信息更多 |

1208×1392 接近方形，和 1224×2912 的长条完全不同，**排版一定要重新看**。

---

## 八、还需要你补的东西

### 8.1 `[stock]` 段（CI 需要）

skyward 的镜像构建流程是"下载原厂完整包 → 抠出 recovery 分区 → 替换
`/system/bin/recovery` → 重新打包"，所以 `devices/bixi.toml` 需要一个可验证的
`[stock]`：

```toml
[stock]
version = "OS3.0.304.0.WOHCNXM"
package = "https://.../bixi-ota_full-OS3.0.304.0.WOHCNXM-user-16.0-<hash>.zip"
recovery = "<recovery.img 的 sha256>"
```

- `recovery` 我能给你：工作区里那张 `recovery.img` 的 sha256 是
  `bc32c5fa4f4396fd52a4c65d03ea84bb147609812194da4eecf12723e5fafcd9`
  （但**这是 OS3.0.304.0.WOHCNXM**，和你 CI 里要写的版本必须一致）
- `package` 的 URL 我**没能确认**：小米的 OTA 服务器需要它自己的查询接口，
  我试了几个历史端点都是 404。这一段留空，等你从官方下载页拿到完整包地址。

**在补上 `[stock]` 之前，CI 的 `devices` 矩阵会因为 `stock` 缺失而失败**，
所以要么先补齐，要么临时把 bixi 从发布矩阵里排除、只做本地构建。

### 8.2 ruyi（FLIP1）

ruyi 是另一代（sm8650 / MIX Flip 1），可以照 bixi 的样子再写一份 `ruyi.toml`。
但 ruyi 的面板参数我没有从本机镜像里取过（工作区只有 bixi 的原厂包），
需要你提供 ruyi 的 `dtbo.img`，或者上机 dump：

```bash
adb shell 'for d in /sys/class/drm/card0-DSI-*; do echo "== $d"; cat $d/status; head -1 $d/modes; done'
```

---

## 九、和 TWRP 那份方案的关系

两份文档不冲突，解决的是同一个根因（"取第一个 DSI 连接器"）在两个代码库里的表现：

| | TWRP 16 | skyward |
|---|---|---|
| 选屏代码位置 | `twrpminui/graphics_drm.cpp` `find_main_monitor()` | `skyward-ui/surface.rs` `KmsSurface::open()` |
| 改动量 | 加一个函数 + 改一处循环（~70 行） | 加一个 enum + 拆两个纯函数（~50 行） |
| 背光 | `TW_BRIGHTNESS_PATH` 是编译期常量，改设备树即可 | 需要加配置项（已加） |
| 双屏同显 | 不支持（后端单 CRTC） | 不支持（单 CRTC） |
| 无真机验证 | 只能按密度推算，没有渲染器 | **有 preview，能直接出 PNG**（需 Linux/macOS） |
| 我编译验证过 | 否（无 AOSP 源码树） | **是**（clippy `-D warnings` 通过） |
| 构建方式 | 全量 AOSP 编译（~100 GB、数小时） | 增量交叉编译（分钟级）+ CI 出镜像 |

**skyward 明显更容易验证**：它的镜像是在原厂 recovery 上"换掉一个程序"，
不是从零编一个 recovery，所以本地能编译、能跑测试、能在 CI 上一次出图。

如果最后要用 skyward，TWRP 那份补丁可以不落地，但里面关于
"`bixi_cover_display_cleanup` 会关掉外屏电源"的坑**一样适用**——
skyward 不用那个程序，但同样的道理：**别让任何东西在 recovery 起来之后
再把外屏的 VCI 关掉**。

---

## 十、诚实的边界

- **编译层面是真的过了**：`skyward` / `skyward-ui` / `skyward-config` 在
  `aarch64-linux-android` 上 clippy `-D warnings` 零告警，并抓到过一个真实的
  `(u16,u16)` vs `(u32,u32)` 类型错误。补丁在干净树上 `git apply` 后重编也通过。
- **逻辑层面部分验证**：配置解析 4 个新测试通过；`Wanted` 的 17 条断言
  单独跑通过。但 `skyward-ui` 自己的测试二进制在 Windows 上编不出来。
- **运行时全部未验证**：DRM 提交、触摸、背光写入只在真机成立。
- `panel0/panel1` 的归属是**推定**，必须按 §六 第 1 步确认。
- `goodix_core` 在 recovery 环境能不能 probe，我没有任何证据，只能上机看 `dmesg`。
- 我改了 `normal_max()` 和 `resonance()` 的容错，这是**为了 bixi 顺手修的**，
  逻辑上对 13 Ultra / 17 Ultra 等价，但没在那些机器上回归过。
  如果要往上游提，建议拆成独立 commit：
  1. `[display] panel` + 选屏（核心）
  2. `[display] backlight`
  3. `normal_max()` 容错
  4. `resonance()` 单位容错
- `[stock]` 段我补不上（见 §8.1），**没有它 CI 出不了 bixi 的镜像**。
