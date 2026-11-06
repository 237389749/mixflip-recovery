# 可复现的思路

> 这份文档记的不是“改了什么”，而是**这类问题下次怎么再走一遍**。
> 每条都配一个这次真实发生过的例子，避免变成空话。
>
> 适用面比“外屏 recovery”宽：任何“某个显示/设备在特定硬件上不对”的活，都会撞上同样的几件事。

---

## 1. 一个“不行”的结论，先问它换层还成立吗

**做法**：把系统按层切开，问这个“不行”是在哪一层不行的。

```
bootloader → 内核 → 用户态程序 → framework
```

**这次的例子**：refMD 原文写“fastboot / recovery 显示在外屏 ❌ 不行”，
一条结论盖住了两层。拆开后：

- fastboot 是 bootloader 画的 → 改 ROM 真的够不到，❌ 成立；
- recovery 是 Linux 用户态程序，自己打开 `/dev/dri/card0` → 选哪块屏是它自己的代码，✅ 能改。

**反例警告**：同一个项目里 framework 层的经验（属性层、`device_state`、`multi_display_type`）
对用户态程序**一条都不适用**。recovery 里没有 framework，那些机制根本不存在。

---

## 2. 硬件事实去镜像里挖，不要推断

**做法**：能解二进制就别查文档、别问模型、别凭印象。

| 要问的事 | 去哪拿 |
|---|---|
| 面板名称/分辨率/刷新率 | `dtbo.img` 的 FDT |
| 触摸 IC 配哪块屏 | DT 里触摸节点的 `panel` phandle |
| 背光节点叫什么 | 上机 `ls /sys/class/backlight/`（DTB label 拼的，静态搜不到） |
| 内核有没有某个参数 | 源码分支 或 上机 `ls /sys/module/*/parameters/` |

**这次的教训**：`panel0/panel1` 哪个是内屏，我一开始是**推定**的，后来确认原厂 kernel 里
根本搜不到这两个字符串 —— 所以它只能是上机判定项，不该写成结论。至今仍是推定状态。

---

## 3. 解析二进制要有“结果对不对”的自检

dtbo 的 FDT 有两个必做项，任一错就是 0 个节点或垃圾：

1. 结构是**大端**；
2. 节点名之后按 **4 字节对齐**。

**可复用的自检**：解析完先看数量是否合理（`nodes=12345` 而不是 0 或 1），
再看一条已知的真值（比如 `qcom,mdss-dsi-panel-width` 是不是 1224）。**数量对不上就先怀疑解析器，别怀疑数据。**

---

## 4. 两个东西配不成对时，找把它们连起来的那条边

**做法**：不要分别研究两个端点，去找外键 / phandle / 注册表项。

**这次的例子**：查“触摸为什么改到外屏就全死”，分别看两个驱动会卡住。
转折点是去找 DT 里的 `panel` phandle：

```
synaptics_tcm@0   panel → 0x122 → ..._prim_dsc_cmd  (1224×2912)  内屏
goodix_berlin@0   panel → 0x123 → ..._sec_dsc_cmd   (1208×1392)  外屏
```

这一条同时解释了三件原本无关的事：`TW_INPUT_BLACKLIST="goodix_ts"` 为什么存在、
ramdisk 里为什么塞了 `goodix_core.ko` 却不 `insmod`、以及为什么外屏版必须换触摸驱动。

---

## 5. 改“显示到哪”，要同时查三样

选屏只是三分之一：

| | 漏了会怎样 |
|---|---|
| scanout 选屏 | — |
| 背光点亮 | 画在外屏、点亮内屏 → **外屏全黑而日志全绿** |
| 触摸输入 | 画对了但点不动，或摸内屏控制外屏 |

**这次的例子**：skyward 把 `panel0-backlight` 写死；只改选屏不改背光，症状极具误导性 ——
日志里一切正常，屏幕全黑。

---

## 6. 能编译就别只读；能让 CI 跑就别手工跑

这条是两轮会话里**收益最高**的一条。本轮四处问题，没有一处能从读代码发现：

| 问题 | 只有谁能发现 |
|---|---|
| glibc 没有 bionic 的 `__unused` | 在 glibc 上编译 |
| `root.join(&format!(...))` 触发 clippy | 跑 host 的 `--all-targets` |
| 外屏 1208×1392 下 `crop` 越界 abort | **真跑一次预览器** |
| 检查脚本在 CI 找不到设备树 | 在 CI 的目录布局下跑 |

第三条尤其值得记：它**只在“真的有一个非标准尺寸跑过”时出现**。
只做内屏版就永远发现不了。

**判据**：如果一个验证需要“换台机器 / 换个目标 / 换个尺寸”才能做，那它就应该进 CI，
而不是写进“待人工验证”清单。

---

## 7. 平台差异先建基线，比通过数而不是通过与否

跨平台项目里“测试挂了”九成不是你的锅，但你必须证明它。

```bash
git stash && cargo test -p X    # 基线：9 passed; 15 failed
git stash pop && cargo test -p X # 改动后：13 passed; 15 failed
```

