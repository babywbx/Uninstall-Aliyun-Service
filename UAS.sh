#!/usr/bin/env bash

set -euo pipefail

readonly SCRIPT_NAME="Uninstall-aliyun-service"
WORKDIR=""
readonly DEFAULT_TIMEOUT=15
COMMAND_TIMEOUT=120
FORCE=0
FAILURES=0
RUN_PID=""
LOCK_DIR="/run/uas.lock"
PROC_ROOT="/proc"
SYS_ROOT="/sys"
BACKUP_ROOT="/var/backups"
AEGIS_DIRS=(/usr/local/aegis /opt/aegis)
ASSIST_DIRS=(/usr/local/share/aliyun-assist /usr/local/share/assist-daemon /opt/local/share/aliyun-assist /opt/local/share/assist-daemon)
MONITOR_DIRS=(/usr/local/cloudmonitor /opt/cloudmonitor)

AUTO_YES=0
SKIP_QUARTZ=0
INCLUDE_ASSIST=0
INCLUDE_CLOUDMONITOR=0
ALLOW_INSECURE_DOWNLOAD=0
DRY_RUN=0

DISTRO_PRETTY="unknown"

if [[ -t 1 && -z "${NO_COLOR:-}" && "${TERM:-dumb}" != "dumb" ]]; then
  C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'
  C_BLUE=$'\033[34m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_RED=$'\033[31m'
else
  C_RESET=''; C_BOLD=''
  C_BLUE=''; C_GREEN=''; C_YELLOW=''; C_RED=''
fi
readonly C_RESET C_BOLD C_BLUE C_GREEN C_YELLOW C_RED

cleanup() {
  if [[ -n "${WORKDIR}" ]]; then
    rm -rf -- "${WORKDIR}"
  fi
}

interrupt() {
  trap '' INT TERM
  if [[ -n "${RUN_PID}" ]]; then
    kill -TERM "${RUN_PID}" 2>/dev/null || true
    wait "${RUN_PID}" 2>/dev/null || true
  fi
  exit "$1"
}

usage() {
  cat <<'EOF'
Usage: ./UAS.sh [options]

Options:
  -y, --yes                Run without interactive confirmation
      --include-assist     Also uninstall Cloud Assistant (assist_daemon)
      --include-cloudmonitor Also uninstall CloudMonitor (argusagent / CmsGoAgent)
      --skip-quartz        Skip legacy quartz cleanup
      --allow-insecure-download Allow fallback to HTTP when HTTPS download fails
      --dry-run            Show what would be stopped or removed, change nothing
      --force              Escalate scoped process, service and file cleanup
      --timeout SECONDS    Timeout for managed commands (default: 120)
  -h, --help              Show this help message
EOF
}

log() {
  printf '%s[INFO]%s %s\n' "${C_BLUE}" "${C_RESET}" "$*"
}

warn() {
  printf '%s[WARN]%s %s\n' "${C_YELLOW}" "${C_RESET}" "$*" >&2
}

die() {
  printf '%s[FAIL]%s %s\n' "${C_RED}" "${C_RESET}" "$*" >&2
  exit 1
}

ok() {
  printf '%s[ OK ]%s %s\n' "${C_GREEN}" "${C_RESET}" "$*"
}

section() {
  printf '\n%s==>%s %s%s%s\n' "${C_BOLD}${C_BLUE}" "${C_RESET}" "${C_BOLD}" "$*" "${C_RESET}"
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

run() {
  if [[ "${DRY_RUN}" -eq 0 ]]; then
    local rc=0
    timeout -k 5 "${COMMAND_TIMEOUT}" "$@" </dev/null 9>&- &
    RUN_PID=$!
    wait "${RUN_PID}" || rc=$?
    RUN_PID=""
    if [[ "${rc}" -ne 0 ]]; then
      warn "Command failed (${rc}):$(printf ' %q' "$@")"
    fi
    return "${rc}"
  fi

  printf '[DRY-RUN]' >&3
  printf ' %q' "$@" >&3
  printf '\n' >&3
}

record_failure() {
  warn "$*"
  FAILURES=1
}

require_linux() {
  if [[ "$(uname -s)" != Linux ]]; then
    die "Only Linux is supported. No uninstall was attempted."
  fi
}

prepare_runtime() {
  local tool=""
  for tool in awk readlink stat grep cksum find timeout flock; do
    command_exists "${tool}" || die "Required command missing: ${tool}. Install it before retrying."
  done
  timeout -k 1 1 true || die "timeout must support -k. Install GNU coreutils."
  [[ -r "${PROC_ROOT}/self/mountinfo" && -r "${PROC_ROOT}/self/status" ]] || die "A readable Linux /proc is required."
  [[ "${DRY_RUN}" -eq 0 ]] || return 0
  [[ -d /run ]] || LOCK_DIR="/var/run/uas.lock"
  if [[ ! -e "${LOCK_DIR}" && ! -L "${LOCK_DIR}" ]]; then
    mkdir -m 700 -- "${LOCK_DIR}" || die "Cannot create ${LOCK_DIR}."
  fi
  [[ -d "${LOCK_DIR}" && ! -L "${LOCK_DIR}" ]] || die "Unsafe lock directory: ${LOCK_DIR}."
  [[ "$(stat -c '%u:%a' "${LOCK_DIR}")" == 0:700 ]] || die "Lock directory must be owned by root with mode 700."
  exec 9<"${LOCK_DIR}"
  flock -n 9 || die "Another UAS instance is already running."
  WORKDIR="$(mktemp -d /tmp/uas.XXXXXX)" || die "Cannot create a private work directory."
  trap cleanup EXIT
  trap 'interrupt 130' INT
  trap 'interrupt 143' TERM
}

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    die "Please run this script as root."
  fi
}

detect_distro() {
  if [[ -r /etc/os-release ]]; then
    DISTRO_PRETTY="$(awk -F= '$1 == "PRETTY_NAME" { sub(/^[^=]*=/, ""); gsub(/^["\047]|["\047]$/, ""); print; exit }' /etc/os-release)"
  elif command_exists lsb_release; then
    DISTRO_PRETTY="$(lsb_release -ds 2>/dev/null)"
  elif [[ -r /etc/redhat-release ]]; then
    DISTRO_PRETTY="$(cat /etc/redhat-release)"
  fi
  DISTRO_PRETTY="${DISTRO_PRETTY:-unknown}"
}

purge_deb() {
  local pkg="$1"
  run env DEBIAN_FRONTEND=noninteractive dpkg --purge "${pkg}"
}

parse_args() {
  while (($# > 0)); do
    case "$1" in
      -y|--yes)
        AUTO_YES=1
        ;;
      --include-assist)
        INCLUDE_ASSIST=1
        ;;
      --include-cloudmonitor)
        INCLUDE_CLOUDMONITOR=1
        ;;
      --skip-quartz)
        SKIP_QUARTZ=1
        ;;
      --allow-insecure-download)
        ALLOW_INSECURE_DOWNLOAD=1
        ;;
      --dry-run)
        DRY_RUN=1
        ;;
      --force)
        FORCE=1
        ;;
      --timeout)
        [[ $# -ge 2 && "$2" =~ ^[1-9][0-9]{0,3}$ ]] || die "--timeout requires 1 to 3600 seconds."
        [[ "$2" -le 3600 ]] || die "--timeout requires 1 to 3600 seconds."
        COMMAND_TIMEOUT="$2"
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        die "Unknown option: $1"
        ;;
    esac
    shift
  done
}

confirm() {
  if [[ "${AUTO_YES}" -eq 1 || "${DRY_RUN}" -eq 1 ]]; then
    return
  fi

  if [[ ! -t 0 ]]; then
    die "Non-interactive stdin detected. Use -y to skip confirmation when piping."
  fi

  printf '%s\n' "======================================================================="
  printf '%s\n' " ${SCRIPT_NAME}"
  printf '%s\n' "======================================================================="
  printf '%s\n' "This script will uninstall the Alibaba Cloud Security Center agent."
  if [[ "${INCLUDE_ASSIST}" -eq 1 ]]; then
    printf '%s\n' "Cloud Assistant (assist_daemon) will also be removed."
  fi
  if [[ "${INCLUDE_CLOUDMONITOR}" -eq 1 ]]; then
    printf '%s\n' "CloudMonitor (argusagent / CmsGoAgent) will also be removed."
  fi
  if [[ "${ALLOW_INSECURE_DOWNLOAD}" -eq 1 ]]; then
    printf '%s\n' "Insecure HTTP download fallback is enabled."
  fi
  if [[ "${FORCE}" -eq 1 ]]; then
    printf '%s\n' "Local fallback and SIGKILL for verified agent processes are enabled."
    printf '%s\n' "Kernel self-protection is not bypassed; protected remnants cause failure."
  fi
  printf '%s\n' "Before continuing, disable Agent Protection and"
  printf '%s\n' "Malicious Host Behavior Prevention in the Security Center console."
  printf '\n'
  printf '%s' "Continue? [y/N] "

  local reply=""
  read -r reply
  if [[ ! "${reply}" =~ ^[Yy]$ ]]; then
    die "Canceled."
  fi
}

download_file() {
  local url="$1"
  local output="$2"

  if command_exists curl; then
    local protocols='=https'
    [[ "${ALLOW_INSECURE_DOWNLOAD}" -eq 0 ]] || protocols='=http,https'
    run curl -fsSL --proto "${protocols}" --proto-redir "${protocols}" \
      --connect-timeout 5 --max-time "${DEFAULT_TIMEOUT}" "${url}" -o "${output}"
    return $?
  fi

  if command_exists wget; then
    if grep -q -- '--max-redirect' < <(wget --help 2>&1); then
      run wget -q --max-redirect=0 --tries=1 -T "${DEFAULT_TIMEOUT}" -O "${output}" "${url}"
    elif [[ "${ALLOW_INSECURE_DOWNLOAD}" -eq 1 ]]; then
      run wget -q -T "${DEFAULT_TIMEOUT}" -O "${output}" "${url}"
    else
      warn "Install curl or GNU Wget for verified HTTPS without downgrade redirects."
      return 1
    fi
    return $?
  fi

  warn "curl or wget is required."
  return 1
}

download_first_available() {
  local output="$1"
  shift

  local url=""
  for url in "$@"; do
    log "Trying ${url}"
    if download_file "${url}" "${output}"; then
      log "Downloaded ${url}"
      return 0
    fi
  done

  return 1
}

detect_ecs() {
  local dmi_path=""
  local dmi_value=""

  for dmi_path in \
    /sys/class/dmi/id/product_name \
    /sys/class/dmi/id/sys_vendor \
    /sys/devices/virtual/dmi/id/product_name \
    /sys/devices/virtual/dmi/id/sys_vendor; do
    if [[ -r "${dmi_path}" ]]; then
      dmi_value="$(<"${dmi_path}")"
      if [[ "${dmi_value}" == *"Alibaba Cloud"* ]]; then
        return 0
      fi
    fi
  done

  return 1
}

run_script() {
  local script_path="$1"
  local description="$2"

  if [[ "${DRY_RUN}" -eq 1 ]]; then
    printf '[DRY-RUN] would run %s\n' "${description}" >&3
    return 0
  fi
  [[ -s "${script_path}" ]] || { warn "Empty script: ${description}."; return 1; }
  bash -n "${script_path}" || { warn "Invalid shell script: ${description}."; return 1; }
  log "Running ${description}"

  local rc=0
  run bash "${script_path}" || rc=$?

  if [[ "${rc}" -ne 0 ]]; then
    if [[ "${rc}" -eq 6 ]]; then
      warn "${description} failed because self-protection may still be enabled."
      warn "Disable Agent Protection and Malicious Host Behavior Prevention, then retry."
    fi
    return "${rc}"
  fi

  return 0
}

run_official_uninstall() {
  local script_path="${WORKDIR}/uninstall.sh"
  local -a urls=()

  if [[ "${DRY_RUN}" -eq 1 ]]; then
    log "Would download, validate and run the current official uninstall.sh."
    return 0
  fi

  if detect_ecs; then
    log "Detected Alibaba Cloud ECS, preferring the official ECS endpoint."
    urls=(
      "https://update2.aegis.aliyun.com/download/uninstall.sh"
      "https://update.aegis.aliyun.com/download/uninstall.sh"
    )
    if [[ "${ALLOW_INSECURE_DOWNLOAD}" -eq 1 ]]; then
      warn "Allowing insecure HTTP fallback for official uninstall download."
      urls+=(
        "http://update2.aegis.aliyun.com/download/uninstall.sh"
        "http://update.aegis.aliyun.com/download/uninstall.sh"
      )
    fi
  else
    log "Using the public uninstall endpoint for a non-ECS server."
    urls=(
      "https://update.aegis.aliyun.com/download/uninstall.sh"
      "https://update2.aegis.aliyun.com/download/uninstall.sh"
    )
    if [[ "${ALLOW_INSECURE_DOWNLOAD}" -eq 1 ]]; then
      warn "Allowing insecure HTTP fallback for official uninstall download."
      urls+=(
      "http://update.aegis.aliyun.com/download/uninstall.sh"
      "http://update2.aegis.aliyun.com/download/uninstall.sh"
      )
    fi
  fi

  if ! download_first_available "${script_path}" "${urls[@]}"; then
    warn "Unable to download the official uninstall.sh script."
    if [[ "${ALLOW_INSECURE_DOWNLOAD}" -eq 0 ]]; then
      warn "HTTPS download failed. Ensure CA certificates are installed, then retry."
      warn "Examples: apt-get install ca-certificates / yum install ca-certificates"
      warn "If you must use HTTP fallback, rerun with --allow-insecure-download."
    fi
    return 1
  fi

  run_script "${script_path}" "official uninstall.sh"
}

run_legacy_quartz_cleanup() {
  local script_path="${WORKDIR}/quartz_uninstall.sh"
  local -a urls=(
    "https://update.aegis.aliyun.com/download/quartz_uninstall.sh"
  )

  if [[ "${SKIP_QUARTZ}" -eq 1 ]]; then
    log "Skipping legacy quartz cleanup."
    return 0
  fi

  if [[ "${DRY_RUN}" -eq 1 ]]; then
    log "Would download, validate and run legacy quartz_uninstall.sh."
    return 0
  fi

  if [[ "${ALLOW_INSECURE_DOWNLOAD}" -eq 1 ]]; then
    warn "Allowing insecure HTTP fallback for legacy quartz cleanup download."
    urls+=("http://update.aegis.aliyun.com/download/quartz_uninstall.sh")
  fi

  if ! download_first_available "${script_path}" "${urls[@]}"; then
    warn "Legacy quartz_uninstall.sh is unavailable, skipping."
    if [[ "${ALLOW_INSECURE_DOWNLOAD}" -eq 0 ]]; then
      warn "If HTTPS is failing because CA certificates are missing, install them and retry."
      warn "If you must use HTTP fallback, rerun with --allow-insecure-download."
    fi
    return 0
  fi

  run_script "${script_path}" "legacy quartz_uninstall.sh"
}

selected_dirs() {
  printf '%s\n' "${AEGIS_DIRS[@]}"
  if [[ "${INCLUDE_ASSIST}" -eq 1 ]]; then
    printf '%s\n' "${ASSIST_DIRS[@]}"
  fi
  if [[ "${INCLUDE_CLOUDMONITOR}" -eq 1 ]]; then
    printf '%s\n' "${MONITOR_DIRS[@]}" /etc/cloudmonitor
  fi
}

selected_services() {
  printf '%s\n' aegis agentwatch
  if [[ "${INCLUDE_ASSIST}" -eq 1 ]]; then
    printf '%s\n' AssistDaemon aliyun aliyun-service
  fi
  if [[ "${INCLUDE_CLOUDMONITOR}" -eq 1 ]]; then
    printf '%s\n' cloudmonitor
  fi
}

path_present() {
  [[ -e "$1" || -L "$1" ]]
}

mount_records() {
  UAS_MOUNT_ROOT="$1" awk '
    function decode(value, result, code) {
      result=""
      while (match(value, /\\(040|011|012|134)/)) {
        code=substr(value, RSTART + 1, 3)
        result=result substr(value, 1, RSTART - 1)
        if (code == "040") result=result " "
        else if (code == "011") result=result "\t"
        else if (code == "012") result=result "\n"
        else result=result sprintf("%c", 92)
        value=substr(value, RSTART + 4)
      }
      return result value
    }
    NF < 10 { invalid=1; next }
    {
      target=decode($5)
      root=ENVIRON["UAS_MOUNT_ROOT"]
      if (target == root || index(target, root "/") == 1) print
    }
    END { if (invalid) exit 1 }
  ' "${PROC_ROOT}/self/mountinfo"
}

safe_tree() {
  local path="$1" resolved="" records=""
  path_present "${path}" || return 0
  if [[ -L "${path}" || ! -d "${path}" ]]; then
    warn "Refusing symlinked or non-directory installation path: ${path}."
    return 1
  fi
  resolved="$(readlink -f -- "${path}")" || return 1
  if [[ "$(stat -c '%u' "${path}")" != 0 ]]; then
    warn "Installation directory is not owned by root: ${path}."
    return 1
  fi
  records="$(mount_records "${resolved}")" || {
    warn "Cannot inspect mount table for ${path}."
    return 1
  }
  [[ -n "${records}" ]] || return 0
  warn "Mounted subtree: ${path}. Review mounts before uninstalling."
  return 1
}

preflight_paths() {
  local path="" entries=""
  while IFS= read -r path; do
    safe_tree "${path}" || return 1
  done < <(selected_dirs)
  path="/opt/aegis"
  [[ -d "${path}" ]] || return 0
  entries="$(find "${path}" -mindepth 1 -maxdepth 1 -print)" || return 1
  if [[ -n "${entries}" ]] && ! path_present "${path}/aegis_client" \
    && ! path_present "${path}/aegis_update" && ! path_present "${path}/globalcfg"; then
    warn "${path} does not look like a Security Center agent installation."
    return 1
  fi
}

preflight_launcher() {
  local pid="${PPID}" executable="" line="" svc="" depth=0
  local -a selected=() dirs=() services=()
  while IFS= read -r line; do selected+=("${line}"); done < <(selected_dirs)
  while IFS= read -r line; do dirs+=("${line}"); done < <(with_real_paths "${selected[@]}")
  while IFS= read -r svc; do services+=("${svc}"); done < <(selected_services)
  while [[ "${pid}" =~ ^[0-9]+$ && "${pid}" -gt 1 && "${depth}" -lt 64 ]]; do
    executable="$(readlink -- "${PROC_ROOT}/${pid}/exe" 2>/dev/null)" || executable=""
    if [[ -n "${executable}" ]] && is_agent_process "${PROC_ROOT}/${pid}" "${executable% (deleted)}" "${dirs[@]}"; then
      warn "Parent process ${pid} belongs to a component selected for removal: ${executable}."
      [[ "${DRY_RUN}" -eq 0 ]] || return 0
      return 1
    fi
    pid="$(awk '{ sub(/^.*\) /, ""); print $2 }' "${PROC_ROOT}/${pid}/stat" 2>/dev/null)" || break
    depth=$((depth + 1))
  done
  [[ -r "${PROC_ROOT}/self/cgroup" ]] || return 0
  while IFS= read -r line; do
    for svc in "${services[@]}"; do
      if [[ "${line}/" == *"/${svc}.service/"* ]]; then
        warn "This script runs inside ${svc}.service, which it would stop."
        [[ "${DRY_RUN}" -eq 0 ]] || return 0
        return 1
      fi
    done
  done <"${PROC_ROOT}/self/cgroup"
}

backup_agent_config() {
  local dir="" backup="" label="" links=""
  for dir in "${AEGIS_DIRS[@]}"; do
    path_present "${dir}/globalcfg" || continue
    if [[ -L "${dir}/globalcfg" || ! -d "${dir}/globalcfg" ]]; then
      warn "Recovery data must be a directory, not a link: ${dir}/globalcfg."
      return 1
    fi
    links="$(find "${dir}/globalcfg" -type l -print)" || { warn "Cannot inspect ${dir}/globalcfg."; return 1; }
    if [[ -n "${links}" ]]; then
      warn "Recovery data contains symlinks; review them before uninstalling: ${dir}/globalcfg."
      return 1
    fi
    if [[ "${DRY_RUN}" -eq 1 ]]; then
      log "Would preserve ${dir}/globalcfg in a private ${BACKUP_ROOT}/uas.* directory."
      continue
    fi
    if [[ ! -d "${BACKUP_ROOT}" ]]; then
      mkdir -m 700 -- "${BACKUP_ROOT}" || return 1
    fi
    [[ ! -L "${BACKUP_ROOT}" && "$(stat -c '%u' "${BACKUP_ROOT}")" == 0 ]] || return 1
    backup="$(mktemp -d "${BACKUP_ROOT}/uas.XXXXXX")" || return 1
    label="${dir//\//-}"
    run cp -a -- "${dir}/globalcfg" "${backup}/${label#-}-globalcfg" || return 1
    log "Preserved agent configuration and recovery data: ${backup} (root only)."
  done
}

remove_path() {
  local path="$1"
  path_present "${path}" || return 0
  if [[ -d "${path}" && ! -L "${path}" ]]; then
    safe_tree "${path}" || return 1
    run rm -rf -- "${path}" || return $?
  else
    run rm -f -- "${path}" || return $?
  fi
  if [[ "${DRY_RUN}" -eq 0 ]] && path_present "${path}"; then
    warn "Path still exists: ${path}."
    return 1
  fi
}

service_files() {
  local svc="" root="" file="" suffix=""
  for svc in "$@"; do
    for root in /etc/systemd/system /run/systemd/system /usr/lib/systemd/system /lib/systemd/system; do
      for suffix in service timer socket; do
        for file in "${root}/${svc}.${suffix}" "${root}/${svc}.${suffix}.d" \
          "${root}"/*.wants/"${svc}.${suffix}" "${root}"/*.requires/"${svc}.${suffix}"; do
          if path_present "${file}"; then
            printf '%s\n' "${file}"
          fi
        done
      done
    done
    for file in /etc/init.d/"${svc}" /etc/init/"${svc}".conf /etc/init/"${svc}".override \
      /etc/rc[0-6S].d/[SK][0-9][0-9]"${svc}" /etc/rc.d/rc[0-6S].d/[SK][0-9][0-9]"${svc}" \
      /etc/runlevels/*/"${svc}"; do
      path_present "${file}" && printf '%s\n' "${file}"
    done
  done
  return 0
}

systemd_available() {
  [[ -d /run/systemd/system ]] && command_exists systemctl
}

component_command() {
  local rc=0
  run "$@" || rc=$?
  [[ "${rc}" -ne 0 ]] || return 0
  if [[ "$1" == /etc/init.d/* && "${rc}" -eq 3 ]]; then
    return 0
  fi
  if [[ "${FORCE}" -eq 1 && "${rc}" -ne 124 && "${rc}" -lt 128 ]]; then
    warn "Component command failed; force mode will check and signal verified agent processes."
    return 0
  fi
  return "${rc}"
}

stop_services() {
  [[ $# -gt 0 ]] || set -- aegis agentwatch
  local svc="" suffix="" state="" rc=0
  for svc in "$@"; do
    if systemd_available; then
      for suffix in socket timer service; do
        state="$(timeout -k 5 "${COMMAND_TIMEOUT}" systemctl show -p LoadState "${svc}.${suffix}" 9>&- 2>/dev/null)" || return 1
        state="${state#LoadState=}"
        [[ "${state}" != not-found ]] || continue
        component_command systemctl stop "${svc}.${suffix}" || return $?
        if [[ "${state}" != masked ]]; then
          run systemctl disable "${svc}.${suffix}" || rc=1
        fi
      done
    elif command_exists rc-service && [[ -f "/etc/init.d/${svc}" ]]; then
      component_command rc-service "${svc}" stop || return $?
    elif [[ -x "/etc/init.d/${svc}" ]]; then
      component_command "/etc/init.d/${svc}" stop || return $?
    fi
    if command_exists initctl && [[ -f "/etc/init/${svc}.conf" ]]; then
      state="$(timeout -k 5 "${COMMAND_TIMEOUT}" initctl status "${svc}" 9>&- 2>/dev/null)" || state=""
      if [[ "${state}" == *start/* ]]; then
        component_command initctl stop "${svc}" || return $?
      fi
    fi
    if [[ -f "/etc/init.d/${svc}" ]]; then
      if command_exists rc-update; then
        run rc-update del "${svc}" --all || rc=1
      elif command_exists chkconfig; then
        run chkconfig --del "${svc}" || rc=1
      elif command_exists update-rc.d; then
        run update-rc.d -f "${svc}" remove || rc=1
      fi
    fi
  done
  return "${rc}"
}

cleanup_services() {
  local file="" rc=0
  while IFS= read -r file; do
    remove_path "${file}" || rc=1
  done < <(service_files "$@")
  if systemd_available; then
    run systemctl daemon-reload || rc=1
  fi
  return "${rc}"
}

path_in_dirs() {
  local executable="$1" dir=""
  shift
  for dir in "$@"; do
    [[ "${executable}" == "${dir}/"* ]] && return 0
  done
  return 1
}

with_real_paths() {
  local dir="" base="" rest="" real=""
  for dir in "$@"; do
    printf '%s\n' "${dir}"
    base="${dir}"
    rest=""
    while [[ -n "${base}" && ! -e "${base}" ]]; do
      rest="/${base##*/}${rest}"
      base="${base%/*}"
    done
    real="$(readlink -f -- "${base:-/}" 2>/dev/null)" || continue
    real="${real%/}${rest}"
    [[ "${real}" == "${dir}" ]] || printf '%s\n' "${real}"
  done
}

process_token() {
  local entry="$1" started="" arguments=""
  started="$(awk '{ sub(/^.*\) /, ""); print $20 }' "${entry}/stat" 2>/dev/null)" || return 1
  [[ "${started}" =~ ^[0-9]+$ ]] || return 1
  arguments="$(cksum <"${entry}/cmdline" 2>/dev/null)" || return 1
  printf '%s|%s' "${started}" "${arguments}"
}

is_agent_process() {
  local entry="$1" executable="$2" script=""
  shift 2
  path_in_dirs "${executable}" "$@" && return 0
  case "${executable##*/}" in
    sh|bash|dash|busybox)
      { IFS= read -r -d '' _; IFS= read -r -d '' script; } <"${entry}/cmdline" 2>/dev/null || true
      case "${script##*/}" in
        cloudmonitor.sh|cloudmonitorCtl.sh|aliyun-service|aliyun_assist_update.sh)
          path_in_dirs "${script}" "$@" && return 0
          ;;
      esac
      ;;
    java)
      java_agent "${entry}/cmdline" "$@" && return 0
      ;;
  esac
  return 1
}

