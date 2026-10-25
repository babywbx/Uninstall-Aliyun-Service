import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import textwrap
import unittest


SCRIPT = Path(os.environ.get("UAS_SCRIPT", Path(__file__).resolve().parents[1] / "UAS.sh"))
BASH = shutil.which("bash")


@unittest.skipUnless(BASH, "Bash is required")
class UasFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="uas-tests-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "root"
        self.root.mkdir()
        for directory in ("tmp", "etc", "proc", "sys", "run", "var", "var/lib"):
            (self.root / directory).mkdir()
        (self.root / "etc/os-release").write_text(
            'ID=debian\nPRETTY_NAME="Debian GNU/Linux 12 (bookworm)"\n'
        )
        self.events = self.base / "events"
        self.events.touch()
        source = SCRIPT.read_text()
        source = re.sub(
            r"(?<![A-Za-z0-9_/])/(etc|usr|opt|lib|lib64|proc|sys|run|var|tmp|sbin)(?=/|[\s\"'])",
            lambda match: f"{self.root}/{match[1]}",
            source,
        )
        self.source = self.base / "UAS.sh"
        self.source.write_text(source)

    def file_snapshot(self):
        return {
            str(path.relative_to(self.root)): (
                path.stat().st_mode,
                path.read_bytes() if path.is_file() else None,
            )
            for path in self.root.rglob("*")
        }

    def run_shell(self, script):
        self.events.write_text("")
        prelude = r"""
            record() { printf '%s\n' "$*" >> "$UAS_TEST_EVENTS"; }
            blocked() { record "unexpected-external $*"; return 97; }
            curl() { blocked curl "$@"; }
            wget() { blocked wget "$@"; }
            ssh() { blocked ssh "$@"; }
            scp() { blocked scp "$@"; }
            sudo() { blocked sudo "$@"; }
            rm() { record "rm $*"; return 0; }
            kill() { blocked kill "$@"; }
            pkill() { blocked pkill "$@"; }
            killall() { blocked killall "$@"; }
            chattr() { blocked chattr "$@"; }
            rmmod() { blocked rmmod "$@"; }
            modprobe() { blocked modprobe "$@"; }
            systemctl() { blocked systemctl "$@"; }
            service() { blocked service "$@"; }
            initctl() { blocked initctl "$@"; }
            chkconfig() { blocked chkconfig "$@"; }
            update-rc.d() { blocked update-rc.d "$@"; }
            timeout() { blocked timeout "$@"; }
            apt-get() { blocked apt-get "$@"; }
            dpkg() { return 1; }
            dpkg-query() { return 1; }
            rpm() { return 1; }
            uname() {
              case "${1:--s}" in
                -m) printf 'x86_64\n' ;;
                *) printf 'Linux\n' ;;
              esac
            }
        """
        overrides = r"""
            cleanup() { :; }
            require_root() { :; }
            prepare_runtime() { :; }
            preflight_paths() { :; }
            backup_agent_config() { :; }
            run() { record "run $*"; return 0; }
        """
        body = (
            textwrap.dedent(prelude)
            + f"\nsource {shlex.quote(str(self.source))}\n"
            + textwrap.dedent(overrides)
            + textwrap.dedent(script)
        )
        environment = {
            "PATH": os.environ.get("PATH", os.defpath),
            "HOME": str(self.base),
            "TMPDIR": str(self.root / "tmp"),
            "NO_COLOR": "1",
            "TERM": "dumb",
            "LC_ALL": "C",
            "UAS_TEST_ROOT": str(self.root),
            "UAS_TEST_EVENTS": str(self.events),
        }
        result = subprocess.run(
            [BASH, "--noprofile", "--norc", "-c", body],
            cwd=self.base,
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertNotIn(
            "unexpected-external",
            self.events.read_text(),
            f"Unexpected external command:\n{self.events.read_text()}\n{result.stderr}",
        )
        return result

    def assert_failed(self, result):
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn(": local uninstall verified.", result.stdout)

    def real_function(self, name):
        source = self.source.read_text()
        body = source.split(f"\n{name}() {{\n", 1)[1].split("\n}\n", 1)[0]
        return f"{name}() {{\n{body}\n}}\n"

    def removal_requested(self, directory):
        return any(
            line.startswith("run rm ") and str(directory) in line
            for line in self.events.read_text().splitlines()
        )

class UninstallTests(UasFixture):
    def test_script_runs_when_piped_to_bash(self):
        result = subprocess.run(
            [BASH, "-s", "--", "--help"],
            input=SCRIPT.read_text(),
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Usage:", result.stdout)

    def test_aegis_directory_removal_failure_is_reported(self):
        directory = self.root / "usr/local/aegis"
        directory.mkdir(parents=True)
        result = self.run_shell(
            r"""
            run_official_uninstall() { return 0; }
            run_legacy_quartz_cleanup() { :; }
            cleanup_legacy_leftovers() { :; }
            stop_agent_processes() { :; }
            safe_tree() { :; }
            uninstall_cloud_assist() { :; }
            uninstall_cloudmonitor() { :; }
            verify_uninstall() { return 0; }
            run() {
              record "run $*"
              if [[ "$1" == rm ]]; then return 1; fi
              return 0
            }
            main --yes --skip-quartz
            """
        )
        self.assert_failed(result)
        self.assertTrue(self.removal_requested(directory))

    def test_dry_run_does_not_download_execute_or_change_files(self):
        aegis = self.root / "usr/local/aegis"
        (aegis / "aegis_client").mkdir(parents=True)
        (self.root / "etc/init.d").mkdir()
        (self.root / "etc/init.d/aegis").write_text("#!/bin/sh\n")
        (self.root / "proc/self").mkdir()
        (self.root / "proc/self/status").touch()
        (self.root / "proc/self/mountinfo").touch()
        before = self.file_snapshot()
        result = self.run_shell(
            self.real_function("run")
            + r"""
            stat() { printf '0\n'; }
            detect_ecs() { record 'metadata-probe'; return 1; }
            download_file() { record "download $1"; }
            verify_uninstall() { record verify; }
            main --dry-run
            """
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.events.read_text(), "")
        self.assertIn(f"[DRY-RUN] rm -rf -- {aegis}", result.stdout)
        self.assertIn(f"[DRY-RUN] rm -f -- {self.root / 'etc/init.d/aegis'}", result.stdout)
        self.assertEqual(before, self.file_snapshot())

    def test_non_linux_fails_before_downloading_or_cleanup(self):
        result = self.run_shell(
            r"""
            uname() {
              case "${1:--s}" in
                -m) printf 'arm64\n' ;;
                *) printf 'Darwin\n' ;;
              esac
            }
            run_official_uninstall() { record 'download'; return 0; }
            run_legacy_quartz_cleanup() { record 'cleanup'; }
            cleanup_legacy_leftovers() { record 'cleanup'; }
            cleanup_aegis_directory() { record 'cleanup'; }
            uninstall_cloud_assist() { record 'cleanup'; }
            uninstall_cloudmonitor() { record 'cleanup'; }
            verify_uninstall() { return 0; }
            main --yes
            """
        )
        self.assert_failed(result)
        self.assertRegex(result.stderr, r"(?i)linux")
        self.assertEqual(self.events.read_text(), "")

    def test_official_protection_failure_stops_before_local_cleanup(self):
        result = self.run_shell(
            r"""
            run_official_uninstall() { record 'official'; return 6; }
            run_legacy_quartz_cleanup() { record 'cleanup'; }
            cleanup_legacy_leftovers() { record 'cleanup'; }
            cleanup_aegis_directory() { record 'cleanup'; }
            uninstall_cloud_assist() { record 'cleanup'; }
            uninstall_cloudmonitor() { record 'cleanup'; }
            verify_uninstall() { return 0; }
            main --yes
            """
        )
        self.assert_failed(result)
        self.assertEqual(self.events.read_text(), "official\n")

    def test_official_failure_stops_before_local_cleanup(self):
        for status in (1, 7):
            with self.subTest(status=status):
                result = self.run_shell(
                    f"run_official_uninstall() {{ record 'official'; return {status}; }}\n"
                    + r"""
                    run_legacy_quartz_cleanup() { record 'cleanup'; }
                    cleanup_legacy_leftovers() { record 'cleanup'; }
                    cleanup_aegis_directory() { record 'cleanup'; }
                    uninstall_cloud_assist() { record 'cleanup'; }
                    uninstall_cloudmonitor() { record 'cleanup'; }
                    verify_uninstall() { return 0; }
                    main --yes
                    """
                )
                self.assertEqual(result.returncode, status, result.stdout + result.stderr)
                self.assertEqual(self.events.read_text(), "official\n")

    def test_force_allows_verified_local_fallback(self):
        result = self.run_shell(
            r"""
            run_official_uninstall() { record 'official'; return 6; }
            run_legacy_quartz_cleanup() { :; }
            cleanup_legacy_leftovers() { record 'cleanup-services'; }
            stop_agent_processes() { :; }
            cleanup_aegis_directory() { record 'cleanup-directory'; }
            uninstall_cloud_assist() { :; }
            uninstall_cloudmonitor() { :; }
            verify_uninstall() { record 'verify'; return 0; }
            main --yes --force
            """
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            self.events.read_text(),
            "official\ncleanup-services\ncleanup-directory\nverify\n",
        )

    def test_force_does_not_continue_after_timeout_or_signal(self):
        for status in (124, 137):
            with self.subTest(status=status):
                result = self.run_shell(
                    f"run_official_uninstall() {{ record 'official'; return {status}; }}\n"
                    + r"""
                    run_legacy_quartz_cleanup() { record 'cleanup'; }
                    cleanup_legacy_leftovers() { record 'cleanup'; }
                    cleanup_aegis_directory() { record 'cleanup'; }
                    uninstall_cloud_assist() { record 'cleanup'; }
                    uninstall_cloudmonitor() { record 'cleanup'; }
                    verify_uninstall() { return 0; }
                    main --yes --force
                    """
                )
                self.assertEqual(result.returncode, status, result.stdout + result.stderr)
                self.assertEqual(self.events.read_text(), "official\n")

    def test_failed_steps_cannot_be_cleared_by_successful_verification(self):
        steps = (
            "cleanup_legacy_leftovers",
            "run_legacy_quartz_cleanup",
            "cleanup_aegis_directory",
            "uninstall_cloud_assist",
            "uninstall_cloudmonitor",
            "uninstall_loongcollector",
        )
        for step in steps:
            with self.subTest(step=step):
                result = self.run_shell(
                    r"""
                    run_official_uninstall() { return 0; }
                    stop_agent_processes() { :; }
                    cleanup_legacy_leftovers() { :; }
                    run_legacy_quartz_cleanup() { :; }
                    cleanup_aegis_directory() { :; }
                    uninstall_cloud_assist() { :; }
                    uninstall_cloudmonitor() { :; }
                    verify_uninstall() { record 'verify'; return 0; }
                    """
                    + f"\n{step}() {{ record 'failed-{step}'; return 1; }}\n"
                    + 'status=0; main --yes || status=$?; exit "$status"\n'
                )
                self.assert_failed(result)
                self.assertEqual(self.events.read_text(), f"failed-{step}\nverify\n")

    def test_failed_assistant_package_removal_preserves_component_files(self):
        directory = self.root / "usr/local/share/aliyun-assist"
        directory.mkdir(parents=True)
        result = self.run_shell(
            r"""
            command_exists() { [[ "$1" == dpkg-query ]]; }
            stop_services() { :; }
            stop_agent_processes() { :; }
            dpkg-query() { printf 'install ok installed'; }
            timeout() {
              if [[ "$1" != -k || "$2" != 5 || "$3" != 120 ]]; then
                blocked timeout "$@"
                return 97
              fi
              shift 3
              case "$1" in
                dpkg-query) dpkg-query "${@:2}" ;;
                *) blocked timeout "$@" ;;
              esac
            }
            run() {
              record "run $*"
              case "$*" in *dpkg*) return 42 ;; esac
              return 0
            }
            INCLUDE_ASSIST=1
            uninstall_cloud_assist
            """
        )
        self.assert_failed(result)
        events = self.events.read_text()
        self.assertIn("run env DEBIAN_FRONTEND=noninteractive dpkg --purge aliyun-assist", events)
        self.assertFalse(self.removal_requested(directory))

    def test_assistant_package_purge_waits_for_dpkg_lock(self):
        lock = self.root / "var/lib/dpkg/lock-frontend"
        lock.parent.mkdir(parents=True)
        lock.touch()
        (self.root / "proc/locks").write_text(
            "1: FLOCK  ADVISORY  WRITE 900 fd:01:77 0 EOF\n"
            "2: POSIX  ADVISORY  WRITE 6253 fd:01:4242 0 EOF\n"
        )
        result = self.run_shell(
            f"lock={lock}\n"
            + r"""
            stat() {
              [[ "$*" == "-c %d %i -- ${lock}" ]] || return 1
              printf '64769 4242\n'
            }
            slept=0
            sleep() {
              record "sleep $*"
              slept=$((slept + 1))
              if [[ "${slept}" -eq 1 ]]; then
                printf '%s\n' '2: -> POSIX  ADVISORY  WRITE 6254 fd:01:4242 0 EOF' > "${PROC_ROOT}/locks"
              else
                : > "${PROC_ROOT}/locks"
              fi
            }
            purge_deb aliyun-assist
            """
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("release the dpkg lock", result.stdout)
        self.assertEqual(self.events.read_text().splitlines(), [
            "sleep 5",
            "sleep 5",
            "run env DEBIAN_FRONTEND=noninteractive dpkg --purge aliyun-assist",
        ])


if __name__ == "__main__":
    unittest.main()
