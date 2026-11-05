# 验证记录

> 记录的是**这次真的跑过什么、结果是什么**，不是“应该能行”。
> 环境：Windows 10/11，Rust 1.99.1（stable-x86_64-pc-windows-msvc），
> Android NDK r27c；Linux 侧未在本机跑（没有 WSL / Docker）。

## 1. 补丁在干净基线树上应用

```text
skyward @ c9deaf026eaf83fe2b9141dd656c256ddf42c8c1
  git apply patches/0003-…  → exit 0
  git apply patches/0004-…  → exit 0
  git apply patches/0005-…  → exit 0

bootable/recovery @ 8a58fc3b586b8a908337fa87529cfbbb119ec7bb
  git apply patches/0001-…  → exit 0

twrp_device_xiaomi_sm8750_bixi @ 9b4b445004006fc2ffbdfefbf7fc7e7758cf129a
  git apply --check patches/0002-…  → exit 0
```

补丁是 `git diff` 生成的，不是手写；上面的顺序就是 CI 的顺序。

## 2. skyward：Android 目标 clippy

在干净 clone + 三个补丁 + `devices/*.toml` 之后：

```bash
cargo clippy -p skyward -p skyward-ui -p skyward-config \
    --target aarch64-linux-android -- -D warnings
# Finished `dev` profile … exit 0
```

`skyward` 的测试模块也单独编译过：

```bash
cargo clippy -p skyward --tests --target aarch64-linux-android -- -D warnings
# Finished … exit 0
```

这覆盖了 0003/0004 改到的 `surface.rs`、`ui.rs`、`input.rs`、`haptics.rs`、`config/lib.rs`。
**只证明类型/借用/警告层面干净，不证明 DRM 行为。**

## 3. skyward-config 测试（Windows 本机）

```text
基线（未打补丁）：      9 passed; 15 failed
三个补丁 + 两份配置：  16 passed; 15 failed
```

失败数不变，通过数 9 → 16（净 +7）：原补丁的 4 个配置测试里，2 个通用测试留在 0003，
2 个 bixi 测试移到 0005；0004 新增 2 个，0005 新增 3 个（9 + 2 + 2 + 3）。那 15 个失败是
Windows 的路径语义：`Path::is_absolute()` 不认 `/data/...`，Linux 上不会出现。

单独跑新增的测试：

```text
tests::a_display_names_the_panel_it_draws_on ... ok
tests::a_panel_named_is_rejected_unless_the_recovery_can_act_on_it ... ok
tests::the_panels_not_drawn_on_can_be_told_to_stay_dark ... ok
tests::a_touch_device_is_named_by_part_of_its_name ... ok
tests::bixi_draws_on_the_inner_panel_by_default ... ok
tests::bixi_cover_draws_on_the_cover_panel ... ok
tests::bixi_names_every_program_its_bring_up_needs ... ok
```

⚠️ **没有在 Linux 上跑过完整 `cargo test --workspace`。** 这是 CI 第一次 push 要补的洞。

## 4. TWRP：语法编译（不是“只 apply 成功”）

用真实 TWRP 16 源码 + libdrm 头 + 两个桩头文件，**编译**打过 0001 的 `graphics_drm.cpp`：

```bash
clang++ --target=aarch64-linux-android30 \
  --sysroot=<ndk>/toolchains/llvm/prebuilt/windows-x86_64/sysroot \
  -std=gnu++17 -fsyntax-only -Wno-non-c-typedef-for-linkage \
  -I recovery/twrpminui/include -I recovery/twrpminui \
  -I recovery/libpixelflinger/include -I libdrm -I libdrm/include/drm -I ci/stubs \
  recovery/twrpminui/graphics_drm.cpp
# exit 0
```

CI 用 `g++ -fsyntax-only` 和 `libdrm-dev` 做同一件事。桩只有两个：
`android-base/properties.h`、`cutils/properties.h`，都只放声明。

这一步抓到的不是“补丁能不能贴”，而是：

- `PROPERTY_VALUE_MAX` / `property_get` 的声明和用法对；
- `drmModeConnector` / `drmModeRes` 的字段名对；
- `sscanf("DSI-%u")` 与 `connector_type_id` 的类型对；
- 顺手修了一个真 bug：`DSI-0` 的 `connector_type_id` 就是 0，旧写法把 0 当“没给名字”。

**仍然没证明**：链接进 `libtwrpminui` 后能不能跑、真机能不能点亮。那要全量 TWRP 构建。

## 5. 原厂镜像

```text
recovery.img  104857600 bytes
sha256 bc32c5fa4f4396fd52a4c65d03ea84bb147609812194da4eecf12723e5fafcd9

dtbo.img      18874368 bytes
sha256 f73e842640971a9c43517a3292fd233f408b7a8ceb2bda84b41b07fb8cae18f3
```

