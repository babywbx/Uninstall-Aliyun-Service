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
