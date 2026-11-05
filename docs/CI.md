# CI：它替我们解决了什么，不解决什么

本地是 Windows：`skyward-preview`、`skyward-install`、`skyward-net` 这些 crate 依赖
`std::os::unix` / `rustix` / `UnixAddr`，**在 Windows 上编不出来**；TWRP 更不可能在 Windows 上全量编。
CI 就是用来补这两个洞的。

## 1. 每次 push 跑什么

`.github/workflows/ci.yml`：

| job | 做什么 | 用时 |
|---|---|---|
| `skyward` | 按 `manifest.toml` 的 commit 克隆 skyward → 打 0003/0004/0005 → 放 `devices/*.toml` → `cargo clippy --workspace --all-targets -D warnings` + `cargo test --workspace` | 几分钟 |
| `variants` | 同一套准备，Linux 上跑 `skyward-pack` 解析两份配置；`ci/check-variants.py` 检查两版只差规定键 | 秒级 |
| `preview` | 两个变体各跑一次 `skyward-preview --device bixi` / `--device bixi-cover`，把 PNG 当 artifact | 几分钟 |
| `twrp` | 克隆 TWRP 16 的 `bootable/recovery` → 打 0001 → **`g++ -fsyntax-only` 编译 `graphics_drm.cpp`**（真源码 + libdrm + 桩头文件） | 一分钟 |
| `image` | 可选：有 `STOCK_BIXI_URL` 时下载原厂 `recovery.img`、校验 sha256、`skyward-pack recovery` 出两个变体的 img 并 zip | 几分钟 |

`image` 和 `preview` 都只在 push/tag 时跑；PR 只跑前三个。

## 2. 让 CI 能出镜像：`STOCK_BIXI_URL`

`skyward-pack recovery` 需要原厂 `recovery.img`（整分区，100 MiB，结尾带 AVB footer）。
本地它在：

```
../bixi_images_OS3.0.304.0/bixi_images_OS3.0.304.0.WOHCNXM_16.0/images/recovery.img
sha256 bc32c5fa4f4396fd52a4c65d03ea84bb147609812194da4eecf12723e5fafcd9
```

GitHub 的 runner 拿不到本地文件，所以需要一个 HTTPS 地址。最省事的做法：

1. 在本仓库建一个 release，把 `recovery.img` 传成 asset（100 MiB，在 2 GiB 的 asset 限制内）；
2. 复制 asset 的直链，形如
   `https://github.com/<owner>/<repo>/releases/download/stock-bixi/OS3.0.304.0.WOHCNXM-recovery.img`；
3. 仓库 **Settings → Secrets and variables → Actions → Variables → New repository variable**，
   名字 `STOCK_BIXI_URL`，值就是上面的直链。

CI 会从 `manifest.toml` 读 `[stock] sha256` 校验，**校验不过直接失败**，不会拿错版本的镜像出包。
没有设置这个变量时，CI 跳过出镜像，只编二进制 + 跑测试 + 出预览，不会红。

> 为什么不直接让 `skyward-pack stock` 去小米 OTA 下载：那个子命令只认“完整 OTA 包里的
> payload.bin”，而手上的原厂包是 **fastboot 线刷包**（`recovery.img` 已经是解开的单分区）。
> 用 release asset 直接喂 `recovery.img` 更短、更可控，也避开了小米 OTA 的查询接口。

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
- 原厂 `recovery.img` 可以再加一层 `actions/cache`（key 用 sha256），避免每次下载 100 MiB。
  当前 workflow 直接 `curl`，够用；要更快就加缓存。