agent_processes() {
  local entry="" pid="" executable="" argv0="" token="" rc=0
  local -a dirs=()
  [[ -r "${PROC_ROOT}/self/status" ]] || { warn "Cannot inspect /proc."; return 1; }
  while IFS= read -r entry; do dirs+=("${entry}"); done < <(with_real_paths "$@")
  for entry in "${PROC_ROOT}"/[0-9]*; do
    [[ -d "${entry}" ]] || continue
    pid="${entry##*/}"
    [[ "${pid}" != "$$" ]] || continue
    if [[ ! -r "${entry}/cmdline" ]]; then
      if [[ -d "${entry}" ]]; then
        warn "Cannot inspect command line for PID ${pid}."
        rc=1
      fi
      continue
    fi
    argv0=""
    IFS= read -r -d '' argv0 <"${entry}/cmdline" 2>/dev/null || true
    [[ -n "${argv0}" ]] || continue
    executable="$(readlink -- "${entry}/exe" 2>/dev/null)" || {
      argv0=""
      IFS= read -r -d '' argv0 <"${entry}/cmdline" 2>/dev/null || true
      if [[ -n "${argv0}" ]]; then
        warn "Cannot inspect executable for PID ${pid}."
        rc=1
      fi
      continue
    }
    executable="${executable% (deleted)}"
    is_agent_process "${entry}" "${executable}" "${dirs[@]}" || continue
    token="$(process_token "${entry}")" || {
      [[ ! -d "${entry}" ]] || rc=1
      continue
    }
    printf '%s|%s|%s\n' "${pid}" "${executable}" "${token}"
  done
  return "${rc}"
}

