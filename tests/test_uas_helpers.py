import os
import shlex
import shutil

from test_uas import UasFixture


class HelperTests(UasFixture):
    def process(self, pid, executable, arguments, started=100):
        proc = self.root / f"proc/{pid}"
        proc.mkdir(parents=True)
        (self.root / "proc/self").mkdir(exist_ok=True)
        (self.root / "proc/self/status").touch()
        (proc / "exe").symlink_to(os.path.realpath(executable))
        (proc / "cmdline").write_bytes(b"\0".join(arg.encode() for arg in arguments) + b"\0")
        fields = ["S", *(["0"] * 18), str(started)]
        (proc / "stat").write_text(f"{pid} (agent worker) {' '.join(fields)}\n")
        return proc

    def test_process_scan_uses_executable_not_argument_substrings(self):
        agent = str(self.root / "usr/local/aegis/aegis_client/AliYunDunMonitor")
        self.process(900001, agent, [agent])
        self.process(900002, "/usr/bin/tail", ["tail", "-f", f"{agent}/log"])
        self.process(900003, "/usr/bin/vim", ["vim", "/etc/init.d/aliyun-service"])
        result = self.run_shell('agent_processes "${AEGIS_DIRS[@]}"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("900001|", result.stdout)
        self.assertNotIn("900002|", result.stdout)
        self.assertNotIn("900003|", result.stdout)

    def test_shell_arguments_do_not_impersonate_agent_scripts(self):
        script = str(self.root / "usr/local/cloudmonitor/cloudmonitor.sh")
        arguments = (
            ["-c", ":", script],
            ["-ec", ":", script],
            ["-s", script],
            ["-es", script],
            ["-o", script],
            ["-O", script],
            ["--unknown-option", script],
            ["--rcfile", script, "/other/script.sh"],
            ["/other/script.sh", script],
        )
        for index, args in enumerate(arguments):
            self.process(900080 + index, "/bin/bash", ["bash", *args])
        result = self.run_shell('agent_processes "${MONITOR_DIRS[@]}"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_java_requires_wrapper_classpath_identity(self):
        root = str(self.root / "usr/local/cloudmonitor")
        wrapper = "org.tanukisoftware.wrapper.WrapperSimpleApp"
        self.process(900010, "/usr/bin/java", ["java", f"-Dapp.log={root}/custom.log", wrapper])
        self.process(900011, "/usr/bin/java", ["java", "-cp", f"{root}/wrapper/lib/wrapper.jar", wrapper])
        result = self.run_shell('agent_processes "${MONITOR_DIRS[@]}"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("900010|", result.stdout)
        self.assertIn("900011|", result.stdout)

    def test_missing_cmdline_is_not_successful_verification(self):
        agent = str(self.root / "usr/local/aegis/agent")
        proc = self.process(900020, agent, [agent])
        (proc / "cmdline").unlink()
        result = self.run_shell('agent_processes "${AEGIS_DIRS[@]}"')
        self.assert_failed(result)
        self.assertIn("Cannot inspect command line", result.stderr)

    def test_pid_reuse_or_changed_arguments_prevents_signal(self):
        script = str(self.root / "usr/local/cloudmonitor/cloudmonitor.sh")
        for pid, changed in ((900029, None), (900030, "start"), (900031, "arguments")):
            with self.subTest(changed=changed):
                proc = self.process(pid, "/bin/bash", ["bash", script])
                change = {
                    None: ":",
                    "start": f"printf '%s\\n' '{pid} (agent worker) S " + "0 " * 18 + "101' > " + shlex.quote(str(proc / "stat")),
                    "arguments": f"printf 'bash\\0/other/service.sh\\0' > {shlex.quote(str(proc / 'cmdline'))}",
                }[changed]
                result = self.run_shell(
                    'exec 3>&1\ntargets="$(agent_processes "${MONITOR_DIRS[@]}")"\n'
                    + change
                    + '\nDRY_RUN=1\nsignal_agent_processes TERM "$targets"\n'
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(f"kill -TERM {pid}" in result.stdout, changed is None)

    def test_safe_tree_rejects_same_filesystem_bind_mount(self):
        root = self.root / "usr/local/aegis"
        root.mkdir(parents=True)
        (self.root / "proc/self").mkdir()
        (self.root / "proc/self/mountinfo").write_text(
            f"10 1 8:1 /business {os.path.realpath(root)}/logs rw - ext4 /dev/root rw\n"
        )
        result = self.run_shell('stat() { printf "0\\n"; }\nsafe_tree "${AEGIS_DIRS[0]}"')
        self.assert_failed(result)
        self.assertIn("Mounted subtree", result.stderr)

    def test_backup_rejects_symlink_before_claiming_success(self):
        root = self.root / "usr/local/aegis"
        (root / "config/globalcfg").mkdir(parents=True)
        for nested in (False, True):
            with self.subTest(nested=nested):
                if nested:
                    (root / "globalcfg").unlink()
                    (root / "globalcfg").mkdir()
                    (root / "globalcfg/key").symlink_to("/etc/shadow")
                else:
                    (root / "globalcfg").symlink_to("config/globalcfg")
                result = self.run_shell(self.real_function("backup_agent_config") + "backup_agent_config")
                self.assert_failed(result)
                self.assertNotIn("Preserved agent", result.stdout)
                self.assertNotIn("run cp", self.events.read_text())

    def test_run_closes_stdin_and_does_not_leak_lock_descriptor(self):
        input_file = self.base / "input"
        input_file.write_text("do not pass to uninstallers\n")
        result = self.run_shell(
            'exec 3>&1\nexec 9<"$UAS_TEST_EVENTS"\n'
            'timeout() {\n'
            '  if [[ -e /dev/fd/9 ]]; then record lock-leaked; return 90; fi\n'
            '  if IFS= read -r value; then record stdin-leaked; return 91; fi\n'
            '  return 17\n'
            '}\n' + self.real_function("run") + 'run harmless <' + shlex.quote(str(input_file))
        )
        self.assertEqual(result.returncode, 17, result.stdout + result.stderr)
        self.assertNotIn("leaked", self.events.read_text())

    def test_downloaded_script_is_run_through_bash(self):
        script = self.base / "vendor.sh"
        script.write_text("#!/bin/bash\nexit 0\n")
        script.chmod(0o600)
        result = self.run_shell("run_script " + shlex.quote(str(script)) + " vendor")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"run bash {script}", self.events.read_text())

    def test_strict_curl_download_restricts_redirect_protocols(self):
        result = self.run_shell('download_file https://example.invalid/vendor.sh "$UAS_TEST_ROOT/tmp/download"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--proto =https --proto-redir =https", self.events.read_text())

    def test_busybox_wget_requires_explicit_download_override(self):
        for allow in (0, 1):
            with self.subTest(allow=allow):
                self.events.write_text("")
                result = self.run_shell(
                    'command_exists() { [[ "$1" == wget ]]; }\n'
                    'wget() { printf "Usage: wget -q -T SEC -O FILE URL\\n"; }\n'
                    f'ALLOW_INSECURE_DOWNLOAD={allow}\n'
                    'download_file https://example.invalid/vendor.sh "$UAS_TEST_ROOT/tmp/download"'
                )
                if allow:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("run wget", self.events.read_text())
                    self.assertNotIn("--connect-timeout", self.events.read_text())
                else:
                    self.assert_failed(result)
                    self.assertNotIn("run wget", self.events.read_text())

    def test_orphan_startup_entries_include_all_supported_init_locations(self):
        paths = (
            "etc/systemd/system/agentwatch.service",
            "etc/runlevels/boot/agentwatch",
            "etc/rc.d/rc3.d/S42agentwatch",
            "etc/init/agentwatch.conf",
        )
        for path in paths:
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.touch()
        result = self.run_shell("service_files agentwatch")
        self.assertEqual(result.returncode, 0, result.stderr)
        for path in paths:
            self.assertIn(str(self.root / path), result.stdout)

    def test_timeout_argument_rejects_missing_zero_and_excessive_values(self):
        for value in (None, "0", "01", "3601", "-2", "one"):
            with self.subTest(value=value):
                argument = "" if value is None else " " + shlex.quote(value)
                result = self.run_shell("parse_args --timeout" + argument)
                self.assert_failed(result)

    def test_loaded_kernel_module_is_not_complete_success(self):
        (self.root / "sys/module/AliSecGuard").mkdir(parents=True)
        result = self.run_shell(
            'selected_dirs() { printf "%s\\n" "${AEGIS_DIRS[0]}"; }\nagent_processes() { :; }\n'
            'service_files() { :; }\nverify_services() { :; }\nverify_uninstall'
        )
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn("remains loaded", result.stderr)

    def test_safe_tree_checks_real_path_below_symlinked_parent(self):
        (self.root / "var/opt/aegis").mkdir(parents=True)
        (self.root / "opt").symlink_to("var/opt")
        (self.root / "proc/self").mkdir()
        mountinfo = self.root / "proc/self/mountinfo"
        resolved = os.path.realpath(self.root / "opt/aegis")
        for mounted in (False, True):
            with self.subTest(mounted=mounted):
                mountinfo.write_text(f"10 1 8:1 /data {resolved}/logs rw - ext4 /dev/vdb rw\n" if mounted else "")
                result = self.run_shell('stat() { printf "0\\n"; }\nsafe_tree "${AEGIS_DIRS[1]}"')
                if mounted:
                    self.assert_failed(result)
                    self.assertIn("Mounted subtree", result.stderr)
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_safe_tree_rejects_symlinked_installation_directory(self):
        (self.root / "data/aegis").mkdir(parents=True)
        (self.root / "usr/local").mkdir(parents=True)
        (self.root / "usr/local/aegis").symlink_to(self.root / "data/aegis")
        result = self.run_shell(self.real_function("preflight_paths") + 'stat() { printf "0\\n"; }\npreflight_paths')
        self.assert_failed(result)
        self.assertIn("Refusing symlinked", result.stderr)

    def test_upstart_stop_only_targets_running_job(self):
        (self.root / "etc/init").mkdir()
        (self.root / "etc/init/aegis.conf").touch()
        for state, expected in (("aegis stop/waiting", False), ("aegis start/running, process 42", True)):
            with self.subTest(state=state):
                result = self.run_shell(
                    "systemd_available() { return 1; }\n"
                    'command_exists() { [[ "$1" == initctl ]]; }\n'
                    'timeout() { shift 3; "$@"; }\n'
                    f"initctl() {{ printf '%s\\n' {shlex.quote(state)}; }}\n"
                    "stop_services aegis"
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual("run initctl stop aegis" in self.events.read_text(), expected)

    def test_cmdline_without_trailing_nul_is_still_inspected(self):
        agent = str(self.root / "usr/local/aegis/AliYunDun")
        script = str(self.root / "usr/local/cloudmonitor/cloudmonitor.sh")
        (self.process(900050, agent, [agent]) / "cmdline").write_bytes(agent.encode())
        (self.process(900051, "/bin/bash", ["bash"]) / "cmdline").write_bytes(f"bash\0{script}".encode())
        result = self.run_shell('agent_processes "${AEGIS_DIRS[@]}" "${MONITOR_DIRS[@]}"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("900050|", result.stdout)
        self.assertIn("900051|", result.stdout)

    def test_respawned_process_receives_term_once(self):
        result = self.run_shell(
            r"""
            sleep() { :; }
            agent_processes() {
              local count
              count=$(( $(cat "$UAS_TEST_ROOT/tmp/scans" 2>/dev/null || echo 0) + 1 ))
              echo "$count" > "$UAS_TEST_ROOT/tmp/scans"
              case "$count" in
                1) printf '1|/a|1|x
' ;;
                2) printf '1|/a|1|x
2|/a|2|y
' ;;
              esac
            }
            signal_agent_processes() { record "signal $1 ${2//$'
'/,}"; }
            stop_agent_processes "${AEGIS_DIRS[@]}"
            """
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.events.read_text(), "signal TERM 1|/a|1|x\nsignal TERM 2|/a|2|y\n")

    def test_agent_below_symlinked_parent_is_matched_by_real_path(self):
        (self.root / "var/opt").mkdir(parents=True)
        (self.root / "opt").symlink_to("var/opt")
        agent = str(self.root / "opt/aegis/aegis_client/AliYunDun")
        for deleted in (False, True):
            with self.subTest(deleted=deleted):
                pid = 900061 if deleted else 900060
                if not deleted:
                    (self.root / "var/opt/aegis").mkdir()
                proc = self.process(pid, agent, [agent])
                if deleted:
                    (self.root / "var/opt/aegis").rmdir()
                    target = os.readlink(proc / "exe")
                    (proc / "exe").unlink()
                    (proc / "exe").symlink_to(target + " (deleted)")
                result = self.run_shell('agent_processes "${AEGIS_DIRS[@]}"')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f"{pid}|", result.stdout)
                shutil.rmtree(proc)

    def test_unrecognized_opt_aegis_directory_stops_preflight(self):
        target = self.root / "opt/aegis"
        target.mkdir(parents=True)
        (self.root / "proc/self").mkdir()
        (self.root / "proc/self/mountinfo").touch()
        script = self.real_function("preflight_paths") + 'stat() { printf "0\\n"; }\npreflight_paths'
        for marker in (None, "unrelated.conf", "aegis_client"):
            with self.subTest(marker=marker):
                if marker:
                    (target / marker).mkdir(exist_ok=True)
                result = self.run_shell(script)
                if marker == "unrelated.conf":
                    self.assert_failed(result)
                    self.assertIn("does not look like", result.stderr)
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_installation_directory_must_be_owned_by_root(self):
        (self.root / "usr/local/aegis").mkdir(parents=True)
        (self.root / "proc/self").mkdir()
        (self.root / "proc/self/mountinfo").touch()
        result = self.run_shell('stat() { printf "1000\\n"; }\nsafe_tree "${AEGIS_DIRS[0]}"')
        self.assert_failed(result)
        self.assertIn("not owned by root", result.stderr)

    def test_lock_falls_back_to_var_run_without_run(self):
        (self.root / "run").rmdir()
        (self.root / "var/run").mkdir()
        (self.root / "proc/self").mkdir()
        (self.root / "proc/self/mountinfo").touch()
        (self.root / "proc/self/status").touch()
        result = self.run_shell(
            self.real_function("prepare_runtime")
            + 'command_exists() { :; }\ntimeout() { :; }\nstat() { printf "0:700\\n"; }\n'
            'flock() { record "flock $*"; }\nprepare_runtime\nprintf "%s\\n" "$LOCK_DIR"'
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root / "var/run/uas.lock").is_dir())
        self.assertIn(f"{self.root}/var/run/uas.lock", result.stdout)
        self.assertEqual(self.events.read_text(), "flock -n 9\n")

    def test_backup_fails_when_symlink_scan_fails(self):
        (self.root / "usr/local/aegis/globalcfg").mkdir(parents=True)
        result = self.run_shell(
            self.real_function("backup_agent_config") + "find() { return 1; }\nbackup_agent_config"
        )
        self.assert_failed(result)
        self.assertIn("Cannot inspect", result.stderr)
        self.assertNotIn("run cp", self.events.read_text())

    def test_assist_package_status_uses_portable_dpkg_field(self):
        for status, installed in (
            ("install ok installed", True),
            ("deinstall ok config-files", True),
            ("unknown ok not-installed", False),
        ):
            with self.subTest(status=status):
                result = self.run_shell(
                    'command_exists() { [[ "$1" == dpkg-query ]]; }\n'
                    'timeout() { shift 3; [[ "$3" == -f=\\${Status} ]] || return 9; '
                    f"printf %s {shlex.quote(status)}; }}\nassist_packages"
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip() == "aliyun-assist", installed)

    def test_activating_units_stop_before_service(self):
        result = self.run_shell(
            'systemd_available() { return 0; }\n'
            'timeout() { printf "LoadState=loaded\\n"; }\n'
            'stop_services aegis'
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        stops = [line for line in self.events.read_text().splitlines() if " stop " in line]
        self.assertEqual(stops, [f"run systemctl stop aegis.{unit}" for unit in ("socket", "timer", "service")])

    def test_gnu_wget_download_forbids_redirects(self):
        result = self.run_shell(
            'command_exists() { [[ "$1" == wget ]]; }\n'
            'wget() { printf "  --max-redirect   maximum redirections\\n"; }\n'
            'download_file https://example.invalid/vendor.sh "$UAS_TEST_ROOT/tmp/download"'
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("run wget -q --max-redirect=0 --tries=1", self.events.read_text())

    def test_process_exiting_between_reads_is_not_an_inspection_failure(self):
        agent = str(self.root / "usr/local/aegis/AliYunDun")
        proc = self.process(900070, agent, [agent])
        result = self.run_shell(
            'readlink() {\n'
            f'  if [[ "$2" == {shlex.quote(str(proc / "exe"))} ]]; then : > {shlex.quote(str(proc / "cmdline"))}; return 1; fi\n'
            '  command readlink "$@"\n'
            '}\nagent_processes "${AEGIS_DIRS[@]}"'
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("900070|", result.stdout)
