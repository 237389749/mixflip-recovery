# 默认 adb 与 root：现在是什么、怎么验

> 结论：**skyward recovery 默认就开 adb，连上就是 root shell，不需要在手机上点任何东西，
> 也不需要授权。没有 `su` 这个命令，但也不需要它。**

外屏可能全黑、触摸可能没起来，这时候命令行就是唯一入口；所以这一条不是“附加功能”，
是这两个版本能不能用的前提。

---

## 1. 机制：为什么插上就是 root

### 1.1 打包时追加的属性

`skyward-pack recovery` 先把 stock 里相反的三个属性**删掉**，再在 `prop.default` 末尾追加：

```properties
ro.secure=0
ro.adb.secure=0
ro.debuggable=1
ro.ota.allow_downgrade=true
```

这是本仓库的补丁 `0007`：原厂文件本来有 `ro.secure=1` / `ro.adb.secure=1` / `ro.debuggable=0`，
上游原来的做法是直接追加、靠“同一属性文件里后面的行覆盖前面的行”生效。**我们不再依赖这个语义**，
把这 6 个属性（3 个 build version + 3 个 adb）先删掉再写，结果里没有重复行。
三者作用：

| 属性 | 值 | 作用 |
|---|---|---|
| `ro.secure` | 0 | adbd 不降权到 `shell`，保持 root |
| `ro.adb.secure` | 0 | 不做 RSA 授权，任何电脑直接连 |
| `ro.debuggable` | 1 | 可调试构建 |

### 1.2 原厂 init 本来就以 root 启动 adbd

原厂 recovery 的 `system/etc/init/hw/init.rc` 里：

```text
service adbd /system/bin/adbd --root_seclabel=u:r:su:s0 --device_banner=recovery
    disabled
    socket adbd stream 660 system system
    seclabel u:r:adbd:s0
    user root

on property:sys.usb.config=adb && property:sys.usb.config_disable=0
    start adbd
```

adbd 的服务本来就是 `user root`，`--root_seclabel=u:r:su:s0` 也给了它 su 的 SELinux 域；
`ro.secure=0` 只是让它**不主动降权**。

### 1.3 skyward 在 UI 之前就把 adb 拉起来

`crates/skyward/src/main.rs` 的 `recovery()` 顺序是：

1. 保留日志；
2. 如果 `sys.usb.state` 不是 `adb`，先切到 `none` 再切 `adb`；
3. 读 misc、加载配置、起 UI。

也就是说：**配置写错、DRM 选屏失败、触摸没起来，adb 都已经在了**。UI 崩了 init 会重启
skyward，adb 不会被带走。这正是“外屏不亮也能救”的保险。

UI 起来后，端口会变成 `mtp,adb`（文件传输 + adb）；MTP 停掉又回到 `adb`。

### 1.4 什么时候会看到 `unauthorized`

只有一种情况：`ro.adb.secure=0` 没生效（比如某次打包没追加、或属性被更后面的文件覆盖）。
这时 `adb devices` 会显示 `unauthorized`，需要在手机上点“允许”，而外屏版恰恰可能点不到。
所以 CI 会对打出来的镜像跑 `tools/check-recovery-adb.py`，不通过就不出包。

---

## 2. 刷入后怎么验（30 秒）

```bash
adb devices
# 期望直接是 device，不是 unauthorized

adb shell 'getprop ro.secure; getprop ro.adb.secure; getprop ro.debuggable'
# 期望 0 / 0 / 1

adb shell id
# 期望 uid=0(root) gid=0(root)

adb shell 'getprop sys.usb.state; getprop init.svc.adbd'
# 期望 adb（或 mtp,adb）/ running
```

如果 `id` 不是 root：

- 看 `getprop ro.secure` 的最后值；不是 0 就是属性没覆盖成功；
- 看 `getprop ro.adb.secure`；不是 0 就会要授权；
- 这两个是打包期决定的，刷错镜像只能换包，运行时改不了（`ro.*` 只读）。

---

## 3. 为什么没有 `su`

- 原厂 recovery ramdisk 里**没有** `/system/bin/su`，toybox 也没编 `su` applet（本次已核对）；
- 但 `adb shell` 本身就是 uid 0，**再套一层 `su` 是多余的**；
- 所以 `adb shell su` 会 `not found`，这不是 bug。

### 如果你有脚本硬编码了 `su -c`

两种做法：

1. 把脚本里的 `su -c 'cmd'` 改成 `sh -c 'cmd'`（recovery 里 sh 已经是 root）；
2. 或者让我们在打包时加一个 `/system/bin/su` 垫片（几行 shell，把 `su -c` 转成 `sh -c`）。
   这会改 stock ramdisk 的内容，属于额外改动；目前**没做**，因为 adb 已经是 root。

---

## 4. 安全边界

- `ro.adb.secure=0` 意味着**拿到手机和数据线的人就能 root**。这在 recovery 里是刻意的；
- 这些属性只在 **recovery 的 ramdisk** 里，不影响正常系统；
- 不要把 recovery 当日常系统用；也不要把这套属性搬进 ROM。

---

## 5. TWRP 侧

TWRP 的路子一样，只是时机不同：

- `system.prop` 里 `ro.adb.secure=0`；
- `init.recovery.qcom.rc` 的 `on init` 里 `setprop sys.usb.config adb`；
- TWRP 的 adbd 也是 root，终端本身也是 root。

外屏版 TWRP 目前**不完整**（背光路径/黑名单没换，见 [CHANGES.md](CHANGES.md) §3），
但“adb 默认开、root”这一条在 TWRP 侧是成立的。

---

## 6. 自动化检查

```bash
python tools/check-recovery-adb.py <recovery.img> --pack <skyward-pack>
```

它检查打出来的镜像，而不是源码：

- `system/bin/adbd` 在 ramdisk 里；
- `prop.default` 里 `ro.secure` / `ro.adb.secure` / `ro.debuggable` 的**最后一行**是 0/0/1；
- `init.rc` 定义 `service adbd`、`user root`、并在 `sys.usb.config=adb` 时 `start adbd`；
- 报告有没有 `su` 二进制（不要求有）。

CI 的 `image` job 在出包后自动跑这一步。本机对烟测镜像的结果：

```text
ok   system/bin/adbd is in the ramdisk
ok   ro.secure=0 (last line)
ok   ro.adb.secure=0 (last line)
ok   ro.debuggable=1 (last line)
ok   init.rc defines the adbd service
ok   adbd runs as root
ok   init.rc starts adbd when sys.usb.config is adb
note no su binary; adbd is already root, so `adb shell` is root
PASS: adb is on by default, as root, with no authorization prompt
```