java_agent() {
  local cmdline="$1" arg="" previous="" dir="" item="" wrapper=0 classpath=0
  local -a entries=()
  shift
  while IFS= read -r -d '' arg || [[ -n "${arg}" ]]; do
    [[ "${arg}" != org.tanukisoftware.wrapper.WrapperSimpleApp ]] || wrapper=1
    if [[ "${previous}" == -cp || "${previous}" == -classpath || "${previous}" == --class-path ]]; then
      IFS=: read -r -a entries <<<"${arg}"
      for item in ${entries[@]+"${entries[@]}"}; do
        for dir in "$@"; do
          [[ "${item}" != "${dir}/wrapper/lib/wrapper.jar" ]] || classpath=1
        done
      done
    fi
    previous="${arg}"
  done <"${cmdline}"
  [[ "${wrapper}" -eq 1 && "${classpath}" -eq 1 ]]
}

signal_agent_processes() {
  local signal="$1" targets="$2" pid="" expected="" current="" started="" arguments="" token=""
  while IFS='|' read -r pid expected started arguments; do
    [[ -n "${pid}" ]] || continue
    if [[ "${expected##*/}" == AliSecGuard ]]; then
      warn "Leaving AliSecGuard running; local cleanup never signals it because that can hang older kernels."
      continue
    fi
    current="$(readlink -- "${PROC_ROOT}/${pid}/exe" 2>/dev/null)" || continue
    [[ "${current% (deleted)}" == "${expected}" ]] || continue
    token="$(process_token "${PROC_ROOT}/${pid}")" || continue
    [[ "${token}" == "${started}|${arguments}" ]] || continue
    if [[ "${DRY_RUN}" -eq 1 ]]; then
      printf '[DRY-RUN] kill -%s %s (%s)\n' "${signal}" "${pid}" "${expected}" >&3
    else
      kill -"${signal}" "${pid}" 2>/dev/null || warn "Cannot signal PID ${pid}: ${expected}."
    fi
  done <<<"${targets}"
}

