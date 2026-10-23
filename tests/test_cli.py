from __future__ import annotations

import argparse
import contextlib
import io
import os
from types import SimpleNamespace
import unittest
from unittest import mock

from kilix_waydroid import cli, system


class ExecCalled(Exception):
    pass


class CLITests(unittest.TestCase):
    def test_size_parser_is_bounded(self):
        self.assertEqual(cli.parse_size("960x600"), (960, 600))
        for value in ("bad", "319x600", "960x239", "20000x600"):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                cli.parse_size(value)

    def test_first_use_install_defaults_on_and_has_explicit_opt_out(self):
        parser = cli.build_parser()
        self.assertTrue(parser.parse_args(["window"]).install)
        self.assertFalse(parser.parse_args(["window", "--no-install"]).install)

    def test_auto_prefers_a_pane_in_kilix_and_a_window_in_desktops(self):
        with mock.patch.dict(
            os.environ,
            {"DISPLAY": ":0", "KITTY_WINDOW_ID": "7"},
            clear=True,
        ):
            self.assertEqual(cli._auto_surface(), "pane")
        with mock.patch.dict(
            os.environ,
            {
                "DISPLAY": ":77",
                "KITTY_WINDOW_ID": "7",
                "KILIX_IN_OVERLAY": "1",
            },
            clear=True,
        ):
            self.assertEqual(cli._auto_surface(), "window")
        with mock.patch.dict(os.environ, {"DISPLAY": ":0"}, clear=True):
            self.assertEqual(cli._auto_surface(), "window")

    def test_pane_reuses_kilix_run_and_reenters_only_for_waydroid(self):
        host_sdk = SimpleNamespace(paths=object())
        seen = {}

        def execute(program, argv, environment):
            seen.update(program=program, argv=argv, environment=environment)
            raise ExecCalled

        args = SimpleNamespace(
            size=(1280, 720), waydroid="waydroid-fixture", weston="weston-fixture")
        with mock.patch.object(cli.sdk, "load", return_value=host_sdk), \
                mock.patch.object(cli, "_preflight", return_value=[]), \
                mock.patch.object(cli, "_kilix_launcher", return_value="/kilix"), \
                mock.patch.object(cli, "_launcher", return_value="/kilix-waydroid"), \
                mock.patch.object(cli.os, "execvpe", side_effect=execute):
            with self.assertRaises(ExecCalled):
                cli._run_pane(args)
        self.assertEqual(seen["program"], "/kilix")
        self.assertEqual(
            seen["argv"],
            [
                "/kilix", "run", "--size=1280x720", "--refit-windows",
                "/kilix-waydroid", "window", "--size", "1280x720",
                "--waydroid", "waydroid-fixture", "--weston", "weston-fixture",
            ],
        )

    def test_window_can_fit_the_provider_owned_x_display(self):
        host_sdk = SimpleNamespace(
            xapp=SimpleNamespace(display_size=lambda: (1110, 700)))
        args = SimpleNamespace(
            fit_parent=True, size=None, waydroid="waydroid", weston="weston")
        with mock.patch.object(cli.sdk, "load", return_value=host_sdk), \
                mock.patch.object(cli, "_preflight", return_value=[]), \
                mock.patch.object(system, "resolve_command", side_effect=lambda value: value), \
                mock.patch.object(cli.runtime, "run_window", return_value=0) as launch:
            self.assertEqual(cli._run_window(args), 0)
        launch.assert_called_once_with(
            host_sdk,
            width=1110,
            height=700,
            waydroid="waydroid",
            weston="weston",
        )

    def test_preflight_runs_first_use_setup_once_then_reprobes(self):
        missing = [system.Check(
            "waydroid-command", "error", "Waydroid command is missing")]
        ready = [system.Check(
            "waydroid-command", "ok", "Waydroid command is available")]
        host_sdk = object()
        with mock.patch.object(
                system, "doctor_checks", side_effect=(missing, ready)) as doctor, \
                mock.patch.object(cli.first_use, "install") as install:
            self.assertEqual(cli._preflight(
                host_sdk=host_sdk,
                lazy_install=True,
                waydroid="waydroid",
                weston="weston",
            ), ready)
        install.assert_called_once_with(host_sdk)
        self.assertEqual(doctor.call_count, 2)

    def test_preflight_retries_setup_after_late_service_failure(self):
        installed = [
            system.Check(check_id, "ok", "installed")
            for check_id in ("waydroid-command", "weston-command", "initialized")
        ]
        incomplete = installed + [system.Check(
            "container-service", "error", "inactive")]
        ready = installed + [system.Check("container-service", "ok", "active")]
        privilege = SimpleNamespace(run_helper=mock.Mock(side_effect=(1, 0)))
        host_sdk = SimpleNamespace(privilege=privilege)
        with mock.patch.object(system, "doctor_checks",
                               side_effect=(incomplete, incomplete, ready)) as doctor, \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(cli.runtime.LaunchError, "launch again to retry"):
                cli._preflight(host_sdk=host_sdk, lazy_install=True)
            self.assertEqual(cli._preflight(host_sdk=host_sdk, lazy_install=True), ready)
        self.assertEqual(doctor.call_count, 3)
        self.assertEqual(privilege.run_helper.call_args_list, [mock.call(
            cli.first_use.SYSTEM_INSTALLER,
            title="Install Android + Weston (about 1 GB)",
        )] * 2)

    def test_service_retry_still_rejects_unrelated_or_persistent_failures(self):
        service = system.Check("container-service", "error", "inactive")
        for blocker in (None, system.Check("session-bus", "error", "missing")):
            checks = [service] + ([blocker] if blocker else [])
            with self.subTest(blocker=blocker), \
                    mock.patch.object(system, "doctor_checks", return_value=checks), \
                    mock.patch.object(cli.first_use, "install") as install, \
                    contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(cli.runtime.LaunchError, "prerequisites"):
                    cli._preflight(host_sdk=object(), lazy_install=True)
                self.assertEqual(install.call_count, 0 if blocker else 1)

    def test_preflight_never_installs_for_opt_out_or_custom_commands(self):
        missing = [system.Check(
            "weston-command", "error", "Weston command is missing")]
        for lazy_install, waydroid, weston in (
            (False, "waydroid", "weston"),
            (True, "fixture-waydroid", "fixture-weston"),
        ):
            with self.subTest(
                    lazy_install=lazy_install, waydroid=waydroid, weston=weston), \
                    mock.patch.object(system, "doctor_checks", return_value=missing), \
                    mock.patch.object(cli.first_use, "install") as install, \
                    contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(
                        cli.runtime.LaunchError, "prerequisites"):
                    cli._preflight(
                        host_sdk=object(),
                        lazy_install=lazy_install,
                        waydroid=waydroid,
                        weston=weston,
                    )
            install.assert_not_called()

    def test_no_install_is_propagated_into_pane_reentry(self):
        host_sdk = SimpleNamespace(paths=object())
        seen = {}
        args = SimpleNamespace(
            size=None,
            install=False,
            waydroid="waydroid-fixture",
            weston="weston-fixture",
        )

        def execute(program, argv, environment):
            seen.update(program=program, argv=argv, environment=environment)
            raise ExecCalled

        with mock.patch.object(cli.sdk, "load", return_value=host_sdk), \
                mock.patch.object(cli, "_preflight", return_value=[]), \
                mock.patch.object(cli, "_kilix_launcher", return_value="/kilix"), \
                mock.patch.object(cli, "_launcher", return_value="/kilix-waydroid"), \
                mock.patch.object(cli.os, "execvpe", side_effect=execute):
            with self.assertRaises(ExecCalled):
                cli._run_pane(args)
        self.assertEqual(seen["argv"][-1], "--no-install")

    def test_doctor_json_is_machine_readable_and_returns_failure(self):
        checks = [system.Check("fixture", "error", "fixture failed")]
        args = SimpleNamespace(
            json_output=True, waydroid="waydroid", weston="weston")
        output = io.StringIO()
        with mock.patch.object(system, "doctor_checks", return_value=checks), \
                contextlib.redirect_stdout(output):
            self.assertEqual(cli._doctor(args), 1)
        self.assertIn('"ready": false', output.getvalue())


if __name__ == "__main__":
    unittest.main()
