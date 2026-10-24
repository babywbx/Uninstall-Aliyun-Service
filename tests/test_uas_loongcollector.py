from test_uas import UasFixture


class LoongCollectorTests(UasFixture):
    def test_only_its_own_option_selects_loongcollector(self):
        result = self.run_shell(
            r'''
            parse_args --include-cloudmonitor
            selected_dirs; selected_services
            echo ---
            parse_args --include-loongcollector
            selected_dirs; selected_services
            '''
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        monitor, loong = result.stdout.split("---\n")
        self.assertNotIn("ilogtail", monitor)
        self.assertNotIn("loongcollectord", monitor)
        for item in (
            f"{self.root}/usr/local/ilogtail",
            f"{self.root}/etc/ilogtail",
            "ilogtaild",
            "loongcollectord",
        ):
            self.assertIn(f"{item}\n", loong)

    def test_dry_run_lists_component_files_without_changes(self):
        binary = self.root / "usr/local/ilogtail"
        binary.mkdir(parents=True)
        (binary / "loongcollector_3.3.2").write_text("fixture\n")
        config = self.root / "etc/ilogtail/users"
        config.mkdir(parents=True)
        (config / "1234").touch()
        init = self.root / "etc/init.d"
        init.mkdir()
        for name in ("loongcollectord", "ilogtaild"):
            (init / name).write_text("#!/bin/sh\n")
            (init / name).chmod(0o755)
        rc3 = self.root / "etc/rc.d/rc3.d"
        rc3.mkdir(parents=True)
        (rc3 / "S55loongcollectord").symlink_to(init / "loongcollectord")
        units = self.root / "etc/systemd/system"
        (units / "default.target.wants").mkdir(parents=True)
        (units / "loongcollectord.service").write_text("[Service]\n")
        (units / "default.target.wants/loongcollectord.service").symlink_to(
            units / "loongcollectord.service"
        )
        (self.root / "proc/self").mkdir()
        (self.root / "proc/self/status").touch()
        (self.root / "proc/self/mountinfo").touch()
        before = self.file_snapshot()
        result = self.run_shell(
            self.real_function("run")
            + r"""
            stat() { printf '0\n'; }
            detect_ecs() { return 1; }
            download_file() { record "download $1"; }
            verify_uninstall() { record verify; }
            main --dry-run --include-loongcollector
            """
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.events.read_text(), "")
        self.assertIn(f"[DRY-RUN] {init / 'ilogtaild'} stop", result.stdout)
        for path in (binary, self.root / "etc/ilogtail"):
            self.assertIn(f"[DRY-RUN] rm -rf -- {path}", result.stdout)
        for path in (
            init / "loongcollectord",
            init / "ilogtaild",
            rc3 / "S55loongcollectord",
            units / "loongcollectord.service",
            units / "default.target.wants/loongcollectord.service",
        ):
            self.assertIn(f"[DRY-RUN] rm -f -- {path}", result.stdout)
        self.assertEqual(before, self.file_snapshot())

    def test_config_agent_must_stop_before_component_files_are_removed(self):
        binary = self.root / "etc/ilogtail/telegraf/telegraf"
        binary.parent.mkdir(parents=True)
        binary.write_text("fixture\n")
        (self.root / "usr/local/ilogtail").mkdir(parents=True)
        (self.root / "proc/self").mkdir()
        (self.root / "proc/self/status").touch()
        process = self.root / "proc/900100"
        process.mkdir()
        (process / "exe").symlink_to(binary.resolve())
        fields = ["S", *(["0"] * 18), "100"]
        (process / "stat").write_text(f"900100 (telegraf) {' '.join(fields)}\n")

        for exits_on_term in (False, True):
            with self.subTest(exits_on_term=exits_on_term):
                (process / "cmdline").write_bytes(str(binary).encode() + b"\0")
                result = self.run_shell(
                    f"exits_on_term={int(exits_on_term)}\n"
                    + r"""
                    INCLUDE_LOONGCOLLECTOR=1
                    stop_services() { :; }
                    cleanup_services() { :; }
                    release_service_masks() { :; }
                    sleep() { :; }
                    kill() {
                      [[ "$*" == '-TERM 900100' ]] || return 97
                      record "kill $*"
                      if [[ "${exits_on_term}" -eq 1 ]]; then
                        : > "${PROC_ROOT}/900100/cmdline"
                      fi
                    }
                    remove_path() { record "remove $1"; }
                    status=0
                    uninstall_loongcollector || status=$?
                    exit "${status}"
                    """
                )
                events = self.events.read_text().splitlines()
                if exits_on_term:
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual(events, [
                        "kill -TERM 900100",
                        f"remove {self.root}/usr/local/ilogtail",
                        f"remove {self.root}/etc/ilogtail",
                    ])
                else:
                    self.assert_failed(result)
                    self.assertEqual(events, ["kill -TERM 900100"])