show_processes() {
  local pid="" executable=""
  while IFS='|' read -r pid executable _; do
    printf '  PID %-8s %s\n' "${pid}" "${executable}" >&2
  done <<<"$1"
}

stop_agent_processes() {
  local targets="" signalled="" fresh=""
  targets="$(agent_processes "$@")" || return 1
  [[ -n "${targets}" ]] || return 0
  signal_agent_processes TERM "${targets}"
  [[ "${DRY_RUN}" -eq 0 ]] || return 0
  signalled="${targets}"
  for _ in 1 2 3 4 5; do
    sleep 1
    targets="$(agent_processes "$@")" || return 1
    [[ -n "${targets}" ]] || return 0
    fresh="$(grep -Fxv -f <(printf '%s\n' "${signalled}") <<<"${targets}")" || true
    [[ -z "${fresh}" ]] || signal_agent_processes TERM "${fresh}"
    signalled="${targets}"
  done
  if [[ "${FORCE}" -eq 1 ]]; then
    signal_agent_processes KILL "${targets}"
    sleep 1
    targets="$(agent_processes "$@")" || return 1
    [[ -n "${targets}" ]] || return 0
  fi
  warn "Agent processes remain; preserving their installation files:"
  show_processes "${targets}"
  return 1
}

cleanup_legacy_leftovers() {
  stop_services aegis agentwatch || return 1
  stop_agent_processes "${AEGIS_DIRS[@]}" || return 1
  cleanup_services aegis agentwatch
}