`recovery.img` 的 sha256 与 `manifest.toml`、以及之前文档里的值一致。

## 6. 变体一致性

```text
$ python3 ci/check-variants.py
ok  devices/bixi.toml and devices/bixi-cover.toml differ only in:
    [display] backlight: 'panel0-backlight' vs 'panel1-backlight'
    [display] backlights_off: ['panel1-backlight'] vs ['panel0-backlight']
    [display] corner_radius: '<unset>' vs 62
    [display] density: 520 vs 440
    [display] diagonal: 6.86 vs 4.01
    [display] height: 2912 vs 1392
    [display] panel: '1224x2912' vs '1208x1392'
    [display] width: 1224 vs 1208
    [touch] device: 'synaptics' vs 'goodix'
```

## 7. CI（GitHub Actions）

最终一次 run：<https://github.com/237389749/mixflip-recovery/actions/runs/42022057174> — **success**

| job | 结果 | 证明了什么 |
|---|---|---|
| Lint and test the patched skyward | ✅ | Linux 上 `cargo clippy --workspace --all-targets -D warnings`、`cargo test --workspace`、Android 目标 clippy、两个变体一致性 |
| Patch and compile-check twrpminui | ✅ | 0001 在真 TWRP 16 源码上 apply + `g++ -fsyntax-only`；0002 在设备树上 `git apply --check` |
| Preview bixi | ✅ | 内屏 1224×2912 的所有页面渲染成 PNG（约 39 MB） |
| Preview bixi-cover | ✅ | 外屏 1208×1392 的所有页面渲染成 PNG（约 29 MB） |
| Recovery image | ⏭️ skipped | 没有设置 `STOCK_BIXI_URL`，CI 没有原厂 `recovery.img` |

第一次跑抓到了三个真问题，都不是“读代码能看出来”的：

1. **`g++` 没有 bionic 的 `__unused`**：TWRP 源码里 `minui_backend* backend __unused` 在 glibc 下报
   “expected ',' before '__unused'”。CI 的编译命令加 `-D__unused=__attribute__((unused))` 后通过。
2. **`root.join(&format!(...))`**：host clippy 的 `needless_borrows_for_generic_args` 直接 `-D warnings` 失败，
   本地只跑 Android 目标时没覆盖到。改成 `root.join(format!(...))`。
3. **外屏尺寸上 `crop` 越界 abort**：`skyward-preview --device bixi-cover` 跑到 `70-erase` 页时
   `canvas.rs:424` 的 assert 失败、exit 134。原因是 `row_part` 只按整页尺寸裁，没考虑页面是分 band 画的。
   补丁 `0006` 修掉，并加了一个 band 裁切的测试。

这三点说明 CI 不只是“换台机器编译”，它实际覆盖了 Windows 编不了的 unix-only crate、只在 Linux 上跑的
测试、以及外屏尺寸才会触发的布局路径。

## 8. 完全没验证的（上机前必须知道）

| 项 | 为什么没验 | 怎么验 |
|---|---|---|
| 选中 DSI-2 后 DRM 能不能提交 | 没有真机回灌 | 刷入看 `display` 日志和实际画面 |
| 外屏背光节点是不是 `panel1-backlight` | 原厂 kernel 里搜不到，DTB label 拼的 | `echo 100 > .../panel1-backlight/brightness` 看哪块亮 |
| Goodix / Synaptics 的 evdev 名字 | 只有 TWRP 的 `goodix_ts` 是实证 | 刷入看 `input ... goodix=True` 行 |
| 内屏背光写 0 后是否真的黑 | 逻辑推断 | 上机看另一块屏 |
| 内屏 CRTC 是否仍在 scanout | 代码上只 detach 同 CRTC 的连接器 | `/sys/kernel/debug/dri/0/state` |
| `goodix_core.ko` 在 recovery 能否 probe | 没有任何证据 | `dmesg | grep -i goodix` |
| skyward 镜像打包 | Windows 上 `DeviceConfig::load` 路径语义失败 | CI 的 `image` job |
| TWRP 全量编译 | 没有 AOSP 树 | 设备树仓库的 builder + 两个 apply |

## 9. 诚实边界

- `0003/0004/0005` 在 **Android 目标**上 clippy 干净，配置测试在本机 16 通过；
- `0001` 在 **TWRP 16 真源码**上语法编译通过；
- `0002` 只做了 `git apply --check`；
- **没有任何一行在真机上跑过**；
- Linux 上的 `cargo test --workspace` 和 `skyward-preview` 出图，要等 CI 第一次运行。
