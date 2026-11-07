# 抓“拔掉内屏卡开机”的日志：可行性

> 状态（2026-11-07）：**可行性用静态证据确认了，一条命令都还没在真机上跑过**（实机未到）。
> 本文是实机到了之后照着做的清单，不是结果记录。
> 结论里的“✅”只表示“镜像里确认存在这条通道”，不表示“在上面读到过内容”。

---

## 0. 一句话

recovery 的 adb（默认就是 root）**看不到**上一次启动的实时 logcat，
但**能看到上一次启动留在预留内存里的内核 console** —— 这台机器的设备树里有一块 4 MiB 的
`ramoops`，其中 2 MiB 给 console、2 MiB 给 pmsg。

所以“为什么拔掉内屏卡开机”大概率能在 `/sys/fs/pstore` 里直接读到，前提是**上次启动以 panic 收场**。
如果是“不重启的死等”，那里什么都没有，才需要动镜像（§5）。

---

## 1. 静态事实（可复现）

```powershell
python tools\vendor_boot_ramoops.py ..\bixi_images_OS3.0.304.0\bixi_images_OS3.0.304.0.WOHCNXM_16.0\images\vendor_boot.img
```

```text
dt #1 .. dt #8 at 0x019f2000 … : 5 properties on /reserved-memory/ramoops-region
    reg          = 0x00000000a3500000 + 4 MiB
    console-size = 0x00200000 (2 MiB)
    pmsg-size    = 0x00200000 (2 MiB)
    record-size  = absent (the kernel default applies)
    ftrace-size  = absent (the kernel default applies)

PASS 8 device trees agree: one ramoops region, console 0x00200000 (2 MiB)
```

| 项 | 值 | 来源 |
|---|---|---|
| 节点 | `/reserved-memory/ramoops-region` | `vendor_boot.img` 的 8 棵 DT，全部一致 |
| `compatible` | `ramoops` | 同上 |
| `reg` | `0xA3500000` + 4 MiB | 同上 |
| `console-size` | 2 MiB | 同上（内核 console 的持久环） |
| `pmsg-size` | 2 MiB | 同上（`/dev/pmsg0`，用户态可写） |
| `record-size` | 未设，内核默认 | 同上（影响 `dmesg-ramoops-*` 有没有） |
| 内核侧参数 | `ramoops.record_size` / `console_size` / `ftrace_size` / `pmsg_size` | `boot.img` 里的内核字符串 |

为什么值得信这个脚本：它要求每棵 DT 的 ramoops 区域**完全一致**，并且只认属性数上千的真 FDT
（假 magic 会被丢掉）—— 解析器的输出自带一个“结果合理吗”的自检，见 [METHOD.md](METHOD.md) 第 3 条。
换固件后重跑一次；不一致就说明不同板型把日志放在不同地方，上机时要分别看。

---

## 2. 能抓到什么，抓不到什么

| 通道 | 能拿到什么 | 现在能不能指望 |
|---|---|---|
| `/sys/fs/pstore/console-ramoops-0` | **上一次启动的内核 console**（包括 DSI / panel / composer 的初始化报错） | ✅ 通道存在（2 MiB）；内容待实机确认 |
| `/sys/fs/pstore/pmsg-ramoops-0` | 用户态经 `/dev/pmsg0` 主动写进去的东西 | ⚠️ 存在，但默认没有程序往里写 |
| `/sys/fs/pstore/dmesg-ramoops-*` | oops / panic 的 dmesg 记录 | ⚠️ `record-size` 未设，可能根本没有这个文件 —— 先 `ls`，别假设 |
| `dmesg`（recovery 自己这次） | 同一个内核 + 同一份 DT，拔着内屏时 DSI-1 的表现会**原样重现** | ✅ 一定会跑（上机时才看得到） |
| `/proc/cmdline` 里的 `androidboot.bootreason` | 上次为什么重启（watchdog / panic / reboot / userrequested） | ✅ 一定会跑 |
| `/data/tombstones`、`/data/system/dropbox` | 原生进程崩溃、fatal 记录残留 | ⚠️ 需要挂上 `/data`，且 FBE 要能解开 |
| 上一次启动的 `logcat` / system_server 栈 | 为什么 applyLayoutLocked 炸了 | ❌ 拿不到（见 §5） |
| bootloader（xbl / abl）的日志 | 选屏、验证失败、重启原因 | ❌ 只能靠串口（`ttyMSM0`）或 Qualcomm ramdump |

“recovery 的 adb 是 root”这件事不是假设：`adbd` 的服务本身就以 `user root` 运行，
没有 `su` 二进制也不需要 —— 见 [ADB_AND_ROOT.md](ADB_AND_ROOT.md)。

---

## 3. 实机当天的顺序（照抄）

```bash
# 1) 先抢 pstore。第一件事：recovery 自己的 console 也在往同一块 2 MiB 环里滚
adb shell 'ls -l /sys/fs/pstore/'
adb shell 'for f in /sys/fs/pstore/*; do echo "=== $f"; cat "$f"; done' > pstore.txt

# 2) 这次启动的内核日志（同内核/DT，DSI-1 的问题会重现）
adb shell dmesg > rec-dmesg.txt

# 3) 上次为什么重启
adb shell 'cat /proc/cmdline' | tr ' ' '\n' | grep -i bootreason

# 4) 显示栈现状 —— 同时回答“能不能检测内屏在不在”
adb shell /system/bin/skyward kms

# 5) 磁盘上的残骸
adb shell /system/bin/skyward mount     # 按 fstab 挂分区（含 /data）
adb shell 'ls -l /data/tombstones /data/system/dropbox 2>/dev/null'
```

