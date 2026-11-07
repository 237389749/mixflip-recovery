# MIX Flip 外屏 recovery

小米 MIX Flip 2（bixi）的 recovery 显示在外屏/内屏的可复现改动集，以及两个成品版本的构建方法。

> 仓库：<https://github.com/237389749/mixflip-recovery>（已公开）。CI 全绿，**两个镜像已经在 Actions 的 artifact 里出过**；
> 原厂 `recovery.img` 放在 release [`stock-bixi`](https://github.com/237389749/mixflip-recovery/releases/tag/stock-bixi)。

> 结论一句话：**能，但改的不是 ROM，是 recovery 自己的 DRM 选屏代码。**
> fastboot 归 bootloader，仍然改不了；双屏同显也不支持。

## 这个仓库是什么

不是 ROM，不是内核，也不是设备树魔改。它是：

- `patches/` —— 对三个上游代码库的最小改动，全部可 `git apply`；
- `devices/` —— 两块屏各一份 skyward 设备配置（内屏版 / 单外屏版）；
- `.github/workflows/` —— 在 Linux 上跑编译、测试、渲染预览和出包，绕开 Windows 编不了 unix-only crate 的问题；
- `docs/CHANGES.md` —— **改动点记载**：每个改动在哪、为什么、影响哪个版本、验证到什么程度；
- `docs/VARIANTS.md` —— 两个版本怎么出、怎么刷、刷错会怎样；
- `tools/` —— 从原厂 `dtbo.img` 解面板/触摸/DSC 事实的脚本（换固件要重跑）。

## 两个版本

| | `bixi`（内屏版） | `bixi-cover`（单外屏版） |
|---|---|---|
| 画在哪 | 内屏 1224×2912 | 外屏 1208×1392 |
| 背光 | `panel0-backlight` | `panel1-backlight` |
| 另一块屏 | 背光关掉 | 背光关掉 |
| 触摸 | `synaptics`（只加载它） | `goodix`（只加载它） |
| 适用 | 正常机器 | 内屏坏了/拆了，只看外屏 |

两个版本只差 `[display]`、`[touch]` 和 `[modules] load` 里的几行，`ci/check-variants.py` 会强制检查“只差这些”，
防止两份配置各自漂移。

## 快速开始

```bash
# 1. 准备上游（首次）
git clone https://github.com/kirklin/skyward.git .work/skyward
git -C .work/skyward checkout c9deaf026eaf83fe2b9141dd656c256ddf42c8c1

# 2. 打补丁 + 放设备配置
for p in patches/000[3-7]-*.patch; do
  git -C .work/skyward apply "$PWD/$p"
done
cp devices/*.toml .work/skyward/devices/

# 3. 编译（需要 Rust + Android NDK + cargo-ndk；没有就让 CI 编）
cargo ndk -t arm64-v8a --platform 30 build --release -p skyward --manifest-path .work/skyward/Cargo.toml
```

不用本地环境也可以：推到 GitHub 后跑 `build` workflow，它会编出
`skyward-<sha>-bixi-OS3.0.304.0.WOHCNXM.zip` 和 `…-bixi-cover-….zip`，产物在 Actions 的 artifact 里。
出包要原厂 `recovery.img`：已在 release `stock-bixi` 里，并设成仓库变量 `STOCK_BIXI_URL`，见 [docs/CI.md](docs/CI.md)。

## 上游与基线

`manifest.toml` 记着每个补丁的基线 commit。补丁不跟随上游 `main`；升级时先改 `manifest.toml`，
再重新生成补丁，并重跑 `cargo clippy` 和 `cargo test`。

## 相关文档

- [docs/CHANGES.md](docs/CHANGES.md) —— 改动点记载（先看这个）
- [docs/VARIANTS.md](docs/VARIANTS.md) —— 两个版本与“插着内屏会怎样”
- [docs/ADB_AND_ROOT.md](docs/ADB_AND_ROOT.md) —— 默认 adb / root、为什么没有 su、怎么验
- [docs/METHOD.md](docs/METHOD.md) —— **可复现的思路**（同类问题怎么再走一遍）
- [docs/CI.md](docs/CI.md) —— CI 能做什么、不能做什么
- [docs/BOOTLOG.md](docs/BOOTLOG.md) —— **拔内屏卡开机时怎么抓内核日志**（pstore/ramoops，可行性已确认、未实机）
- [docs/UPSTREAM.md](docs/UPSTREAM.md) —— 哪些改动提 PR、哪些留本仓库
- [docs/VERIFICATION.md](docs/VERIFICATION.md) —— 哪些验证过、哪些没有
- [会话总结.md](会话总结.md)、[外屏recovery可行性与方案.md](外屏recovery可行性与方案.md)、[skyward外屏方案.md](skyward外屏方案.md) —— 过程记录

## 许可

补丁是 skyward（GPL-3.0）和 TWRP（GPL）的衍生改动，本仓库整体按 GPL-3.0 发布，
见 [LICENSE](LICENSE)。