cleanup_aegis_directory() {
  local dir="" rc=0
  for dir in "${AEGIS_DIRS[@]}"; do
    remove_path "${dir}" || rc=1
  done
  return "${rc}"
}

assist_packages() {
  local packages="" status=""
  if command_exists rpm; then
    packages="$(timeout -k 5 "${COMMAND_TIMEOUT}" rpm -qa --qf '%{NAME}\n' 'aliyun_assist*' 9>&-)" || return 1
    [[ -z "${packages}" ]] || printf '%s\n' "${packages}"
  fi
  if command_exists dpkg-query; then
    status="$(timeout -k 5 "${COMMAND_TIMEOUT}" dpkg-query -W -f="\${Status}" aliyun-assist 9>&- 2>/dev/null)" || {
      [[ $? -eq 1 ]] || return 1
    }
    if [[ -n "${status}" && "${status}" != *" not-installed" ]]; then
      printf '%s\n' aliyun-assist
    fi
  fi
}

uninstall_cloud_assist() {
  [[ "${INCLUDE_ASSIST}" -eq 1 ]] || return 0
  section "Cloud Assistant (aliyun-service / assist_daemon)"
  local daemon="" dir="" pkg="" packages="" rc=0
  stop_services AssistDaemon aliyun aliyun-service || return 1
  for dir in "${ASSIST_DIRS[@]}"; do
    daemon="${dir}/assist_daemon"
    [[ -x "${daemon}" ]] || continue
    component_command "${daemon}" --stop || return $?
    run "${daemon}" --delete || return $?
  done
  stop_agent_processes "${ASSIST_DIRS[@]}" || return 1
  packages="$(assist_packages)" || return 1
  while IFS= read -r pkg; do
    [[ -n "${pkg}" ]] || continue
    if [[ "${pkg}" == aliyun-assist ]]; then
      purge_deb "${pkg}" || return 1
    else
      run rpm -e "${pkg}" || return 1
    fi
  done <<<"${packages}"
  if [[ "${DRY_RUN}" -eq 0 ]]; then
    packages="$(assist_packages)" || return 1
    [[ -z "${packages}" ]] || { warn "Cloud Assistant packages remain installed."; return 1; }
  fi
  stop_agent_processes "${ASSIST_DIRS[@]}" || return 1
  cleanup_services AssistDaemon aliyun aliyun-service || return 1
  for dir in "${ASSIST_DIRS[@]}"; do
    remove_path "${dir}" || rc=1
  done
  for dir in /usr/sbin/aliyun-service /usr/sbin/aliyun-service.backup /usr/sbin/aliyun_installer \
    /usr/sbin/acs-plugin-manager /tmp/aliyun_assist_service.sock \
    /tmp/AliyunAssistClientSingleLock.lock /var/tmp/aliyun-service.pid; do
    remove_path "${dir}" || rc=1
  done
  return "${rc}"
}

