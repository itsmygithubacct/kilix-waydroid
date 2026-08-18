from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from kilix_waydroid import system


class SystemTests(unittest.TestCase):
    def test_status_parser_keeps_session_container_and_display(self):
        status = system.parse_status(
            "Session:\tRUNNING\nContainer:\tFROZEN\n"
            "Wayland display:\twayland-7\n"
        )
        self.assertTrue(status.running)
        self.assertEqual(status.session, "RUNNING")
        self.assertEqual(status.container, "FROZEN")
        self.assertEqual(status.wayland_display, "wayland-7")

    def test_status_runner_failures_are_data_not_tracebacks(self):
        def unavailable(*_args, **_kwargs):
            raise FileNotFoundError("fixture missing")

        status = system.waydroid_status("missing", runner=unavailable)
        self.assertFalse(status.running)
        self.assertEqual(status.returncode, 127)
        self.assertIn("fixture missing", status.error)

    def test_doctor_reports_a_ready_initialized_host(self):
        def run(argv, **_kwargs):
            if argv[0] == "systemctl":
                return subprocess.CompletedProcess(argv, 0, stdout="active\n")
            return subprocess.CompletedProcess(argv, 0, stdout="fixture 1.0\n")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "waydroid"
            root.mkdir()
            (root / "rootfs").mkdir()
            (root / "waydroid.cfg").write_text(
                "[waydroid]\nbinder=binder\nvndbinder=vndbinder\n"
                "hwbinder=hwbinder\n",
                encoding="utf-8",
            )
            fake_sdk = SimpleNamespace(core=SimpleNamespace(SDK_VERSION="1.16.0"))
            with mock.patch.object(system.sdk, "load", return_value=fake_sdk), \
                    mock.patch.object(
                        system, "_kernel_config",
                        return_value={"CONFIG_ANDROID_BINDER_IPC": "m"}), \
                    mock.patch.object(system, "_binder_paths", return_value=()), \
                    mock.patch.dict(
                        os.environ,
                        {"DBUS_SESSION_BUS_ADDRESS": "unix:path=/fixture", "DISPLAY": ":7"},
                        clear=True,
                    ):
                checks = system.doctor_checks(
                    waydroid="/bin/true",
                    weston="/bin/true",
                    workdir=str(root),
                    require_display=True,
                    runner=run,
                )
        self.assertEqual(system.required_failures(checks), [])
        self.assertTrue(all(check.status == "ok" for check in checks))

    def test_doctor_does_not_treat_missing_binder_nodes_as_an_app_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            fake_sdk = SimpleNamespace(core=SimpleNamespace(SDK_VERSION="1.16.0"))

            def run(argv, **_kwargs):
                if argv[0] == "systemctl":
                    return subprocess.CompletedProcess(argv, 0, stdout="active\n")
                return subprocess.CompletedProcess(argv, 0, stdout="fixture\n")

            with mock.patch.object(system.sdk, "load", return_value=fake_sdk), \
                    mock.patch.object(
                        system, "_kernel_config",
                        return_value={"CONFIG_ANDROID_BINDER_IPC": "y"}), \
                    mock.patch.object(
                        system, "_binder_paths",
                        return_value=("binder", "vndbinder")), \
                    mock.patch.dict(
                        os.environ,
                        {"DBUS_SESSION_BUS_ADDRESS": "unix:path=/fixture"},
                        clear=True,
                    ):
                checks = system.doctor_checks(
                    waydroid="/bin/true",
                    weston="/bin/true",
                    workdir=temporary,
                    runner=run,
                )
        binder = next(check for check in checks if check.check_id == "binder-devices")
        self.assertEqual(binder.status, "warning")
        self.assertFalse(binder.required)
        initialized = next(check for check in checks if check.check_id == "initialized")
        self.assertEqual(initialized.status, "error")


if __name__ == "__main__":
    unittest.main()
