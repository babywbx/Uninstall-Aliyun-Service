<div align="center"><a name="readme-top"></a>

# Uninstall Aliyun Service

一键卸载阿里云云安全中心（云盾）Agent 并清理历史残留组件的 Bash 脚本，<br/>
可选同时卸载云助手（Cloud Assistant）、云监控（CloudMonitor）和 LoongCollector。

[English](./README.en.md) · [报告问题][github-issues-link] · [参考文档][doc-uninstall-link]

<!-- SHIELD GROUP -->

[![][github-stars-shield]][github-stars-link]
[![][github-forks-shield]][github-forks-link]
[![][github-issues-shield]][github-issues-link]
[![][github-license-shield]][github-license-link]<br/>
[![][github-contributors-shield]][github-contributors-link]
[![][github-lastcommit-shield]][github-lastcommit-link]
[![][github-ci-shield]][github-ci-link]

</div>

> \[!TIP]
>
> **在找腾讯云的方案吗？** 请使用同系列的 [Uninstall Tencent Service][uts-link]，一键卸载腾讯云主机安全（云镜 YunJing）Agent，可选同时卸载云监控（BaradAgent / Sgagent）和自动化助手（TAT）。

<details>
<summary><kbd>目录</kbd></summary>

#### TOC

- [📋 概述](#-概述)
- [⚠️ 前置条件](#️-前置条件)
- [🚀 快速开始](#-快速开始)
- [📖 用法](#-用法)
- [🔩 执行流程](#-执行流程)
- [🧪 实测记录](#-实测记录)
- [🛠 故障排查](#-故障排查)
- [🔗 相关项目](#-相关项目)
- [📚 参考资料](#-参考资料)
- [📝 许可证](#-许可证)

####

<br/>

</details>

## 📋 概述

这个项目面向仍然存在历史遗留组件的 Linux 服务器环境。脚本会优先调用阿里云官方卸载脚本，并补充处理旧版 `quartz`、`agentwatch` 等常见残留。通过可选参数还可以一并卸载云助手（`aliyun-service` / `assist_daemon`）、云监控（`argusagent` / `CmsGoAgent`）和 LoongCollector（`loongcollectord` / `ilogtaild`）。当前官方云监控安装命令会顺带安装 LoongCollector，但它同时是日志服务（SLS）的采集 Agent，`--include-cloudmonitor` 不会卸载它，需要另加 `--include-loongcollector`。

适用场景：

- 🛡️ 需要卸载云安全中心 Agent（原 Aegis / 安骑士）
- 🧹 服务器上可能安装过旧版云盾组件，需要一并清理
- 🤖 需要卸载云助手（Cloud Assistant / `assist_daemon`）
- 📊 需要卸载云监控（CloudMonitor / `argusagent` / `CmsGoAgent`）
- 🪵 需要卸载 LoongCollector（日志服务采集 Agent，安装云监控时可能被一并装上）
- 📦 希望用一个脚本完成官方卸载和残留清理，而不是手动逐项操作
- 🖥️ 在非阿里云 ECS 或已退役的服务器上移除相关组件

<div align="right">

[![][back-to-top]](#readme-top)

</div>

## ⚠️ 前置条件

在执行脚本前，请确认以下条件：

1. 当前系统为 Linux，且已安装 `bash`（Alpine 等精简系统需要先安装）
2. 使用 `root` 或具备等效 `sudo` 权限的账户执行
3. 已安装 `awk`、`readlink`、`stat`、`grep`、`cksum`、`find`、`flock` 和支持 `-k` 的 `timeout`，并且可以读取 Linux `/proc`
4. 已安装 `curl` 或 GNU Wget，且能够通过 HTTPS 访问阿里云卸载入口。Alpine 推荐安装 `curl`；只有 BusyBox `wget` 时，默认拒绝下载

脚本检查依赖，但不会自动安装软件。缺少 `timeout` 时安装 GNU coreutils；`flock` 通常由 util-linux 提供。`--dry-run` 仍需满足本地检查所需的依赖，但不会下载官方脚本。

`--force` 的按需依赖包括 `lsattr`、`chattr` 和 `umount`：前两者仅在删除失败后修复阻塞属性时需要，`umount` 仅在处理已识别的 Agent 挂载时需要。脚本同样不会自动安装这些工具。

> \[!IMPORTANT]
>
> 按官方命令行卸载流程，应先在 [云安全中心控制台][console-link] 关闭以下保护项：
>
> - **客户端自保护**（Agent Protection）：在 **系统设置** → **功能设置** → **客户端能力配置** 中关闭 **防御模式** 开关，或在 **保护范围** 中移出目标服务器。仅暂停防护不会解除自保护
> - **恶意主机行为防御**（Malicious Host Behavior Prevention）
>
> 设置通常在 1 分钟内生效。`--force` 可以在官方卸载失败后尝试受限的本地清理，但不绕过内核自保护，也不保证保护开启时一定能够卸载。

### 支持的系统

以下是代码覆盖的系统接口和安装路径。自动化测试使用模拟文件与命令，真机上的验证情况见[实测记录](#-实测记录)。

| 类别 | 覆盖范围 |
| --- | --- |
| RPM 系 | Alibaba Cloud Linux、CentOS、RHEL、Rocky Linux、AlmaLinux、Fedora、openSUSE，用 `rpm -e` 卸载云助手软件包 |
| DEB 系 | Debian、Ubuntu，用 `dpkg --purge` 精确卸载云助手软件包，不通过 `apt-get` 连带移除依赖包；dpkg 锁被自动更新等进程占用时，最多等待 10 分钟 |
| 初始化系统 | systemd、SysVinit（`chkconfig` / `update-rc.d`）、OpenRC（如 Alpine）、Upstart |
| 安装路径 | 标准路径 `/usr/local/...`，以及 CoreOS / Flatcar 使用的 `/opt/...` |
| CPU 架构 | 云监控 Go 二进制按 x86_64、aarch64 / arm64、i386 系列选择；不把未知架构默认为 32 位 x86 |
| Bash 版本 | 保留 Bash 4.2 的语法兼容路径；目标主机仍需满足上述工具依赖 |

<div align="right">

[![][back-to-top]](#readme-top)

</div>

## 🚀 快速开始

推荐先下载并检查内容，再预览和执行。最后一条命令会交互确认：

```bash
curl --proto '=https' --proto-redir '=https' -fsSL https://raw.githubusercontent.com/babywbx/Uninstall-Aliyun-Service/main/UAS.sh -o UAS.sh
less UAS.sh
sudo bash UAS.sh --dry-run
sudo bash UAS.sh
```

非交互模式（跳过确认提示）：

```bash
curl --proto '=https' --proto-redir '=https' -fsSL https://raw.githubusercontent.com/babywbx/Uninstall-Aliyun-Service/main/UAS.sh | sudo bash -s -- -y
```

连同云助手一起卸载：

```bash
sudo bash UAS.sh -y --include-assist
```

连同云监控一起卸载：

```bash
sudo bash UAS.sh -y --include-cloudmonitor
```

安装云监控时一并装上的 LoongCollector 需要单独指定：

```bash
sudo bash UAS.sh -y --include-cloudmonitor --include-loongcollector
```

卸载全部组件，建议先空跑确认：

```bash
sudo bash UAS.sh --dry-run --include-assist --include-cloudmonitor --include-loongcollector
```

确认无误后正式执行：

```bash
sudo bash UAS.sh -y --include-assist --include-cloudmonitor --include-loongcollector
```

> \[!TIP]
>
> 如果 `raw.githubusercontent.com` 无法访问，可以使用 jsDelivr CDN 替代：
>
> ```bash
> curl --proto '=https' --proto-redir '=https' -fsSL https://cdn.jsdelivr.net/gh/babywbx/Uninstall-Aliyun-Service@main/UAS.sh | sudo bash -s -- -y
> ```

<div align="right">

[![][back-to-top]](#readme-top)

</div>

## 📖 用法

```bash
sudo bash UAS.sh [options]
```

### 参数

| 选项 | 说明 |
| --- | --- |
| `-y`, `--yes` | 跳过确认提示，直接执行 |
| `--include-assist` | 同时卸载云助手（Cloud Assistant / `aliyun-service` / `assist_daemon`） |
| `--include-cloudmonitor` | 同时卸载云监控（CloudMonitor / `argusagent` / `CmsGoAgent`），不包括 LoongCollector |
| `--include-loongcollector` | 同时卸载 LoongCollector（`loongcollectord` / `ilogtaild`，`/usr/local/ilogtail`、`/etc/ilogtail`）。当前官方云监控安装命令会顺带安装它 |
| `--skip-quartz` | 跳过旧版 quartz 清理 |
| `--allow-insecure-download` | 允许 HTTP 回退及 BusyBox Wget 下载，放宽默认下载限制 |
| `--dry-run` | 预览本地清理，不下载、不创建临时工作目录、不修改安装状态 |
| `--force` | 官方卸载普通失败或返回 `6` 后仍尝试本地清理；组件自带的停止命令失败时继续检查进程，已确认的用户态进程在 TERM 后仍未退出时发送 KILL（`AliSecGuard` 除外） |
| `--timeout SECONDS` | 卸载命令的时限，接受 `1` 至 `3600` 秒，默认 `120` 秒；超时后给出 `5` 秒宽限期，再发送 KILL。下载另设连接和传输超时 |
| `-h`, `--help` | 显示帮助信息 |

### 输出

执行过程按组件分段显示（环境、云安全中心、云助手、云监控、LoongCollector、验证），每行带 `[INFO]`、`[ OK ]`、`[WARN]`、`[FAIL]` 状态标签。终端支持时自动着色；输出被重定向、终端类型为 `dumb` 或设置了 `NO_COLOR` 环境变量时自动关闭颜色。

`--dry-run` 模式下，本地操作以 `[DRY-RUN]` 开头，并列出实际命中的进程和已存在的文件。官方脚本仅显示执行计划，因为预览不会下载或运行它们。

### 本地强制清理的边界

```bash
sudo bash UAS.sh -y --force --timeout 120
```

默认模式下，官方卸载返回非零就停止后续本地清理。`--force` 允许普通失败或状态码 `6` 后继续尝试，但官方步骤超时或被信号中断时仍停止。它只处理所选组件的已确认安装路径，不会通过宽泛的进程名匹配终止其他程序。

旧版 `quartz_uninstall.sh` 返回普通错误时，强制模式也会再次确认相关进程已停止，再尝试本地残留清理；超时或信号中断不会触发该回退。新出现的相关进程会在停止阶段被重新检查。

对所选组件的已知 systemd 单元，强制模式先停止，再通过屏蔽（mask）阻止再次激活。若 `/etc/systemd/system` 已有对应定义，先将其备份到仅 root 可读的 `/var/backups/uas-units.*`，并记录备份位置。组件清理失败时保留本次创建的 mask，成功完成组件文件清理后再移除，原有 mask 保持不变。脚本创建的 mask 记录在仅 root 可访问的 `/var/lib/uas/created-masks`，失败后留下的 mask 会在之后的运行中被识别，组件清理成功后解除并删除记录；记录清空时连同目录删除，没有记录的 mask 仍视为原有 mask。之后的内核模块检查仍可能返回 `3`，因此并非所有非零退出都会保留本次 mask。脚本不会自动恢复服务定义或重新启动服务。

如果删除已选安装路径或服务文件失败，强制模式会精确检查文件属性，只解除实际发现的 `i`（不可变）和 `a`（仅追加）标志，再重试删除一次。已备份的本地服务定义因这些属性无法替换为 mask 时，也使用同样的限定修复。属性修复跳过符号链接，拒绝修改挂载文件或具有多个硬链接的普通文件，也不会更改范围外路径或其他属性。删除或替换超时、被信号中断时不进行这项修复；预览模式不会更改属性，也不会模拟失败后才触发的修复。

强制模式可以在相关进程停止后卸载以下精确位置的内核伪文件系统。表中的 Agent 根目录仅限 `/usr/local/aegis` 或 `/opt/aegis`，允许上级目录存在符号链接，但挂载点必须位于解析后的安装目录内：

| Agent 根目录下的位置 | 允许的文件系统类型 |
| --- | --- |
| `aegis_debug` | `debugfs`、`tracefs` |
| `cgroup` | `cgroup`、`cgroup2` |
| `cgroup/cpu` | `cgroup`、`cgroup2` |

这些挂载的 mount root 必须是 `/`。脚本先检查完整列表，遇到其他位置、类型、未知子挂载或叠加挂载就停止。通过检查后，按从深到浅的顺序使用普通 `umount`，不使用 `-f`、`-l` 或递归卸载；每次操作前后核对包含挂载 ID 和 root 的原始记录，最后再次确认挂载已移除。预览只列出计划。Linux `mountinfo` 不记录 bind 来源，因此白名单位置的整根内核伪文件系统 bind 无法与普通挂载可靠区分，不能保证排除这类 bind。

本地回退不会向 `AliSecGuard` 发送任何信号，不会用 `rmmod` 强行卸载内核模块、修改控制台保护设置或自动重启。官方脚本仍按厂商实现执行驱动清理。进程无法停止时保留对应安装文件；保护仍然生效、路径不安全或验证发现残留时，结果不会标记为成功。官方卸载脚本本身可能已经做出部分修改，停止后续清理不等于自动回滚。

### 临时后台执行

先下载并检查脚本，在保存 `UAS.sh` 的目录中打开 root shell 后运行：

```bash
sudo -s
umask 077
log_dir="$(mktemp -d /var/log/uas.XXXXXX)" || exit 1
nohup bash -c '
  bash "$1" -y --include-assist --include-cloudmonitor
  status=$?
  printf "%s\n" "$status" > "$2/exit-code"
  exit "$status"
' _ "$PWD/UAS.sh" "$log_dir" </dev/null >"$log_dir/output.log" 2>&1 &
printf 'PID=%s\nLOG=%s\n' "$!" "$log_dir"
```

这会创建仅 root 可读的日志目录，不安装常驻服务。根据实际需要移除可选组件参数。`nohup` 返回 PID 只表示任务已启动，不能证明卸载成功；查看 `output.log` 和完成后写入的 `exit-code`。若 `exit-code` 不存在，检查进程与日志确认是仍在执行还是被中断。脚本使用独占锁拒绝另一个同时执行的实例。

### 退出状态

| 状态码 | 含义 |
| --- | --- |
| `0` | 所选组件的本地卸载验证通过；预览模式下表示预览完成 |
| `1` | 前置检查、清理或验证失败，查看失败操作和残留列表 |
| `3` | 本地检查仍发现相关内核模块，需要安排维护并复查 |
| `6` | 默认模式下，官方卸载报告可能仍有自保护 |
| `124` | 官方卸载步骤超时，后续本地清理未启动 |

官方脚本的其他非零状态也可能原样返回；中断通常返回 `130` 或 `143`。强制模式返回 `0` 只确认本地结果，不代表云端状态已同步。

<div align="right">

[![][back-to-top]](#readme-top)

</div>

## 🔩 执行流程

脚本默认执行以下流程：

1. 检查 Linux 和 root 权限，识别发行版；进行交互确认，`-y` 或 `--dry-run` 模式下跳过确认
2. 检查工具依赖和 `/proc`；正式执行时获取独占锁并创建私有临时目录
3. 检查所选安装目录，拒绝目录本身为符号链接或非 root 所有。默认拒绝挂载点；强制模式只接受上文白名单挂载。上级目录为符号链接（如 Fedora CoreOS 的 `/opt`）时按实际路径检查和匹配进程。`/opt/aegis` 非空但不含 `aegis_client`、`aegis_update` 或 `globalcfg` 时视为无关软件并停止执行。启动者检查复用相同的进程身份规则；实际卸载由待卸载组件启动或运行在其服务 cgroup 中时停止，预览仅警告后继续
4. 在运行官方脚本前，将现有 Aegis `globalcfg` 保存到仅 root 可读的 `/var/backups/uas.*` 目录；配置含符号链接或备份失败时停止
5. 根据 ECS 标识选择入口，下载当前官方 `uninstall.sh`，检查非空与 Bash 语法后通过 Bash 执行。默认在失败时停止；`--force` 的范围见上文
6. 停用服务并确认相关进程停止，强制模式屏蔽已知 systemd 单元以阻止重新激活；调用旧版 `quartz_uninstall.sh` 清理（可通过 `--skip-quartz` 跳过），再确认进程状态、处理允许的挂载并删除已确认的残留文件。强制模式下的普通卸载错误和删除属性障碍按上文规则处理
7. 若指定 `--include-assist`，停止服务和 `assist_daemon`、确认进程退出，再通过 `dpkg --purge` 或 `rpm -e` 卸载软件包，验证包已移除后清理文件与启动项
8. 若指定 `--include-cloudmonitor`，处理 C++、Go、Java 三个历史版本。对于使用 `KillMode=none` 的服务，单纯 `systemctl stop` 可能留下 `argusagent`，因此删除目录前还会独立检查进程。云监控安装命令附带的 LoongCollector 不在此范围内
9. 若指定 `--include-loongcollector`，按官方卸载流程停止 `ilogtaild` 和 `loongcollectord`（systemd 单元通过 `/etc/init.d/loongcollectord stop` 停止），确认进程退出，再删除 systemd 单元、init 脚本、启动链接和 `/usr/local/ilogtail`。官方卸载保留的配置目录 `/etc/ilogtail` 也会删除
10. 验证进程、安装目录、服务与启动项、所选云助手软件包和内核模块，汇总失败并返回相应状态

建议正式执行前先加 `--dry-run` 跑一遍，确认要停止的进程和要删除的文件。

默认仅通过 HTTPS 下载官方脚本：`curl` 限制初始 URL 和重定向协议，GNU Wget 禁止重定向。仅有 BusyBox Wget 时默认拒绝下载；`--allow-insecure-download` 会放宽限制并允许 HTTP 回退。脚本不会主动修改防火墙规则或覆盖 `/etc/motd`。

备份包含 Agent 配置、恢复资料或被屏蔽前的本地服务定义，不是整机快照，也不能自动回滚卸载。请在确认不再需要后自行处理备份。

<div align="right">

[![][back-to-top]](#readme-top)

</div>

## 🧪 实测记录

2026 年 10 月，在阿里云 ECS 公共镜像上逐一实测，覆盖 11 个发行版的 30 个版本，并包含 aarch64 架构。每组参数都按「预演、实跑、重跑」三步执行，前后核对进程、服务、文件和软件包，确认卸载干净，SSH、网络和 cloud-init 均不受影响。

### 覆盖范围

下表列出各系统上实测卸载干净的组件，首跑和重跑均成功：

| 发行版 | 版本 | 已验证的组件 |
| --- | --- | --- |
| Alibaba Cloud Linux | 2 | 云安全中心、云助手 |
| Alibaba Cloud Linux | 3、4、4 Deb 版 | 云安全中心、云助手、云监控、LoongCollector |
| Alibaba Cloud Linux | 3（aarch64） | 云安全中心、云助手、云监控 |
| Anolis OS | 7.9、8.10 | 云安全中心、云助手 |
| CentOS | 7.9、8.5 | 云安全中心、云助手 |
| CentOS Stream | 9 | 云安全中心、云助手、云监控 |
| Rocky Linux | 8.10 | 云安全中心、云助手 |
| Rocky Linux | 9.8 | 云安全中心 |
| Rocky Linux | 10.2 | 云安全中心、云助手、云监控、LoongCollector |
| AlmaLinux | 8.10 | 云安全中心、云助手 |
| AlmaLinux | 9.8 | 云安全中心、云助手、云监控 |
| AlmaLinux | 10.2 | 云安全中心 |
| Fedora | 44 | 云安全中心、云助手、云监控 |
| Fedora CoreOS | 34 | 云安全中心、云助手 |
| openSUSE Leap | 15.6 | 云安全中心、云助手、云监控、LoongCollector |
| openSUSE Leap | 16.0 | 云安全中心、云助手 |
| Debian | 10、11、13 | 云安全中心、云助手 |
| Debian | 12 | 云安全中心 |
| Ubuntu | 14.04、16.04、18.04、20.04 | 云安全中心、云助手 |
| Ubuntu | 22.04、24.04 | 云安全中心、云助手、云监控 |
| Ubuntu | 26.04 | 云安全中心、云助手、云监控、LoongCollector |

### 实测发现

- **客户端自保护**：购买 ECS 时开启安全加固，自保护默认开启，这时无法卸载云安全中心 Agent。脚本会停下并说明原因，不改动系统。在云安全中心关闭防御模式，或把服务器移出保护范围，约 1 分钟后重跑即可完成。只暂停防护不够。
- **中断后重跑**：因自保护等原因没能完成时，脚本留下的临时屏蔽会在之后成功的运行中自动收回，不需要手动处理。
- **ARM 实例**：aarch64 上的自保护不会阻止卸载。
- **LoongCollector**：新版云监控默认附带安装它。只加 `--include-cloudmonitor` 不会动它，需要一并卸载时再加 `--include-loongcollector`。
- **开机自动更新**：Debian 和 Ubuntu 系镜像刚开机时可能正在自动安装更新，脚本会等更新结束再卸载云助手。
- **老系统**：Ubuntu 14.04（Upstart）可以正常卸载。CentOS 6 自带的工具版本过旧，脚本会直接提示并退出，不改动系统。

尚未实测：Alpine（阿里云没有 Alpine 公共镜像，云安全中心也不支持），以及 OpenRC 等其他非 systemd 初始化系统。

<div align="right">

[![][back-to-top]](#readme-top)

</div>

## 🛠 故障排查

### 官方卸载脚本执行失败

如果官方脚本返回失败，优先检查云安全中心控制台中的以下保护项是否已经关闭：

- **客户端自保护**（Agent Protection）
- **恶意主机行为防御**（Malicious Host Behavior Prevention）

默认模式下，官方脚本返回非零时停止后续本地清理。状态码 `6` 表示可能仍有自保护；按「前置条件」中的路径关闭防御模式或移出保护范围，约 1 分钟后重新执行。需要尝试本地清理时，明确添加 `--force`，并按退出状态和残留报告判断结果。

### 提示 Non-interactive stdin detected

通过 `curl ... | sudo bash` 执行时，标准输入不是终端，无法交互确认，需要加 `-y`。

### 提示 Run from an SSH session or a detached unit

脚本由待卸载组件的进程启动，或运行在其服务 cgroup 中时（例如加 `--include-assist` 后通过云助手远程命令执行），停止该服务可能连同脚本一起终止。实际卸载会在修改组件前退出；`--dry-run` 可以警告后继续预览。正式执行请通过 SSH 登录，或用 `systemd-run` 在独立单元中运行，再通过日志查看结果：

```bash
systemd-run --unit=uas /bin/bash /root/UAS.sh -y --include-assist
```

```bash
journalctl -u uas -f
```

### 官方卸载脚本下载失败

常见原因包括：

- 服务器网络出站受限
- DNS 解析异常
- 当前环境无法访问阿里云卸载入口
- 系统缺少 CA 证书，导致 HTTPS 校验失败

建议先安装系统 CA 证书后重试，例如：

```bash
# Debian / Ubuntu
apt-get update && apt-get install -y ca-certificates

# CentOS / RHEL
yum install -y ca-certificates
```

Alpine 请优先安装 `curl` 和 CA 证书。若仅能使用 BusyBox Wget，或明确接受 HTTP 下载可被篡改的风险，可以显式添加 `--allow-insecure-download`；该选项不会绕过安装目录检查或内核保护。

### 操作超时或任务被中断

检查日志中失败的命令，再根据情况调整 `--timeout`。该参数限制单个外部操作，不是整次卸载的总时限；多次下载和多个清理步骤的总耗时可能更长。外部卸载已经进行的修改不会自动恢复，重新执行前先查看残留和备份。

若强制清理期间屏蔽过 systemd 单元，失败后检查日志中的 mask 状态和 `/var/backups/uas-units.*` 备份位置。脚本不会因为退出就自动恢复定义或启动服务，重新执行前应先确认当前状态。之后的运行在对应组件清理成功后会收回这些 mask。

### 挂载或文件属性仍阻止清理

强制模式只尝试上文列出的挂载和 `i` / `a` 属性修复。未知挂载、挂载身份变化、`umount` 后挂载仍存在、缺少修复工具或内核拒绝操作，都会让相应清理失败。按日志中的具体路径排查后，再决定如何处理剩余项目。

### 卸载后仍有相关进程

如果脚本结束后仍然发现相关进程，通常表示自保护仍然生效，或进程尚未完全退出。建议在关闭保护项后重新执行一次。

如果仅剩 `AliSecGuard` 等相关内核模块，脚本返回 `3`，不把这种状态报告为完全卸载。脚本不会强行卸载模块或自动重启；安排维护窗口，按官方要求处理后重新检查，不能仅凭一次重启就假定没有残留。

### 卸载云助手后的影响

停止云助手会中断 Workbench 免密会话和会话管理（Session Manager）连接，建议先通过 SSH 或 VNC 登录再执行。卸载后，控制台中发送远程命令等依赖云助手的功能将不可用。

### 卸载后立即重装失败

阿里云官方文档说明，卸载后 24 小时内为冷却期。期间重新执行安装命令，云端策略会识别并自动卸载新装的客户端，请在冷却期结束后再安装。

### 本地检查与测试

在仓库目录运行：

```bash
bash -n UAS.sh
shellcheck UAS.sh
uv run --no-project python -m unittest discover -s tests -v
```

测试使用临时目录和模拟命令，不需要连接服务器或执行真实卸载；它们不能替代各发行版和 Agent 版本的真实环境验证。推送到 `main` 和提交 Pull Request 时，CI 会在 Ubuntu 上运行同样的检查。

<div align="right">

[![][back-to-top]](#readme-top)

</div>

## 🔗 相关项目

- [Uninstall Tencent Service][uts-link]：本项目的腾讯云版本。一键卸载腾讯云主机安全（云镜 YunJing）Agent，可选同时卸载云监控（BaradAgent / Sgagent）和自动化助手（TAT），同样先调用官方卸载程序再清理残留，并在腾讯云多个发行版上实测过。

<div align="right">

[![][back-to-top]](#readme-top)

</div>

## 📚 参考资料

- [阿里云：卸载云安全中心客户端][doc-uninstall-link]
- [阿里云：安装云安全中心客户端][doc-install-link]
- [阿里云：启动、停止或卸载云助手客户端][doc-assist-link]
- [阿里云：安装和卸载云监控插件][doc-cloudmonitor-link]
- [阿里云：管理 LoongCollector][doc-loongcollector-link]

<div align="right">

[![][back-to-top]](#readme-top)

</div>

## 📝 许可证

Copyright © 2018-present [Babywbx][profile-link].<br/>
本项目基于 [MIT](./LICENSE) 许可证发布。

<!-- LINK GROUP -->

[back-to-top]: https://img.shields.io/badge/-BACK_TO_TOP-151515?style=flat-square
[console-link]: https://yundun.console.aliyun.com
[doc-assist-link]: https://help.aliyun.com/zh/ecs/user-guide/start-stop-or-uninstall-the-cloud-assistant-agent
[doc-cloudmonitor-link]: https://help.aliyun.com/zh/cms/cloudmonitor-1-0/user-guide/install-and-uninstall-the-cloudmonitor-agent-for-cpp
[doc-install-link]: https://help.aliyun.com/zh/security-center/user-guide/install-the-security-center-agent
[doc-loongcollector-link]: https://help.aliyun.com/zh/sls/loongcollector-management-linux
[doc-uninstall-link]: https://help.aliyun.com/zh/security-center/user-guide/uninstall-the-security-center-agent
[github-ci-link]: https://github.com/babywbx/Uninstall-Aliyun-Service/actions/workflows/ci.yml
[github-ci-shield]: https://img.shields.io/github/actions/workflow/status/babywbx/Uninstall-Aliyun-Service/ci.yml?branch=main&label=CI&labelColor=black&style=flat-square
[github-contributors-link]: https://github.com/babywbx/Uninstall-Aliyun-Service/graphs/contributors
[github-contributors-shield]: https://img.shields.io/github/contributors/babywbx/Uninstall-Aliyun-Service?color=c4f042&labelColor=black&style=flat-square
[github-forks-link]: https://github.com/babywbx/Uninstall-Aliyun-Service/network/members
[github-forks-shield]: https://img.shields.io/github/forks/babywbx/Uninstall-Aliyun-Service?color=8ae8ff&labelColor=black&style=flat-square
[github-issues-link]: https://github.com/babywbx/Uninstall-Aliyun-Service/issues
[github-issues-shield]: https://img.shields.io/github/issues/babywbx/Uninstall-Aliyun-Service?color=ff80eb&labelColor=black&style=flat-square
[github-lastcommit-link]: https://github.com/babywbx/Uninstall-Aliyun-Service/commits/main
[github-lastcommit-shield]: https://img.shields.io/github/last-commit/babywbx/Uninstall-Aliyun-Service?labelColor=black&style=flat-square
[github-license-link]: https://github.com/babywbx/Uninstall-Aliyun-Service/blob/main/LICENSE
[github-license-shield]: https://img.shields.io/github/license/babywbx/Uninstall-Aliyun-Service?color=white&labelColor=black&style=flat-square
[github-stars-link]: https://github.com/babywbx/Uninstall-Aliyun-Service/stargazers
[github-stars-shield]: https://img.shields.io/github/stars/babywbx/Uninstall-Aliyun-Service?color=ffcb47&labelColor=black&style=flat-square
[profile-link]: https://github.com/babywbx
[uts-link]: https://github.com/babywbx/Uninstall-Tencent-Service