uninstall_cloudmonitor() {
  [[ "${INCLUDE_CLOUDMONITOR}" -eq 1 ]] || return 0
  section "CloudMonitor (argusagent / CmsGoAgent)"
  local dir="" agent="" arch="" rc=0
  case "$(uname -m)" in
    x86_64) arch=amd64 ;;
    aarch64|arm64) arch=arm64 ;;
    i?86) arch=386 ;;
  esac
  stop_services cloudmonitor || return 1
  for dir in "${MONITOR_DIRS[@]}"; do
    if [[ -x "${dir}/cloudmonitorCtl.sh" ]]; then
      component_command "${dir}/cloudmonitorCtl.sh" stop || return $?
      component_command "${dir}/cloudmonitorCtl.sh" uninstall || return $?
    fi
    if [[ -n "${arch}" && -x "${dir}/CmsGoAgent.linux-${arch}" ]]; then
      agent="${dir}/CmsGoAgent.linux-${arch}"
      component_command "${agent}" stop || return $?
      component_command "${agent}" uninstall || return $?
    elif [[ -z "${arch}" ]] && compgen -G "${dir}/CmsGoAgent.linux-*" >/dev/null; then
      warn "Unsupported CloudMonitor binary architecture: $(uname -m)."
      return 1
    fi
    if [[ -x "${dir}/wrapper/bin/cloudmonitor.sh" ]]; then
      component_command "${dir}/wrapper/bin/cloudmonitor.sh" remove || return $?
    fi
  done
  stop_agent_processes "${MONITOR_DIRS[@]}" || return 1
  cleanup_services cloudmonitor || return 1
  rc=0
  for dir in "${MONITOR_DIRS[@]}" /etc/cloudmonitor; do
    remove_path "${dir}" || rc=1
  done
  return "${rc}"
}

