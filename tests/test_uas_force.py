import os
import shlex

from test_uas import UasFixture


class ForceTests(UasFixture):
    def test_mounted_file_cannot_have_attributes_changed(self):
        target = self.root / "usr/local/aegis/immutable"
        target.parent.mkdir(parents=True)
        target.write_text("fixture\n")
        (self.root / "proc/self").mkdir()
        (self.root / "proc/self/mountinfo").write_text(
            f"10 1 8:1 /outside {os.path.realpath(target)} rw - ext4 /dev/root rw\n"
        )
        result = self.run_shell(
            'lsattr() { record unexpected-attributes; return 1; }\n'
            'FORCE=1\nclear_blocking_attributes '
            + shlex.quote(str(target))
        )
        self.assert_failed(result)
        self.assertIn("mounted file", result.stderr)
        self.assertNotIn("unexpected-attributes", self.events.read_text())

    def test_force_quartz_fallback_rechecks_processes_before_removing_files(self):
        for status in (1, 124, 137):
            with self.subTest(status=status):
                result = self.run_shell(
                    f"run_legacy_quartz_cleanup() {{ record quartz; return {status}; }}\n"
                    + r"""
                    preflight_launcher() { :; }
                    run_official_uninstall() { return 0; }
                    cleanup_legacy_leftovers() { record services; }
                    stop_agent_processes() { record processes; }
                    cleanup_aegis_directory() { record directory; }
                    uninstall_cloud_assist() { :; }
                    uninstall_cloudmonitor() { :; }
                    verify_uninstall() { record verify; return 0; }
                    main --yes --force
                    """
                )
                if status == 1:
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual(
                        self.events.read_text(),
                        "services\nquartz\nprocesses\ndirectory\nverify\n",
                    )
                else:
                    self.assert_failed(result)
                    self.assertNotIn("processes", self.events.read_text())
                    self.assertNotIn("directory", self.events.read_text())

    def test_safe_tree_decodes_mountinfo_paths_with_spaces_and_backslashes(self):
        (self.root / "proc/self").mkdir()
        mountinfo = self.root / "proc/self/mountinfo"
        for name in ("aegis data", r"aegis\data"):
            directory = self.root / "usr/local" / name
            directory.mkdir(parents=True)
            resolved = os.path.realpath(directory)
            encoded = resolved.replace("\\", r"\134").replace(" ", r"\040")
            for mounted in (False, True):
                with self.subTest(name=name, mounted=mounted):
                    mountinfo.write_text(
                        f"10 1 8:1 /data {encoded}/logs rw - ext4 /dev/vdb rw\n"
                        if mounted
                        else ""
                    )
                    result = self.run_shell(
                        'stat() { printf "0\\n"; }\nsafe_tree '
                        + shlex.quote(str(directory))
                    )
                    if mounted:
                        self.assert_failed(result)
                    else:
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def launcher_fixture(self, executable, arguments):
        pid = os.getpid()
        proc = self.root / f"proc/{pid}"
        proc.mkdir(parents=True)
        (self.root / "proc/self").mkdir(exist_ok=True)
        (self.root / "proc/self/status").touch()
        (self.root / "proc/self/cgroup").touch()
        (proc / "exe").symlink_to(os.path.realpath(executable))
        (proc / "cmdline").write_bytes(
            b"\0".join(argument.encode() for argument in arguments) + b"\0"
        )
        fields = ["S", "1", *(["0"] * 17), "100"]
        (proc / "stat").write_text(f"{pid} (agent parent) {' '.join(fields)}\n")

    def test_launcher_rejects_shell_agent_parent_but_allows_dry_run(self):
        agent = str(self.root / "usr/local/share/aliyun-assist/aliyun-service")
        self.launcher_fixture("/bin/bash", ["bash", agent])
        for dry_run in (0, 1):
            with self.subTest(dry_run=dry_run):
                result = self.run_shell(
                    f"INCLUDE_ASSIST=1\nDRY_RUN={dry_run}\npreflight_launcher"
                )
                if dry_run:
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                else:
                    self.assert_failed(result)
                self.assertEqual(self.events.read_text(), "")

    def test_launcher_allows_dry_run_from_direct_agent_parent(self):
        agent = str(self.root / "usr/local/aegis/aegis_client/AliYunDun")
        self.launcher_fixture(agent, [agent])
        result = self.run_shell("DRY_RUN=1\npreflight_launcher")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.events.read_text(), "")

    def attribute_case(
        self,
        force=1,
        status=1,
        blocking=1,
        dry_run=0,
        symlink=0,
        hardlinks=1,
        chattr_status=0,
        retry_status=0,
    ):
        target = self.root / "usr/local/aegis"
        target.mkdir(parents=True, exist_ok=True)
        for name in ("immutable", "append", "ordinary"):
            (target / name).write_text("fixture data\n")
        outside = self.root / "outside"
        outside.write_text("do not modify\n")
        linked = target / "linked"
        if not linked.is_symlink():
            linked.symlink_to(outside)
        if hardlinks > 1:
            os.link(target / "immutable", self.root / "immutable-link")
        before = self.file_snapshot()
        result = self.run_shell(
            f"FORCE={force}\nDRY_RUN={dry_run}\nRM_STATUS={status}\n"
            f"HAS_BLOCKING={blocking}\nLINK_TARGET={symlink}\n"
            f"HARDLINKS={hardlinks}\nCHATTR_STATUS={chattr_status}\nRETRY_STATUS={retry_status}\n"
            + r"""
            exec 3>&1
            ATTR_TARGET="$UAS_TEST_ROOT/usr/local/aegis"
            WORKDIR="$UAS_TEST_ROOT/tmp"
            RM_ATTEMPTS=0
            REMOVED=0
            ROOT_CLEARED=0
            IMMUTABLE_CLEARED=0
            APPEND_CLEARED=0
            safe_tree() { :; }
            stat() {
              case "$2" in
                %u) printf '0\n' ;;
                %h)
                  if [[ "$3" == "$ATTR_TARGET/immutable" ]]; then
                    printf '%s\n' "$HARDLINKS"
                  else
                    printf '1\n'
                  fi
                  ;;
                *) blocked stat "$@" ;;
              esac
            }
            rm() {
              if [[ "$#" -ne 3 || "$1" != -f || "$2" != -- ||
                    "${3%/*}" != "$UAS_TEST_ROOT/tmp" || "${3##*/}" != uas-attrs.* ||
                    ! -f "$3" || -L "$3" ]]; then
                blocked rm "$@"
                return 97
              fi
              command rm -f -- "$3"
            }
            umount() { blocked umount "$@"; }
            find() {
              local item
              for item in "$@"; do
                case "$item" in
                  /*) [[ "$item" == "$ATTR_TARGET" || "$item" == "$ATTR_TARGET/"* ]] || {
                    blocked find "$@"
                    return 97
                  } ;;
                esac
              done
              command find "$@"
            }
            path_present() {
              [[ "$REMOVED" -eq 0 ]] || return 1
              [[ -e "$1" || -L "$1" ]]
            }
            lsattr() {
              local item flags='-------------e-------'
              for item in "$@"; do :; done
              record "lsattr $item"
              if [[ -L "$item" ]]; then
                blocked lsattr-symlink "$item"
                return 97
              fi
              if [[ "$HAS_BLOCKING" -eq 1 ]]; then
                case "$item" in
                  "$ATTR_TARGET") [[ "$ROOT_CLEARED" -eq 1 ]] || flags='----ia-------e-------' ;;
                  "$ATTR_TARGET/immutable") [[ "$IMMUTABLE_CLEARED" -eq 1 ]] || flags='----i--------e-------' ;;
                  "$ATTR_TARGET/append") [[ "$APPEND_CLEARED" -eq 1 ]] || flags='-----a-------e-------' ;;
                esac
              fi
              printf '%s %s\n' "$flags" "$item"
            }
            chattr() {
              [[ "$#" -eq 3 && "$1" == -ia && "$2" == -- && ! -L "$3" ]] || {
                blocked chattr "$@"
                return 97
              }
              if [[ "$CHATTR_STATUS" -ne 0 ]]; then
                record "chattr-failed $3"
                return "$CHATTR_STATUS"
              fi
              case "$3" in
                "$ATTR_TARGET") ROOT_CLEARED=1 ;;
                "$ATTR_TARGET/immutable") IMMUTABLE_CLEARED=1 ;;
                "$ATTR_TARGET/append") APPEND_CLEARED=1 ;;
                *) blocked chattr-unverified "$@"; return 97 ;;
              esac
              record "attributes-cleared $3"
            }
            timeout() {
              if [[ "$1" != -k || "$2" != 5 || "$3" != 120 ]]; then
                blocked timeout "$@"
                return 97
              fi
              shift 3
              case "$1" in
                lsattr) shift; lsattr "$@" ;;
                *) blocked timeout "$@" ;;
              esac
            }
            run() {
              if [[ "$DRY_RUN" -eq 1 ]]; then
                record "plan $*"
                return 0
              fi
              case "$1" in
                rm)
                  RM_ATTEMPTS=$((RM_ATTEMPTS + 1))
                  record "rm-attempt $RM_ATTEMPTS"
                  [[ "$RM_ATTEMPTS" -ne 1 ]] || return "$RM_STATUS"
                  [[ "$RETRY_STATUS" -eq 0 ]] || return "$RETRY_STATUS"
                  REMOVED=1
                  return 0
                  ;;
                chattr) shift; chattr "$@" ;;
                find) shift; find "$@" ;;
                *) blocked run "$@" ;;
              esac
            }
            if [[ "$LINK_TARGET" -eq 1 ]]; then
              remove_path "$ATTR_TARGET/linked"
            else
              remove_path "$ATTR_TARGET"
            fi
            """
        )
        self.assertEqual(before, self.file_snapshot())
        return result, target

    def test_force_clears_only_verified_blocking_attributes_before_one_retry(self):
        result, target = self.attribute_case()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        events = self.events.read_text().splitlines()
        self.assertEqual(
            [event for event in events if event.startswith("rm-attempt ")],
            ["rm-attempt 1", "rm-attempt 2"],
        )
        self.assertCountEqual(
            [event for event in events if event.startswith("attributes-cleared ")],
            [
                f"attributes-cleared {target}",
                f"attributes-cleared {target / 'immutable'}",
                f"attributes-cleared {target / 'append'}",
            ],
        )
        self.assertFalse(any(str(target / "linked") in event for event in events))
        self.assertEqual(events[-1], "rm-attempt 2")

    def test_attribute_repair_requires_force_and_an_ordinary_failure(self):
        for force, status in ((0, 1), (1, 124), (1, 137)):
            with self.subTest(force=force, status=status):
                result, _ = self.attribute_case(force=force, status=status)
                self.assert_failed(result)
                events = self.events.read_text()
                self.assertEqual(events.count("rm-attempt "), 1)
                self.assertNotIn("attributes-cleared ", events)

    def test_force_does_not_retry_without_blocking_attributes(self):
        result, _ = self.attribute_case(blocking=0)
        self.assert_failed(result)
        events = self.events.read_text()
        self.assertEqual(events.count("rm-attempt "), 1)
        self.assertNotIn("attributes-cleared ", events)

    def test_force_dry_run_does_not_change_attributes_or_delete_files(self):
        result, _ = self.attribute_case(dry_run=1)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        events = self.events.read_text()
        self.assertNotIn("attributes-cleared ", events)
        self.assertNotIn("rm-attempt ", events)
        self.assertNotIn("lsattr ", events)

    def test_force_does_not_repair_a_symlink_target(self):
        result, _ = self.attribute_case(symlink=1)
        self.assert_failed(result)
        events = self.events.read_text()
        self.assertEqual(events.count("rm-attempt "), 1)
        self.assertNotIn("attributes-cleared ", events)
        self.assertNotIn("lsattr ", events)

    def test_force_does_not_change_attributes_on_multiply_linked_files(self):
        result, target = self.attribute_case(hardlinks=2)
        self.assert_failed(result)
        events = self.events.read_text()
        self.assertIn(f"lsattr {target / 'immutable'}", events)
        self.assertNotIn(f"attributes-cleared {target / 'immutable'}", events)
        self.assertEqual(events.count("rm-attempt "), 1)

    def test_failed_attribute_change_prevents_removal_retry(self):
        result, _ = self.attribute_case(chattr_status=1)
        self.assert_failed(result)
        events = self.events.read_text()
        self.assertIn("chattr-failed ", events)
        self.assertNotIn("attributes-cleared ", events)
        self.assertEqual(events.count("rm-attempt "), 1)

    def test_failed_removal_retry_is_not_reported_as_success(self):
        result, _ = self.attribute_case(retry_status=1)
        self.assert_failed(result)
        events = self.events.read_text()
        self.assertEqual(events.count("rm-attempt "), 2)
        self.assertIn("attributes-cleared ", events)
