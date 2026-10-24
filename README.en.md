<div align="center"><a name="readme-top"></a>

# Uninstall Aliyun Service

A Bash script to uninstall the Alibaba Cloud Security Center (YunDun) agent on Linux<br/>
and clean up legacy component leftovers, with optional Cloud Assistant, CloudMonitor, and LoongCollector removal.

[简体中文](./README.md) · [Report Issue][github-issues-link] · [Documentation][doc-uninstall-link]

<!-- SHIELD GROUP -->

[![][github-stars-shield]][github-stars-link]
[![][github-forks-shield]][github-forks-link]
[![][github-issues-shield]][github-issues-link]
[![][github-license-shield]][github-license-link]<br/>
[![][github-contributors-shield]][github-contributors-link]
[![][github-lastcommit-shield]][github-lastcommit-link]
[![][github-ci-shield]][github-ci-link]

</div>

<details>
<summary><kbd>Table of contents</kbd></summary>

#### TOC

- [📋 Overview](#-overview)
- [⚠️ Prerequisites](#️-prerequisites)
- [🚀 Quick Start](#-quick-start)
- [📖 Usage](#-usage)
- [🔩 How It Works](#-how-it-works)
- [🛠 Troubleshooting](#-troubleshooting)
- [📚 References](#-references)
- [📝 License](#-license)

####

<br/>

</details>

## 📋 Overview

This project targets Linux hosts that may still contain historical YunDun / Aegis components. The script prefers the official Alibaba Cloud uninstall flow and adds cleanup for common legacy remnants such as `quartz` and `agentwatch`. Optional flags also remove Cloud Assistant (`aliyun-service` / `assist_daemon`), CloudMonitor (`argusagent` / `CmsGoAgent`), and LoongCollector (`loongcollectord` / `ilogtaild`). The current official CloudMonitor install command also installs LoongCollector, but LoongCollector is also the Simple Log Service (SLS) collection agent, so `--include-cloudmonitor` does not remove it; add `--include-loongcollector` as well.

Typical use cases:

- 🛡️ Remove the Security Center agent (formerly Aegis / AnQiShi)
- 🧹 Clean up older YunDun components that may still be installed on the host
- 🤖 Remove Cloud Assistant (`assist_daemon`)
- 📊 Remove CloudMonitor (`argusagent` / `CmsGoAgent`)
- 🪵 Remove LoongCollector (the Simple Log Service agent, which may come with CloudMonitor)
- 📦 Run one script for both official uninstall and leftover cleanup instead of doing it manually
- 🖥️ Strip related components from non-ECS or decommissioned servers

<div align="right">

[![][back-to-top]](#readme-top)

</div>

## ⚠️ Prerequisites

Before running the script, make sure that:

1. The target system is Linux with `bash` installed (minimal systems such as Alpine need it installed first)
2. You run it as `root` or with equivalent `sudo` privileges
3. `awk`, `readlink`, `stat`, `grep`, `cksum`, `find`, `flock`, and a `timeout` implementation supporting `-k` are installed, and Linux `/proc` is readable
4. `curl` or GNU Wget is installed, and the host can reach Alibaba Cloud uninstall endpoints over HTTPS. On Alpine, install `curl`; BusyBox `wget` alone is rejected by default

The script checks dependencies but does not install them. Install GNU coreutils if `timeout` is missing; `flock` is usually provided by util-linux. A dry run still needs the local inspection tools, but does not download official scripts.

The optional force-mode dependencies are `lsattr`, `chattr`, and `umount`. The first two are needed only to repair blocking attributes after deletion fails. `umount` is needed only for recognized agent mounts. These tools are not installed automatically either.

> \[!IMPORTANT]
>
> For the official command-line uninstall flow, disable these protections in the [Security Center console][console-link] first:
>
> - **Agent Protection**: under **System Configuration** → **Feature Settings** → **Agent Settings**, turn off **Defense Mode**, or remove the server from its protection scope. Pausing protection alone does not disable it
> - **Malicious Host Behavior Prevention**
>
> The change usually takes effect within a minute. `--force` can attempt scoped local cleanup after the official uninstall fails. It does not bypass kernel self-protection or guarantee removal while protection is enabled.

### Supported Systems

The table describes system interfaces and installation paths covered by the code. Automated tests use fixtures and mocked commands. There is no completed live uninstall matrix for these distributions, so the table does not mean every system, version, and agent combination has been verified:

| Category | Coverage |
| --- | --- |
| RPM-based | Alibaba Cloud Linux, CentOS, RHEL, Rocky Linux, AlmaLinux, Fedora, openSUSE; removes the Cloud Assistant package with `rpm -e` |
| DEB-based | Debian, Ubuntu; uses `dpkg --purge` for the exact Cloud Assistant package, without using `apt-get` to remove dependent packages |
| Init systems | systemd, SysVinit (`chkconfig` / `update-rc.d`), OpenRC (such as Alpine), Upstart |
| Install paths | Standard `/usr/local/...` paths, plus the `/opt/...` paths used on CoreOS / Flatcar |
| CPU architectures | CloudMonitor Go binaries are selected for x86_64, aarch64 / arm64, and i386 variants; unknown architectures are not treated as 32-bit x86 |
| Bash version | Retains Bash 4.2 syntax compatibility; the host must still provide the tools listed above |

<div align="right">

[![][back-to-top]](#readme-top)

</div>

## 🚀 Quick Start

Download and inspect the script first, then preview and execute it. The last command asks for confirmation:

```bash
curl --proto '=https' --proto-redir '=https' -fsSL https://raw.githubusercontent.com/babywbx/Uninstall-Aliyun-Service/main/UAS.sh -o UAS.sh
less UAS.sh
sudo bash UAS.sh --dry-run
sudo bash UAS.sh
```

Non-interactive mode (skip confirmation):

```bash
curl --proto '=https' --proto-redir '=https' -fsSL https://raw.githubusercontent.com/babywbx/Uninstall-Aliyun-Service/main/UAS.sh | sudo bash -s -- -y
```

Also remove Cloud Assistant:

```bash
sudo bash UAS.sh -y --include-assist
```

Also remove CloudMonitor:

```bash
sudo bash UAS.sh -y --include-cloudmonitor
```

LoongCollector installed alongside CloudMonitor must be selected separately:

```bash
sudo bash UAS.sh -y --include-cloudmonitor --include-loongcollector
```

Remove every component, with a dry run first:

```bash
sudo bash UAS.sh --dry-run --include-assist --include-cloudmonitor --include-loongcollector
```

Then run it for real:

```bash
sudo bash UAS.sh -y --include-assist --include-cloudmonitor --include-loongcollector
```

> \[!TIP]
>
> If `raw.githubusercontent.com` is unreachable, use the jsDelivr CDN mirror instead:
>
> ```bash
> curl --proto '=https' --proto-redir '=https' -fsSL https://cdn.jsdelivr.net/gh/babywbx/Uninstall-Aliyun-Service@main/UAS.sh | sudo bash -s -- -y
> ```

<div align="right">

[![][back-to-top]](#readme-top)

</div>

## 📖 Usage

```bash
sudo bash UAS.sh [options]
```

### Options

| Flag | Description |
| --- | --- |
| `-y`, `--yes` | Run without confirmation |
| `--include-assist` | Also uninstall Cloud Assistant (`aliyun-service` / `assist_daemon`) |
| `--include-cloudmonitor` | Also uninstall CloudMonitor (`argusagent` / `CmsGoAgent`), excluding LoongCollector |
| `--include-loongcollector` | Also uninstall LoongCollector (`loongcollectord` / `ilogtaild`, `/usr/local/ilogtail`, `/etc/ilogtail`). The current official CloudMonitor install command also installs it |
| `--skip-quartz` | Skip legacy quartz cleanup |
| `--allow-insecure-download` | Permit HTTP fallback and BusyBox Wget downloads, relaxing the default download restrictions |
| `--dry-run` | Preview local cleanup without downloads, a temporary work directory, or installation changes |
| `--force` | Still try local cleanup after an ordinary official failure or status `6`; continue to the process check when a component's own stop command fails, and send KILL to confirmed user-space processes that survive TERM (except `AliSecGuard`) |
| `--timeout SECONDS` | Limit managed uninstall commands to `1` through `3600` seconds, default `120`. After a timeout, allow a `5` second grace period before sending KILL. Downloads also have separate connection and transfer timeouts |
| `-h`, `--help` | Show help |

### Output

Progress is grouped by component (environment, Security Center, Cloud Assistant, CloudMonitor, LoongCollector, verification), and each line carries an `[INFO]`, `[ OK ]`, `[WARN]`, or `[FAIL]` tag. Colors are enabled on capable terminals and turned off automatically when output is redirected, `TERM` is `dumb`, or the `NO_COLOR` environment variable is set.

In `--dry-run` mode, local actions start with `[DRY-RUN]` and show matched processes and existing files. Official scripts are only listed as planned steps because a preview does not download or execute them.

### Scope of forced local cleanup

```bash
sudo bash UAS.sh -y --force --timeout 120
```

By default, a nonzero official uninstall result stops subsequent local cleanup. `--force` allows an attempt after ordinary failures or status `6`, but the script still stops if the official step times out or is interrupted by a signal. It targets confirmed installation paths for the selected components rather than using broad process-name matches.

If legacy `quartz_uninstall.sh` returns an ordinary error, force mode also checks that the related processes have stopped before attempting local cleanup. A timeout or signal interruption does not trigger this fallback. Newly appearing agent processes are checked again during the stopping stage.

For known systemd units belonging to selected components, force mode stops the units, then masks them to prevent activation. An existing definition in `/etc/systemd/system` is first backed up to a root-only `/var/backups/uas-units.*` directory, and its location is logged. Masks created by this run remain if that component's cleanup fails, and are removed only after its files have been cleaned successfully. Existing masks are preserved. Later kernel-module checks can still return `3`, so not every nonzero exit leaves the new masks in place. The script does not automatically restore definitions or restart services.

If deleting a selected installation path or service file fails, force mode inspects its attributes, clears only detected `i` (immutable) and `a` (append-only) flags, then retries deletion once. The same scoped repair applies when these attributes prevent replacing an already backed-up local service definition with a mask. Attribute repair skips symlinks and refuses to modify mounted files or regular files with multiple hard links. It does not change other attributes or paths outside the selected scope. A deletion or replacement timeout or signal interruption does not trigger repair. A dry run does not change attributes or simulate repairs that are conditional on a real failure.

After related processes have stopped, force mode can unmount kernel pseudo filesystems at these exact locations. The agent root must be `/usr/local/aegis` or `/opt/aegis`. Parent-directory symlinks are supported, but the mount point must remain inside the resolved installation directory:

| Location below the agent root | Allowed filesystem types |
| --- | --- |
| `aegis_debug` | `debugfs`, `tracefs` |
| `cgroup` | `cgroup`, `cgroup2` |
| `cgroup/cpu` | `cgroup`, `cgroup2` |

The mount root must be `/`. The script inspects the complete list first and stops for other locations, filesystem types, unknown nested mounts, or stacked mounts. It then uses ordinary `umount` from deepest to shallowest, without `-f`, `-l`, or recursive unmounting. Before and after each operation, it checks the original records, including mount ID and root, and confirms that mounts are gone at the end. A dry run only lists the plan. Linux `mountinfo` does not retain bind origins, so a bind of an entire kernel pseudo filesystem at an allowed location cannot reliably be distinguished from a normal mount. Such binds cannot be ruled out.

The local fallback never sends any signal to `AliSecGuard`, and does not force kernel modules out with `rmmod`, change console protection settings, or reboot the host. The official script still performs its vendor-defined driver cleanup. Installation files are preserved when their processes cannot be stopped. Active protection, unsafe paths, or detected leftovers prevent a successful result. The official script may already have made partial changes; stopping later cleanup does not roll them back.

### Temporary background execution

Download and inspect the script first. Open a root shell in the directory containing `UAS.sh`, then run:

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

This creates a log directory accessible only to root and does not install a persistent service. Remove optional component flags as needed. A PID from `nohup` means the task started, not that removal succeeded. Read `output.log` and the `exit-code` file written on completion. If `exit-code` is absent, check the process and log to determine whether the task is running or was interrupted. An exclusive lock rejects another concurrent uninstall instance.

### Exit status

| Status | Meaning |
| --- | --- |
| `0` | Local uninstall verification passed for the selected components, or a dry run completed |
| `1` | A prerequisite, cleanup step, or verification failed; inspect failed operations and leftovers |
| `3` | Local checks still found related kernel modules; arrange maintenance and check again |
| `6` | In default mode, the official uninstall reported possible active self-protection |
| `124` | The official uninstall step timed out; subsequent local cleanup was not started |

Other nonzero official exit codes may also be returned unchanged. Interruptions typically return `130` or `143`. A `0` result in force mode verifies local cleanup only, not the cloud-side state.

<div align="right">

[![][back-to-top]](#readme-top)

</div>

## 🔩 How It Works

By default, the script performs the following steps:

1. Checks Linux and root privileges, identifies the distribution, and prompts for confirmation unless `-y` or `--dry-run` is used
2. Checks tool dependencies and `/proc`; a real run also acquires an exclusive lock and creates a private temporary directory
3. Checks selected installation directories and rejects directories that are symlinks themselves or are not owned by root. Mounts are rejected by default; force mode accepts only the allowlist above. Symlinked parents such as `/opt` on Fedora CoreOS are checked, and processes matched, by their real path. A nonempty `/opt/aegis` without `aegis_client`, `aegis_update`, or `globalcfg` is treated as unrelated software and stops the run. Launcher checks use the same process identity rules: a real uninstall stops when launched by, or running inside the service cgroup of, a selected component; a dry run warns and continues
4. Before invoking official scripts, preserves existing Aegis `globalcfg` data in a root-only `/var/backups/uas.*` directory; configuration symlinks or a failed backup stop the run
5. Picks an endpoint from ECS identification, downloads the current official `uninstall.sh`, checks that it is nonempty and passes Bash syntax validation, then runs it through Bash. Failures stop the default flow; see the force-mode scope above
6. Disables services and confirms their processes stopped; force mode masks known systemd units to prevent activation. It runs legacy `quartz_uninstall.sh` cleanup (skippable with `--skip-quartz`), rechecks processes, handles allowed mounts, then removes confirmed leftovers. Force-mode handling of ordinary uninstall errors and blocking file attributes follows the rules above
7. With `--include-assist`, stops services and `assist_daemon`, confirms processes exited, removes packages through `dpkg --purge` or `rpm -e`, verifies package removal, then cleans files and startup entries
8. With `--include-cloudmonitor`, handles C++, Go, and Java versions. For services using `KillMode=none`, `systemctl stop` alone can leave `argusagent` running, so processes are checked separately before directories are removed. LoongCollector installed by the CloudMonitor command is outside this scope
9. With `--include-loongcollector`, follows the official uninstall flow: stops `ilogtaild` and `loongcollectord` (the systemd unit stops through `/etc/init.d/loongcollectord stop`), confirms the processes exited, then removes the systemd units, init scripts, startup links, and `/usr/local/ilogtail`. It also removes `/etc/ilogtail`, which the official uninstall keeps
10. Verifies processes, installation directories, services and startup entries, selected Cloud Assistant packages, and kernel modules; reports failures through its final status

Run once with `--dry-run` first to review the processes and files the script would touch.

Official scripts are downloaded over HTTPS by default. `curl` restricts both initial and redirect protocols; GNU Wget rejects redirects. BusyBox Wget alone is rejected unless `--allow-insecure-download` relaxes these restrictions and permits HTTP fallback. The script does not change firewall rules or overwrite `/etc/motd`.

Backups contain agent configuration, recovery data, or local service definitions saved before masking. They are not whole-system snapshots and do not provide automatic rollback. Remove them yourself after confirming they are no longer needed.

<div align="right">

[![][back-to-top]](#readme-top)

</div>

## 🛠 Troubleshooting

### The official uninstall script fails

First verify that the following protections are disabled in the Security Center console:

- **Agent Protection**
- **Malicious Host Behavior Prevention**

By default, a nonzero official result stops subsequent local cleanup. Status `6` indicates possible active self-protection; turn off defense mode or remove the server from the protection scope as described in the prerequisites, then retry after about a minute. To attempt local cleanup, explicitly add `--force` and judge the result from the exit status and remaining-items report.

### "Non-interactive stdin detected"

When run as `curl ... | sudo bash`, standard input is not a terminal, so the script cannot ask for confirmation. Add `-y`.

### "Run from an SSH session or a detached unit"

When the script is started by a process of a component selected for removal, or runs inside that component's service cgroup (for example, a Cloud Assistant remote command with `--include-assist`), stopping the service could also terminate the script. A real uninstall exits before changing components; `--dry-run` can warn and continue the preview. For an actual uninstall, log in over SSH or start it in a separate unit with `systemd-run`, then follow the log:

```bash
systemd-run --unit=uas /bin/bash /root/UAS.sh -y --include-assist
```

```bash
journalctl -u uas -f
```

### The official uninstall script cannot be downloaded

Common causes include:

- Outbound network restrictions on the server
- DNS resolution issues
- The host cannot reach Alibaba Cloud uninstall endpoints
- Missing CA certificates on the system, causing HTTPS validation to fail

Install CA certificates first, then retry. For example:

```bash
# Debian / Ubuntu
apt-get update && apt-get install -y ca-certificates

# CentOS / RHEL
yum install -y ca-certificates
```

On Alpine, prefer installing `curl` and CA certificates. If only BusyBox Wget is available, or you explicitly accept that HTTP downloads can be altered in transit, use `--allow-insecure-download`. This option does not bypass installation-path checks or kernel protection.

### An operation timed out or the task was interrupted

Inspect the failed command in the log before adjusting `--timeout`. It limits each external operation, not the total uninstall duration; multiple downloads and cleanup steps can take longer in total. Changes already made by external uninstallers are not rolled back automatically. Review leftovers and backups before retrying.

If force cleanup masked systemd units, inspect the logged mask state and `/var/backups/uas-units.*` backup locations after a failure. Exiting does not automatically restore definitions or start services. Confirm the current state before retrying.

### Mounts or file attributes still prevent cleanup

Force mode attempts only the mounts and `i` / `a` attribute repairs described above. Unknown mounts, changed mount identities, mounts remaining after `umount`, missing repair tools, or a kernel refusal cause the affected cleanup to fail. Inspect the exact path in the log before deciding how to handle the remaining items.

### Related processes are still running after uninstall

This usually means self-protection is still active, or the processes have not fully exited yet. Disable the protection features and run the script again.

If only related kernel modules such as `AliSecGuard` remain, the script returns `3` instead of reporting a complete uninstall. It does not force module removal or reboot automatically. Arrange a maintenance window, follow the official procedure, and check again; a reboot alone is not proof that no remnants remain.

### Effects of removing Cloud Assistant

Stopping Cloud Assistant ends Workbench passwordless sessions and Session Manager connections, so log in over SSH or VNC before running the script. After removal, console features that depend on Cloud Assistant, such as sending remote commands, stop working.

### Reinstall fails shortly after uninstall

Alibaba Cloud documentation describes a 24-hour cooldown after uninstall. If you run the install command during that window, a cloud-side policy detects the new agent and uninstalls it automatically. Wait until the cooldown ends before reinstalling.

### Local checks and tests

From the repository directory, run:

```bash
bash -n UAS.sh
shellcheck UAS.sh
uv run --no-project python -m unittest discover -s tests -v
```

Tests use temporary directories and mocked commands. They do not require a server connection or a real uninstall, and do not replace validation against real distributions and agent versions. CI runs the same checks on Ubuntu for pushes to `main` and for pull requests.

<div align="right">

[![][back-to-top]](#readme-top)

</div>

## 📚 References

- [Alibaba Cloud: Uninstall the Security Center agent][doc-uninstall-link]
- [Alibaba Cloud: Install the Security Center agent][doc-install-link]
- [Alibaba Cloud: Stop and uninstall Cloud Assistant agent][doc-assist-link]
- [Alibaba Cloud: Install and uninstall CloudMonitor agent][doc-cloudmonitor-link]
- [Alibaba Cloud: Manage LoongCollector][doc-loongcollector-link]

<div align="right">

[![][back-to-top]](#readme-top)

</div>

## 📝 License

Copyright © 2018-present [Babywbx][profile-link].<br/>
This project is licensed under [MIT](./LICENSE).

<!-- LINK GROUP -->

[back-to-top]: https://img.shields.io/badge/-BACK_TO_TOP-151515?style=flat-square
[console-link]: https://yundun.console.aliyun.com
[doc-assist-link]: https://www.alibabacloud.com/help/en/ecs/user-guide/stop-and-uninstall-the-cloud-assistant-agent
[doc-cloudmonitor-link]: https://www.alibabacloud.com/help/en/cms/cloudmonitor-1-0/user-guide/install-and-uninstall-the-cloudmonitor-agent-for-cpp
[doc-install-link]: https://www.alibabacloud.com/help/en/security-center/user-guide/install-the-security-center-agent
[doc-loongcollector-link]: https://www.alibabacloud.com/help/en/sls/loongcollector-management-linux
[doc-uninstall-link]: https://www.alibabacloud.com/help/en/security-center/user-guide/uninstall-the-security-center-agent
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