**通过数 +4、失败数不变** → 那 15 个与我无关。

---

## 8. 同一件事只留一个真值来源

**做法**：一个决定，只让一个地方能设为真。重复设置同一项，结果会取决于读取顺序。

**这次的例子（两次踩到同一类问题）**：

1. skyward 打包时只在 `prop.default` 末尾追加 `ro.secure=0`，靠“同一文件后一行覆盖前一行”生效。
   改成**先删掉** stock 的 6 个属性再写（`0007`）——把“能不能 root”压在一个未验证的
   init 行为上不值得。
2. TWRP 侧 `system.prop` 和变体 prop 文件都想设 `twrp.drm.connector`。
   改成**只有变体文件设**（`0002b`），并且写了检查脚本强制这一点 ——
   脚本当场就抓到了残留的一行。

---

## 9. 配置的差异要能被机器检查

**做法**：两个变体允许不同的键，列成白名单；其余必须逐字相同，用脚本比。

**这次的例子**：`ci/check-variants.py` 去掉白名单键再比较两份 TOML。
它抓到了我原本没想到的差异维度（`modules.load`），说明**写检查脚本会逼你想清楚“什么算同一个东西”**。

同类的：`tools/check-twrp-variants.py` 用**真 make** 展开 `BoardConfig.mk`，
而不是正则读文件。理由是 `ifeq` 的求值顺序、变量展开时机，读文件读不出来。

---

## 10. 验证缺口要显式声明，且分级

“没测”和“测了但没测到”是两回事。写清楚三档：

| 档 | 含义 | 例子 |
|---|---|---|
| ✅ | 真跑过、有输出 | CI 全绿、`cargo clippy` 通过 |
| ⚠️ | 部分验证 / 推定 | 背光归属从 DT 推的，未上机 |
| ❌ | 完全没验证 | DRM 提交、真机点亮 |

**这次的例子**：TWRP 补丁只有“能贴 + 能编译 + 变体变量正确”，
**链接进 recovery 后能不能跑、真机能不能亮，完全没验证**。这必须写在文档显眼处，
否则下一个人会以为“都测过了”。

---

## 11. 该改旧文档就改，不要只加新文件

**理由**：错误的旧结论会被下一次会话当作**前提**引用，传播成本比修一次高得多。

**这次的例子**：`Single_Outer_Screen_Plan.md` 里“改 ROM 永远解决不了 fastboot/recovery 的单外屏显示”
这句话，如果留着不改，后面的会话会直接引用它，然后得出“不可能”的结论。
所以那一轮不仅新增了 `Recovery_Outer_Display.md`，还回头改了 `Plan.md` 的 §1 表和 §7 禁令。

**本轮的同类动作**：TWRP 单外屏版从“不完整（还差三处）”变成“已经做了”，
就把 `CHANGES.md`、`ADB_AND_ROOT.md`、`VERIFICATION.md` 里对应的旧表述全部更正，
而不是留着新补丁让旧结论在旁边发霉。

---

## 12. 一个“上游”判断：哪些该提 PR，哪些该自己留着

**判据**：这个改动**对其它机型是否也成立**、以及**上游 CI 会不会因此变红**。

| 改动 | 归属 | 原因 |
|---|---|---|
| `[display] panel` / `[touch] device` / 容错 | 提 PR | 所有双屏折叠机通用 |
| `devices/bixi.toml` | 自己留着 | 上游 CI 要 OTA 包地址，提上去会红 |

**补丁栈是为“PR 被拒或长期不回”准备的**：钉 commit、`git diff` 生成、每个 release 重放。
**宁可维护 6 个补丁，也不要 fork 之后长期改 `main`** —— 那会把“上游修了 bug 我们没跟上”
变成常态。

---

## 附：这次用到的命令（可直接重放）

```bash
# 补丁在干净基线上应用（顺序即 CI 顺序）
git -C upstream apply patches/0003-*.patch patches/0004-*.patch \
                           patches/0005-*.patch patches/0006-*.patch patches/0007-*.patch
cp devices/*.toml upstream/devices/

# 编译验证（Android 目标 = 真机目标）
cargo clippy -p skyward -p skyward-ui -p skyward-config \
    --target aarch64-linux-android -- -D warnings

# 两端配置一致性
python3 ci/check-variants.py

# TWRP 变体（用真 make，不用正则）
python3 tools/check-twrp-variants.py <设备树路径>

# 打出来的镜像是否默认 adb + root
python3 tools/check-recovery-adb.py <recovery.img> --pack <skyward-pack>

# 外屏排版（必须 Linux/macOS）
cargo run --release -p skyward-preview -- out --device bixi-cover --lang zh-CN

# 上机判据（改任何配置之前先做）
adb shell 'for d in /sys/class/drm/card0-DSI-*; do echo "== $d"; cat $d/status; head -1 $d/modes; done'
adb shell 'echo 100 > /sys/class/backlight/panel1-backlight/brightness'   # 看哪块屏亮
```