verify_uninstall() {
  local path="" targets="" packages="" module="" found=0
  local -a dirs=()
  while IFS= read -r path; do
    dirs+=("${path}")
    if path_present "${path}"; then
      warn "Installation path remains: ${path}."
      found=1
    fi
  done < <(selected_dirs)
  targets="$(agent_processes "${dirs[@]}")" || return 1
  if [[ -n "${targets}" ]]; then
    warn "Agent processes remain:"
    show_processes "${targets}"
    found=1
  fi
  if [[ "${INCLUDE_ASSIST}" -eq 1 ]]; then
    packages="$(assist_packages)" || return 1
    if [[ -n "${packages}" ]]; then
      warn "Cloud Assistant packages remain: ${packages}."
      found=1
    fi
  fi
  for module in AliSecGuard AliHips AliNet AliWebGuard; do
    if [[ -d "${SYS_ROOT}/module/${module}" ]]; then
      warn "Kernel module ${module} remains loaded. Review a reboot window and verify again."
      [[ "${found}" -ne 0 ]] || found=3
    fi
  done
  return "${found}"
}

main() {
  local official_rc=0
  local quartz_rc=0
  local verify_rc=0

  exec 3>&1
  parse_args "$@"
  require_linux
  require_root
  detect_distro
  confirm
  prepare_runtime
  preflight_paths || die "Unsafe installation paths. No uninstall was attempted."
  preflight_launcher || die "Run from an SSH session or a detached unit such as systemd-run. No uninstall was attempted."
  backup_agent_config || die "Could not preserve agent recovery data. No uninstall was attempted."

  section "Environment"
  log "Distribution: ${DISTRO_PRETTY}"
  log "Architecture: $(uname -m)"
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    log "Dry run: no process will be stopped and no file will be removed."
  fi

  section "Security Center agent (Aegis)"
  log "Alibaba Cloud docs require disabling self-protection before a command-line uninstall."
  run_official_uninstall || official_rc=$?
  if [[ "${official_rc}" -ne 0 ]]; then
    warn "Official uninstall.sh exited with status ${official_rc}."
    if [[ "${FORCE}" -eq 0 || "${official_rc}" -eq 124 || "${official_rc}" -ge 128 ]]; then
      warn "Local cleanup was not started. Resolve the official failure before retrying."
      return "${official_rc}"
    fi
    warn "Force mode: trying scoped local cleanup; kernel protection may still block it."
  fi

  if cleanup_legacy_leftovers; then
    run_legacy_quartz_cleanup || quartz_rc=$?
    if [[ "${quartz_rc}" -eq 0 || "${FORCE}" -eq 1 && "${quartz_rc}" -ne 124 && "${quartz_rc}" -lt 128 ]]; then
      if [[ "${quartz_rc}" -ne 0 ]]; then
        warn "Legacy quartz uninstall failed (${quartz_rc}); force mode will verify and clean local remnants."
      fi
      if [[ "${DRY_RUN}" -eq 1 ]] || stop_agent_processes "${AEGIS_DIRS[@]}"; then
        cleanup_aegis_directory || record_failure "Aegis directory cleanup failed."
      else
        record_failure "Aegis processes remain. Installation files were preserved."
      fi
    else
      record_failure "Legacy quartz cleanup failed. Installation files were preserved."
    fi
  else
    record_failure "Could not stop Aegis and remove its startup entries. Installation files were preserved."
  fi

  uninstall_cloud_assist || record_failure "Cloud Assistant uninstall is incomplete."
  uninstall_cloudmonitor || record_failure "CloudMonitor uninstall is incomplete."

  if [[ "${DRY_RUN}" -eq 1 ]]; then
    section "Dry run finished"
    log "No downloads, process signals or installation changes were made."
    return "${FAILURES}"
  fi

  section "Verification"
  verify_uninstall || verify_rc=$?

  printf '\n'
  if [[ "${FAILURES}" -eq 0 && "${verify_rc}" -eq 0 ]]; then
    ok "${SCRIPT_NAME}: local uninstall verified."
    if [[ "${official_rc}" -ne 0 ]]; then
      warn "Official uninstall failed (${official_rc}); only local cleanup is verified."
    fi
    return 0
  fi

  warn "${SCRIPT_NAME}: incomplete. See the failed operations and remaining items above."
  [[ "${verify_rc}" -eq 0 ]] || return "${verify_rc}"
  return 1
}

if [[ "${BASH_SOURCE[0]:-$0}" == "$0" ]]; then
  main "$@"
fi
