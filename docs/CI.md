# CI：它替我们解决了什么，不解决什么

当前状态：**全绿，6 个 job 全过，含出包**，
run：<https://github.com/237389749/mixflip-recovery/actions/runs/42220039542>（2026-11-06，`cb8fcc4`）。

本地是 Windows：`skyward-preview`、`skyward-install`、`skyward-net` 这些 crate 依赖
`std::os::unix` / `rustix` / `UnixAddr`，**在 Windows 上编不出来**；TWRP 更不可能在 Windows 上全量编。
CI 就是用来补这两个洞的。

## 1. 每次 push 跑什么

`.github/workflows/ci.yml`：

| job | 做什么 | 用时 |
|---|---|---|
| `skyward` | 按 `manifest.toml` 的 commit 克隆 skyward → 打 0003–0007 → 放 `devices/*.toml` → `cargo clippy --workspace --all-targets -D warnings` + `cargo test --workspace` + Android 目标 clippy + `ci/check-variants.py` | 约 10 分钟（冷缓存） |
| `preview` | 两个变体各跑一次 `skyward-preview --device bixi` / `--device bixi-cover`，把 PNG 当 artifact | 几分钟 |
| `twrp` | 克隆 TWRP 16 的 `bootable/recovery` → 打 0001 → **`g++ -fsyntax-only` 编译 `graphics_drm.cpp`**；克隆设备树 → 打 0002 + 0002b → `check-twrp-variants.py` 用真 make 验两个变体 → 编译显示程序 | 两三分钟 |
| `image` | 下载原厂 `recovery.img`、校验 sha256、`skyward-pack recovery` 出两个变体的 img、**核验镜像里装的是本变体的配置**、跑 `check-recovery-adb.py`、zip 成 artifact（两个变体各一个） | 约 3 分钟（含 100 MiB 下载） |

`skyward`、`preview`、`twrp`、`image` 每次 push 都跑；`image` 的唯一前提是 `STOCK_BIXI_URL` 存在（现在就存在）。

## 2. 让 CI 能出镜像：`STOCK_BIXI_URL`（已设好）

`skyward-pack recovery` 需要原厂 `recovery.img`（整分区，100 MiB，结尾带 AVB footer）。
GitHub 的 runner 拿不到本机文件，所以这个文件放在**本仓库的 release** 里：

```text
release  stock-bixi
asset    OS3.0.304.0.WOHCNXM-recovery.img   104857600 bytes
sha256   bc32c5fa4f4396fd52a4c65d03ea84bb147609812194da4eecf12723e5fafcd9
直链     https://github.com/237389749/mixflip-recovery/releases/download/stock-bixi/OS3.0.304.0.WOHCNXM-recovery.img
```

仓库 **Settings → Secrets and variables → Actions → Variables** 里的 `STOCK_BIXI_URL` 就是上面这条直链。
`image` job 用 `curl -fL` 取它，再拿 `manifest.toml` 的 `[stock] sha256` 校验，**校验不过直接失败**，
不会拿错版本的镜像出包。

**硬前提：仓库必须是公开的。** 私有仓库的 release asset 对匿名请求返回 404，
`curl` 没有凭据就取不到 —— `image` job 会死在第一步，跟 URL 抄得对不对无关。
这条是 2026-11-06 把仓库从私有转公开的直接原因。如果以后要转回私有，
把下载换成 `gh release download stock-bixi --pattern recovery.img` 并给 `GH_TOKEN: ${{ github.token }}`，
那样就不需要公开仓库了。

换固件时三件事缺一不可，缺哪件 CI 都会在 sha256 上失败：

1. 新 release（或同一个 release 里新 asset）上传新的 `recovery.img`；
2. 改 `manifest.toml` 的 `[stock] version / file / size / sha256`；
3. 改 `STOCK_BIXI_URL` 指向新 asset。

> 为什么不让 `skyward-pack stock` 去小米 OTA 下载：那个子命令只认"完整 OTA 包里的 payload.bin"，
> 而手上的原厂包是 **fastboot 线刷包**（`recovery.img` 已经解开）。用 release asset 直接喂 `recovery.img`
> 更短、更可控，也避开了小米 OTA 的查询接口。

## 3. TWRP 全量编译（不在本仓库 CI 里跑）

`g++ -fsyntax-only` 只能证明补丁的 C++ 语法/类型/头文件没问题。要证明能链进 recovery 并跑起来，
必须全量 AOSP。**设备树仓库已经自带这个 workflow**：`twrp_device_xiaomi_sm8750_bixi/.github/workflows/build.yml`
（TWRP 16，`TWRP-Test/platform_manifest_twrp_aosp`，`maximize-build-space` + ccache，约 1–2 小时）。

接我们的补丁只需要在它的流程里插两步：

```yaml
# 在 “Setup device” 之后、 “Build TWRP” 之前
- name: Apply the cover-panel patches
  run: |
    git -C bootable/recovery apply "$GITHUB_WORKSPACE/patches/0001-twrpminui-name-the-panel-on-foldables.patch"
    git -C device/xiaomi/bixi apply "$GITHUB_WORKSPACE/patches/0002-bixi-let-the-recovery-choose-its-panel.patch"
```

注意：

- `Setup device` 是 `git clone <DEVICE_TREE_URL>` 到 `device/xiaomi/bixi`，所以 0002 要打在那个
  分支上；把 `DEVICE_TREE_URL/BRANCH` 指向你自己的 fork 也行；
- 设备树分支用 `twrp-16.0-kernel6.6.139`（`manifest.toml` 的 `9b4b445`），workflow 默认的
  `twrp-16.0` 可能不是同一个 commit；
- 这条路线只出**内屏版**。外屏版还要改 `BoardConfig.mk` / `init.recovery.qcom.rc` /
  `TW_INPUT_BLACKLIST` 三处（见 [CHANGES.md](CHANGES.md) §3 T2），改完再编。

## 4. 为什么补丁要按 commit 钉死

`patches/` 是 `git diff`，带上下文行号。上游一改，补丁就可能 apply 失败。
所以 `manifest.toml` 钉 commit，CI 每次都从那个 commit 重新 clone 再 apply；
升级上游时先改 `manifest.toml`，再重新生成补丁，再跑 CI。不要用 `main` 的最新 HEAD 当基线。

## 5. 缓存与耗时

- `Swatinem/rust-cache` 缓存 `target/`，第二次 clippy 从几分钟降到几十秒；
- NDK 由 `nttld/setup-ndk` 下载（r29），`cargo-ndk` 由 `taiki-e/install-action` 装；
- **打包器写 ramdisk 时调的是 `lz4` 命令行**（读的时候是纯 Rust 的 `lz4_flex`），
  `ubuntu-24.04` runner 上自带；换 runner 镜像要确认这一点，否则 `image` job 会死在打包步骤；
- 原厂 `recovery.img` 可以再加一层 `actions/cache`（key 用 sha256），避免每次下载 100 MiB。
  当前 workflow 直接 `curl`，从 release 下 100 MiB 在 runner 上是几秒级，够用。
