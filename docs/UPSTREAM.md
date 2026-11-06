# skyward 怎么落地：提 PR，还是自己养一个仓库

结论：**两者都要，但分工不同。**

- **通用引擎改动 → 提 PR 回上游**（`kirklin/skyward`）；
- **bixi 设备配置、两个变体、CI、文档 → 留在这个仓库**。

## 1. 为什么不是“全提 PR”

skyward 的 `devices` 矩阵在 CI 里对每个 `devices/*.toml` 跑：

```bash
tools/skyward-pack stock --config devices/<codename>.toml   # 需要一个 HTTPS 的完整 OTA 包
```

`[stock] package` 必须是“完整 OTA 包里带 payload.bin 的 zip”。我们手上是**小米 fastboot 线刷包**，
`recovery.img` 已经是解开的单分区，没有 OTA 包地址。把 `bixi.toml` 提上去，上游 CI 的
`recovery` job 会直接因为 `[stock]` 缺失/无效而红。

所以：

| 内容 | 归属 | 原因 |
|---|---|---|
| `[display] panel` / `backlight` / `backlights_off` | 上游 PR | 所有双屏折叠机通用 |
| `[touch] device` | 上游 PR | 一块屏一个触摸控制器的机器通用 |
| `normal_max()` / `resonance()` 容错 | 上游 PR | 对现有 21 个机型等价，bixi 必需 |
| `skyward-preview --device` | 上游 PR | 纯工具增强 |
| `row_part` 的 band 裁切（0006） | 上游 PR | 短屏通用，且是 preview 真抓到的崩溃 |
| `devices/bixi.toml`、`bixi-cover.toml` | 本仓库 | 缺 `[stock]` OTA 地址 |
| 两个变体的构建/命名/`check-variants` | 本仓库 | 上游不需要“同一机型两个变体”的概念 |

## 2. 提 PR 怎么拆 commit

不要把一个 `0003` 原样丢上去。按关注点拆，每个 commit 能独立解释、独立测试：

| commit | 内容 | 对应补丁 |
|---|---|---|
| 1 | `[display] panel` + `KmsSurface::open_on()`（核心） | 0003 前半 |
| 2 | `[display] backlight` + `Backlight::open(named)` | 0003 |
| 3 | `normal_max()` 的容错 | 0003 |
| 4 | `resonance()` 的单位容错 | 0003 |
| 5 | `skyward-preview --device` | 0003 |
| 6 | `[touch] device` | 0004 |
| 7 | `[display] backlights_off` | 0004 |
| 8 | 短屏按住行的 band 裁切 | 0006 |
| 9 | 打包时去掉 stock 的 `ro.secure` / `ro.adb.secure` / `ro.debuggable`，不靠重复行覆盖 | 0007 |

`0005`（bixi 配置测试）**不要提**：它 `include_str!` 了本仓库的 `devices/*.toml`，上游没有这两个文件。

提交信息用上游的风格：`feat: …` / `fix: …`，正文说清“为什么”和“对现有设备为什么等价”，
不要写机型私货。上游作者在代码注释里写得很细，PR 的描述也应该如此。

## 3. 提 PR 之前先跑什么

CI 已经替我们跑了上游 `check` job 的等价内容：

```bash
cargo clippy --locked --workspace --all-targets -- -D warnings
cargo test --locked --workspace
cargo ndk -t arm64-v8a --platform 30 clippy --locked -p skyward -p skyward-install -- -D warnings
```

本仓库的 `.github/workflows/ci.yml` 就是这三条 + preview + 变体检查。PR 前确认它绿。

## 4. PR 合并之后

- 上游发布新版本（如 v0.1.3）后，把 `manifest.toml` 的 `ref` 指到新 tag；
- 已经合并的补丁从 `patches/` 删掉，重新生成剩下的；
- `devices/*.toml` 不动 —— 它们只依赖配置字段，不依赖补丁；
- 如果上游改了字段名/语义，`ci/check-variants.py` 和 `cargo test` 会先报警。

## 5. 如果 PR 被拒/长期不回

补丁栈就是为这个准备的：`manifest.toml` 钉 commit，`patches/` 是 `git diff`，
每个 release 重放一次即可。**不要 fork 后长期改 `main`** —— 那会把“上游修了 bug 我们没跟上”
变成常态。宁可维护 6 个补丁，也不要维护一个分叉。

## 6. 现在的状态

- 本仓库：已建（私有），CI 全绿，两个变体可构建/可预览；
- 上游 PR：**还没提**。要提的话，先确认 `bixi.toml` 不随 PR 走，再按上表拆 commit。
