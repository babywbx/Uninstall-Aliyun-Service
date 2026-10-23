import os

from test_uas import UasFixture


class ServiceMaskTests(UasFixture):
    def setUp(self):
        super().setUp()
        self.units = self.root / "etc/systemd/system"
        self.units.mkdir(parents=True)
        self.backup = self.root / "var/backups/uas-units.mock"
        self.backup.mkdir(parents=True, mode=0o700)

    def mask_mocks(self):
        return r'''
            stat() { printf '0\n'; }
            mktemp() {
              record "backup-directory $*"
              printf '%s\n' "$UAS_TEST_ROOT/var/backups/uas-units.mock"
            }
            timeout() {
              record "query $*"
              printf 'LoadState=masked\n'
            }
        '''

    def state_mocks(self):
        return r'''
            systemd_available() { return 0; }
            timeout() {
              case "${@: -1}" in
                aegis.service)
                  printf 'LoadState=masked\nActiveState=inactive\nFragmentPath=/dev/null\n'
                  ;;
                *) printf 'LoadState=not-found\nActiveState=inactive\nFragmentPath=\n' ;;
              esac
            }
        '''

    def test_local_unit_is_backed_up_before_replacement(self):
        unit = self.units / "aegis.service"
        unit.write_text("[Service]\nExecStart=/vendor/agent\n")
        result = self.run_shell(self.mask_mocks() + "FORCE=1\nmask_selected_service aegis.service")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        events = self.events.read_text().splitlines()
        copy = f"run cp -a -- {unit} {self.backup}/aegis.service"
        replace = f"run ln -sfn -- /dev/null {unit}"
        self.assertIn(copy, events)
        self.assertIn(replace, events)
        self.assertLess(events.index(copy), events.index(replace))
        self.assertLess(events.index(replace), events.index("run systemctl daemon-reload"))
        self.assertIn(
            f"backup-directory -d {self.root}/var/backups/uas-units.XXXXXX", events
        )

    def test_failed_backup_never_replaces_local_unit(self):
        unit = self.units / "aegis.service"
        unit.write_text("[Service]\nExecStart=/vendor/agent\n")
        result = self.run_shell(
            self.mask_mocks()
            + r'''
            run() { record "run $*"; [[ "$1" != cp ]] || return 1; }
            FORCE=1
            mask_selected_service aegis.service
            '''
        )
        self.assert_failed(result)
        self.assertNotIn("run ln ", self.events.read_text())
        self.assertNotIn("daemon-reload", self.events.read_text())
        self.assertFalse(unit.is_symlink())

    def test_immutable_local_unit_is_backed_up_before_repair_and_retry(self):
        unit = self.units / "aegis.service"
        unit.write_text("[Service]\nExecStart=/vendor/agent\n")
        result = self.run_shell(
            self.mask_mocks()
            + r'''
            link_attempts=0
            run() {
              record "run $*"
              if [[ "$1" == ln ]]; then
                link_attempts=$((link_attempts + 1))
                [[ "$link_attempts" -ne 1 ]] || return 1
              fi
              return 0
            }
            clear_blocking_attributes() { record "attribute-repair $1"; return 0; }
            FORCE=1
            mask_selected_service aegis.service
            '''
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        events = self.events.read_text().splitlines()
        copy = f"run cp -a -- {unit} {self.backup}/aegis.service"
        replace = f"run ln -sfn -- /dev/null {unit}"
        repair = f"attribute-repair {unit}"
        attempts = [index for index, event in enumerate(events) if event == replace]
        self.assertEqual(len(attempts), 2)
        self.assertEqual(events.count(copy), 1)
        self.assertEqual(events.count(repair), 1)
        self.assertLess(events.index(copy), attempts[0])
        self.assertLess(attempts[0], events.index(repair))
        self.assertLess(events.index(repair), attempts[1])
        self.assertLess(attempts[1], events.index("run systemctl daemon-reload"))

    def test_failed_attribute_repair_does_not_retry_mask_replacement(self):
        unit = self.units / "aegis.service"
        unit.write_text("[Service]\nExecStart=/vendor/agent\n")
        for status in (1, 124, 137):
            with self.subTest(repair_status=status):
                result = self.run_shell(
                    self.mask_mocks()
                    + f'''
                    run() {{ record "run $*"; [[ "$1" != ln ]] || return 1; }}
                    clear_blocking_attributes() {{ record attribute-repair; return {status}; }}
                    FORCE=1
                    mask_selected_service aegis.service
                    '''
                )
                self.assert_failed(result)
                events = self.events.read_text().splitlines()
                self.assertEqual(events.count(f"run ln -sfn -- /dev/null {unit}"), 1)
                self.assertNotIn("run systemctl daemon-reload", events)

    def test_successful_command_with_ineffective_mask_fails(self):
        result = self.run_shell(
            self.mask_mocks()
            + r'''
            timeout() { printf 'LoadState=loaded\n'; }
            FORCE=1
            mask_selected_service aegis.service
            '''
        )
        self.assert_failed(result)
        self.assertIn("mask is not effective", result.stderr)

    def test_mask_failure_or_timeout_does_not_reach_cleanup(self):
        for status in (1, 124, 137):
            for phase in ("link", "reload", "query"):
                with self.subTest(status=status, phase=phase):
                    result = self.run_shell(
                        self.mask_mocks()
                        + f'''
                        run() {{
                          record "run $*"
                          if [[ {phase} == link && "$1" == ln ]]; then return {status}; fi
                          if [[ {phase} == reload && "$1" == systemctl ]]; then return {status}; fi
                          return 0
                        }}
                        timeout() {{
                          record query
                          [[ {phase} != query ]] || return {status}
                          printf 'LoadState=masked\\n'
                        }}
                        clear_blocking_attributes() {{ record attribute-repair; return 1; }}
                        FORCE=1
                        mask_selected_service aegis.service || exit $?
                        record cleanup
                        '''
                    )
                    self.assert_failed(result)
                    events = self.events.read_text()
                    self.assertNotIn("cleanup", events)
                    if phase == "link":
                        self.assertNotIn("daemon-reload", events)
                    if phase != "query":
                        self.assertNotIn("query", events)
                    if status in (124, 137):
                        self.assertNotIn("attribute-repair", events)

    def test_existing_mask_is_preserved_while_real_unit_is_cleaned(self):
        mask = self.units / "aegis.service"
        mask.symlink_to("/dev/null")
        vendor_unit = self.root / "usr/lib/systemd/system/aegis.service"
        vendor_unit.parent.mkdir(parents=True)
        vendor_unit.write_text("[Service]\nExecStart=/vendor/agent\n")
        result = self.run_shell(
            r'''
            systemd_available() { return 0; }
            remove_path() { record "remove $1"; }
            mask_selected_service aegis.service
            cleanup_services aegis
            release_service_masks aegis
            '''
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        events = self.events.read_text().splitlines()
        self.assertNotIn(f"remove {mask}", events)
        self.assertIn(f"remove {vendor_unit}", events)
        self.assertNotIn(f"run rm -f -- {mask}", events)
        self.assertNotIn("run ln ", self.events.read_text())
        self.assertTrue(mask.is_symlink())

    def test_owned_mask_is_kept_until_explicit_release(self):
        mask = self.units / "aegis.service"
        mask.symlink_to("/dev/null")
        result = self.run_shell(
            r'''
            CREATED_MASKS=("$UAS_TEST_ROOT/etc/systemd/system/aegis.service")
            systemd_available() { return 0; }
            remove_path() { record "remove $1"; }
            mask_removed=0
            path_present() {
              if [[ "$1" == "${CREATED_MASKS[0]}" && "$mask_removed" -eq 1 ]]; then return 1; fi
              [[ -e "$1" || -L "$1" ]]
            }
            run() { record "run $*"; if [[ "$1" == rm ]]; then mask_removed=1; fi; return 0; }
            cleanup_services aegis
            record release-start
            release_service_masks aegis
            '''
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        events = self.events.read_text().splitlines()
        self.assertNotIn(f"remove {mask}", events)
        self.assertIn(f"run rm -f -- {mask}", events)
        self.assertLess(events.index("release-start"), events.index(f"run rm -f -- {mask}"))

    def test_component_masks_are_released_only_after_successful_removal(self):
        components = (
            ("cleanup_aegis_directory", "aegis agentwatch"),
            ("uninstall_cloud_assist", "AssistDaemon aliyun aliyun-service"),
            ("uninstall_cloudmonitor", "cloudmonitor"),
        )
        for component, services in components:
            for status in (0, 1):
                with self.subTest(component=component, removal_status=status):
                    result = self.run_shell(
                        r'''
                        FORCE=1
                        INCLUDE_ASSIST=1
                        INCLUDE_CLOUDMONITOR=1
                        stop_services() { :; }
                        stop_agent_processes() { :; }
                        cleanup_services() { :; }
                        assist_packages() { :; }
                        unmount_agent_mounts() { :; }
                        release_service_masks() { record "release $*"; }
                        '''
                        + f'remove_path() {{ record "remove $1"; return {status}; }}\n{component}'
                    )
                    events = self.events.read_text().splitlines()
                    if status:
                        self.assert_failed(result)
                        self.assertNotIn(f"release {services}", events)
                    else:
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                        self.assertEqual(events[-1], f"release {services}")

    def test_remaining_owned_mask_fails_verification(self):
        (self.units / "aegis.service").symlink_to("/dev/null")
        result = self.run_shell(
            self.state_mocks()
            + r'''
            CREATED_MASKS=("$UAS_TEST_ROOT/etc/systemd/system/aegis.service")
            verify_services aegis
            '''
        )
        self.assert_failed(result)

    def test_lower_priority_existing_mask_cannot_hide_owned_mask(self):
        (self.units / "aegis.service").symlink_to("/dev/null")
        runtime_mask = self.root / "run/systemd/system/aegis.service"
        runtime_mask.parent.mkdir(parents=True)
        runtime_mask.symlink_to("/dev/null")
        result = self.run_shell(
            self.state_mocks()
            + r'''
            CREATED_MASKS=("$UAS_TEST_ROOT/etc/systemd/system/aegis.service")
            verify_services aegis
            '''
        )
        self.assert_failed(result)

    def test_existing_inactive_mask_passes_verification(self):
        (self.units / "aegis.service").symlink_to("/dev/null")
        result = self.run_shell(self.state_mocks() + "verify_services aegis")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_relative_existing_mask_is_preserved_and_verified(self):
        mask = self.units / "aegis.service"
        target = os.path.relpath("/dev/null", self.units.resolve())
        mask.symlink_to(target)
        result = self.run_shell(
            self.state_mocks()
            + r'''
            remove_path() { record "remove $1"; }
            FORCE=1
            mask_selected_service aegis.service
            cleanup_services aegis
            release_service_masks aegis
            verify_services aegis
            '''
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        events = self.events.read_text()
        self.assertNotIn("run ln ", events)
        self.assertNotIn(f"remove {mask}", events)
        self.assertNotIn(f"run rm -f -- {mask}", events)
        self.assertEqual(os.readlink(mask), target)

    def test_mask_dry_run_does_not_change_files(self):
        unit = self.units / "aegis.service"
        unit.write_text("[Service]\nExecStart=/vendor/agent\n")
        before = self.file_snapshot()
        result = self.run_shell(
            self.mask_mocks() + "FORCE=1\nDRY_RUN=1\nmask_selected_service aegis.service"
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.events.read_text(), "")
        self.assertEqual(before, self.file_snapshot())

    def test_force_stops_unit_before_masking_it(self):
        result = self.run_shell(
            r'''
            systemd_available() { return 0; }
            timeout() {
              case "${@: -1}" in
                aegis.service) printf 'LoadState=loaded\n' ;;
                *) printf 'LoadState=not-found\n' ;;
              esac
            }
            mask_selected_service() { record "mask $1"; }
            FORCE=1
            stop_services aegis
            '''
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            self.events.read_text().splitlines(),
            ["run systemctl stop aegis.service", "mask aegis.service"],
        )

    def test_disable_or_mask_failure_blocks_process_fallback(self):
        for force in (0, 1):
            with self.subTest(force=force):
                result = self.run_shell(
                    r'''
                    systemd_available() { return 0; }
                    timeout() {
                      case "${@: -1}" in
                        aegis.service) printf 'LoadState=loaded\n' ;;
                        *) printf 'LoadState=not-found\n' ;;
                      esac
                    }
                    run() { record "run $*"; [[ "${2:-}" != disable ]] || return 1; }
                    mask_selected_service() { record "mask $1"; return 1; }
                    stop_agent_processes() { record process-fallback; }
                    cleanup_services() { record service-cleanup; }
                    '''
                    + f"FORCE={force}\ncleanup_legacy_leftovers"
                )
                self.assert_failed(result)
                self.assertNotIn("process-fallback", self.events.read_text())
                self.assertNotIn("service-cleanup", self.events.read_text())