顺序是有讲究的：

- **先 pstore 后其它**。ramoops 的 console 区是环形的，recovery 一启动就写它自己的日志进去，
  先折腾别的、或者重启一次，上一次启动的内容就被挤掉了；
- `skyward kms` 和 `skyward mount` 都是现成子命令，不用往镜像里加东西；
- `/data` 是 FBE：没有锁屏密码时 recovery 能读，设了密码就读不到 —— 读不到不算失败，记下来即可。

---

## 4. 判读：三种“卡”对应三条路

| 现象 | pstore 里会有东西吗 | 下一步 |
|---|---|---|
| 反复重启，`bootreason` 是 `watchdog` / `panic` | 有 console，可能还有 `dmesg-ramoops-*` | 直接读，基本能定位到哪一层 |
| 反复重启，`bootreason` 是 `reboot` / `userrequested` | 可能只有 console | 看 console 尾部（谁是最后说话的），再走 §5 |
| 不重启，停在 logo | **没有**（没有 panic，内存区没人写） | 只能走 §5 |
| 停在 bootloader / 直接进 fastboot | — | 与 recovery 无关的另一类问题 |

---

## 5. 抓不到时怎么补：改镜像，代价是 AVB

两条路都要重打包 `boot` 或 `vendor_boot`，所以都会踩 AVB。**不要在主用机上做。**

### 方案 A：早期 logcat 落盘（推荐先试这个）

用 `skyward-pack boot` 把原厂 kernel 和原厂 boot ramdisk 拼回去，同时在 ramdisk 里加一个 init 服务：

```rc
# 大意：logd 比 system_server 起得早，赶得上记录它的启动
service skyward-bootlog /system/bin/logcat -b all -f /metadata/skyward-boot.log
    class late_start
    user root
    oneshot
```

选 `/metadata` 的理由：它在 fstab 里、`first_stage_mount`、**不需要解密**，而且刷机/清数据不影响。

### 方案 B：让 adbd 更早起来

把 `ro.adb.secure=0` 之类的开关带进 ramdisk，让 adbd 在第一阶段就起 —— 这样卡开机时
“Android 的 adb”能连上，可以直接 `adb logcat` / `adb shell ps` / `cat /proc/...`，还能在卡住的现场动手。
这条路信息最多，但“没起来时连不上”的风险也最大，适合和方案 A 一起用。

### 两个方案共有的 AVB 代价

- 改到的是被验证的分区，刷之前要 `fastboot --disable-verification flash vbmeta vbmeta.img`
  （可能还要 `--disable-verity`），否则设备会拒绝启动；
- **先准备好回滚**：原厂 `boot.img` 就在本地，sha256 记在 `manifest.toml`/`VERIFICATION.md`；
- 这是“拆机测试”之外多出来的一层风险面，最好等 §3 的结果回来再决定要不要做。

---

## 6. 和“自动选屏”的关系

同一份 `dmesg | grep -iE 'dsi|panel'` 就同时回答两件事：

- 拔掉内屏时，内核是让 DSI-1 **消失**、**在但 modes 为 0**、还是**一切照旧只有一行报错** ——
  这决定自动选屏能不能按连接器状态判断（上一轮的三种形态 A/B/C）；
- 如果内核确实读到了“面板 ID 读不到”，那 `console-ramoops` 里也会有这行 —— 也就意味着
  **卡开机的原因和检测内屏存在的判据是同一个事实**，一次上机可以同时拿到。

---

## 7. 未验证清单

| 项 | 档 | 说明 |
|---|---|---|
| 设备树里有 ramoops 区域 | ✅ | `tools/vendor_boot_ramoops.py`，8 棵 DT 一致 |
| 内核带 ramoops / pstore | ✅ | `boot.img` 里的驱动参数与字符串 |
| `/sys/fs/pstore` 真有文件 | ⚠️ | 通道存在 ≠ 里面有内容；要等第一次实机 |
| `record-size` 缺省时 `dmesg-ramoops-*` 是否存在 | ⚠️ | 先 `ls` 再说，别写死在脚本里 |
| `androidboot.bootreason` 的取值 | ❌ | 实机看 |
| 拔着内屏时 recovery 能起来（外屏版） | ⚠️ | 镜像已出包，未上机 |
| 早期 logcat 落 /metadata 方案 | ❌ | 只写了思路，没打过一个镜像 |
| AVB 回滚流程 | ❌ | 没在真机上 disable-verification 过 |

---

## 8. 下次接手的顺序

1. 进 recovery，**第一件事** dump `/sys/fs/pstore`（§3）；
2. 看 `bootreason`：有 panic 就基本结束了，没有就进 §5；
3. 不管哪条路，顺手 `dmesg | grep -i dsi` 和 `skyward kms` —— 自动选屏的判据和这里要的是同一份数据。
