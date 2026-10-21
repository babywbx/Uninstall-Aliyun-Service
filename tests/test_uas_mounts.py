import os
import shlex

from test_uas import UasFixture


class MountTests(UasFixture):
    def setUp(self):
        super().setUp()
        self.agent = self.root / "usr/local/aegis"
        self.agent.mkdir(parents=True)
        (self.root / "proc/self").mkdir()
        self.mountinfo = self.root / "proc/self/mountinfo"
        self.mountinfo.touch()

    @staticmethod
    def encode_path(path):
        return (
            str(path)
            .replace("\\", r"\134")
            .replace(" ", r"\040")
            .replace("\t", r"\011")
            .replace("\n", r"\012")
        )

    def mount(self, target, filesystem="debugfs", root="/", mount_id=10):
        target.mkdir(parents=True, exist_ok=True)
        return (
            f"{mount_id} 1 0:{mount_id} {self.encode_path(root)} "
            f"{self.encode_path(os.path.realpath(target))} rw - {filesystem} none rw\n"
        )

    def inspect(self, script):
        return self.run_shell('stat() { printf "0\\n"; }\n' + script)

    def remove_mock(self):
        return r'''
            run() {
              record "run $*"
              [[ $# -eq 3 && "$1" == umount && "$2" == -- ]] || return 97
              local snapshot="" line="" mounted=""
              snapshot="$(cat "$PROC_ROOT/self/mountinfo")"
              : > "$PROC_ROOT/self/mountinfo"
              while IFS= read -r line; do
                read -r _ _ _ _ mounted _ <<<"$line"
                decode_mount_path "$mounted" mounted
                [[ "$mounted" == "$3" ]] || printf '%s\n' "$line" >> "$PROC_ROOT/self/mountinfo"
              done <<<"$snapshot"
            }
        '''

    def test_mountinfo_escapes_and_literal_backslashes_are_matched(self):
        for suffix in ("space name", "tab\tname", "line\nname", r"slash\name", r"literal\040name"):
            with self.subTest(suffix=suffix):
                target = self.root / "var" / suffix / "aegis"
                target.mkdir(parents=True)
                opt = self.root / "opt"
                if opt.is_symlink():
                    opt.unlink()
                elif opt.is_dir():
                    opt.rmdir()
                opt.symlink_to(target.parent)
                self.mountinfo.write_text(self.mount(target / "logs", "ext4"))
                result = self.inspect('safe_tree "${AEGIS_DIRS[1]}"')
                self.assert_failed(result)
                self.assertIn("Mounted subtree", result.stderr)

    def test_managed_mounts_require_force_and_preflight_opt_in(self):
        self.mountinfo.write_text(self.mount(self.agent / "aegis_debug"))
        for force, allow, accepted in ((0, 0, False), (0, 1, False), (1, 0, False), (1, 1, True)):
            with self.subTest(force=force, allow=allow):
                result = self.inspect(f'FORCE={force}\nsafe_tree "${{AEGIS_DIRS[0]}}" {allow}')
                self.assertEqual(result.returncode == 0, accepted, result.stderr)
                self.assertEqual(self.events.read_text(), "")

    def test_preflight_allows_only_managed_mounts_in_force_mode(self):
        self.mountinfo.write_text(self.mount(self.agent / "aegis_debug"))
        for force in (0, 1):
            with self.subTest(force=force):
                result = self.inspect(
                    self.real_function("preflight_paths") + f"FORCE={force}\npreflight_paths"
                )
                self.assertEqual(result.returncode == 0, bool(force), result.stderr)

    def test_whitelisted_positions_and_filesystems(self):
        for location, filesystem in (
            ("aegis_debug", "debugfs"),
            ("aegis_debug", "tracefs"),
            ("cgroup", "cgroup"),
            ("cgroup", "cgroup2"),
            ("cgroup/cpu", "cgroup"),
            ("cgroup/cpu", "cgroup2"),
        ):
            with self.subTest(location=location, filesystem=filesystem):
                self.mountinfo.write_text(self.mount(self.agent / location, filesystem))
                result = self.inspect('FORCE=1\nsafe_tree "${AEGIS_DIRS[0]}" 1')
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_unknown_mounts_are_rejected_before_any_unmount(self):
        for location, filesystem, root in (
            ("logs", "debugfs", "/"),
            ("aegis_debug/data", "ext4", "/"),
            ("cgroup", "tmpfs", "/"),
            ("aegis_debug", "debugfs", "/subtree"),
            ("aegis_debug\n", "debugfs", "/"),
        ):
            with self.subTest(location=location, filesystem=filesystem, root=root):
                records = self.mount(self.agent / "cgroup/cpu", "cgroup", mount_id=10)
                records += self.mount(self.agent / location, filesystem, root, mount_id=20)
                self.mountinfo.write_text(records)
                result = self.inspect('FORCE=1\nunmount_agent_mounts "${AEGIS_DIRS[0]}"')
                self.assert_failed(result)
                self.assertEqual(self.events.read_text(), "")

    def test_other_component_cannot_use_aegis_mount_allowlist(self):
        target = self.root / "usr/local/cloudmonitor"
        self.mountinfo.write_text(self.mount(target / "aegis_debug"))
        result = self.inspect('FORCE=1\nunmount_agent_mounts "${MONITOR_DIRS[0]}"')
        self.assert_failed(result)
        self.assertEqual(self.events.read_text(), "")

    def test_mountpoint_must_not_redirect_outside_installation(self):
        outside = self.root / "var/shared"
        outside.mkdir()
        (self.agent / "cgroup").symlink_to(outside)
        encoded = self.encode_path(os.path.realpath(self.agent) + "/cgroup")
        self.mountinfo.write_text(f"10 1 0:10 / {encoded} rw - cgroup none rw\n")
        result = self.inspect('FORCE=1\nunmount_agent_mounts "${AEGIS_DIRS[0]}"')
        self.assert_failed(result)
        self.assertEqual(self.events.read_text(), "")

    def test_stacked_mounts_are_rejected_before_any_unmount(self):
        target = self.agent / "aegis_debug"
        self.mountinfo.write_text(self.mount(target, mount_id=10) + self.mount(target, mount_id=20))
        result = self.inspect('FORCE=1\nunmount_agent_mounts "${AEGIS_DIRS[0]}"')
        self.assert_failed(result)
        self.assertIn("Stacked mounts", result.stderr)
        self.assertEqual(self.events.read_text(), "")

    def test_unmounts_deepest_first_and_rechecks_empty_mount_table(self):
        parent = self.agent / "cgroup"
        child = parent / "cpu"
        self.mountinfo.write_text(
            self.mount(parent, "cgroup2", mount_id=10) + self.mount(child, "cgroup", mount_id=20)
        )
        result = self.inspect(self.remove_mock() + 'FORCE=1\nunmount_agent_mounts "${AEGIS_DIRS[0]}"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.events.read_text(),
            f"run umount -- {os.path.realpath(child)}\nrun umount -- {os.path.realpath(parent)}\n",
        )
        self.assertEqual(self.mountinfo.read_text(), "")

    def test_dry_run_lists_unmounts_without_changing_mount_table(self):
        target = self.agent / "aegis_debug"
        records = self.mount(target)
        self.mountinfo.write_text(records)
        result = self.inspect(
            self.real_function("run") + 'exec 3>&1\nFORCE=1\nDRY_RUN=1\nunmount_agent_mounts "${AEGIS_DIRS[0]}"'
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"[DRY-RUN] umount -- {os.path.realpath(target)}", result.stdout)
        self.assertEqual(self.mountinfo.read_text(), records)
        self.assertEqual(self.events.read_text(), "")

    def test_successful_umount_status_with_remaining_mount_is_failure(self):
        self.mountinfo.write_text(self.mount(self.agent / "aegis_debug"))
        result = self.inspect('FORCE=1\nunmount_agent_mounts "${AEGIS_DIRS[0]}"')
        self.assert_failed(result)
        self.assertIn("Mount remained or changed", result.stderr)
        self.assertEqual(len(self.events.read_text().splitlines()), 1)

    def test_changed_mount_id_or_root_stops_before_umount(self):
        target = self.agent / "aegis_debug"
        initial = self.mount(target)
        for changed in (self.mount(target, mount_id=90), self.mount(target, root="/subtree")):
            with self.subTest(changed=changed):
                self.mountinfo.write_text(initial)
                counter = self.root / "tmp/mount-reads"
                if counter.exists():
                    counter.unlink()
                original = self.real_function("mount_records").replace("mount_records()", "original_mount_records()", 1)
                script = original + (
                    'mount_records() {\n'
                    '  local count\n'
                    '  count=$(( $(cat "$UAS_TEST_ROOT/tmp/mount-reads" 2>/dev/null || echo 0) + 1 ))\n'
                    '  printf "%s" "$count" > "$UAS_TEST_ROOT/tmp/mount-reads"\n'
                    f'  if [[ "$count" -eq 3 ]]; then printf %s {shlex.quote(changed)} > "$PROC_ROOT/self/mountinfo"; fi\n'
                    '  original_mount_records "$@"\n'
                    '}\nFORCE=1\nunmount_agent_mounts "${AEGIS_DIRS[0]}"'
                )
                result = self.inspect(script)
                self.assert_failed(result)
                self.assertIn("Mount identities changed", result.stderr)
                self.assertEqual(self.events.read_text(), "")

    def test_remount_after_first_unmount_stops_remaining_cleanup(self):
        parent = self.agent / "cgroup"
        child = parent / "cpu"
        initial = self.mount(parent, "cgroup2", mount_id=10) + self.mount(child, "cgroup", mount_id=20)
        changed = self.mount(parent, "cgroup2", mount_id=99)
        self.mountinfo.write_text(initial)
        result = self.inspect(
            'run() { record "run $*"; '
            f'printf %s {shlex.quote(changed)} > "$PROC_ROOT/self/mountinfo"; }}\n'
            'FORCE=1\nunmount_agent_mounts "${AEGIS_DIRS[0]}"'
        )
        self.assert_failed(result)
        self.assertEqual(self.events.read_text(), f"run umount -- {os.path.realpath(child)}\n")

    def test_symlinked_parent_preserves_exact_decoded_unmount_target(self):
        parent = self.root / "var" / "mount space\tline\nslash\\040"
        target = parent / "aegis/aegis_debug"
        target.mkdir(parents=True)
        (self.root / "opt").symlink_to(parent)
        self.mountinfo.write_text(self.mount(target))
        result = self.inspect(self.remove_mock() + 'FORCE=1\nunmount_agent_mounts "${AEGIS_DIRS[1]}"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.events.read_text(), f"run umount -- {os.path.realpath(target)}\n")
