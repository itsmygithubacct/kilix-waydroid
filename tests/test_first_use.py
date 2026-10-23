from __future__ import annotations

import contextlib
import io
from types import SimpleNamespace
import unittest
from unittest import mock

from kilix_waydroid import first_use, runtime, system


class FirstUseTests(unittest.TestCase):
    def test_only_installer_managed_failures_request_setup(self):
        for check_id, expected in (
            ("waydroid-command", True),
            ("weston-command", True),
            ("initialized", True),
            ("binder-kernel", False),
            ("session-bus", False),
            ("container-service", True),
        ):
            with self.subTest(check_id=check_id):
                self.assertEqual(first_use.needed([
                    system.Check(check_id, "error", "fixture")
                ]), expected)
        self.assertFalse(first_use.needed([
            system.Check("waydroid-command", "warning", "fixture", required=False)
        ]))
        self.assertTrue(first_use.needed([
            system.Check("waydroid-command", "error", "fixture"),
            system.Check("container-service", "error", "fixture"),
        ]))
        self.assertFalse(first_use.needed([
            system.Check("waydroid-command", "error", "fixture"),
            system.Check("binder-kernel", "error", "fixture"),
        ]))

    def test_install_uses_exact_shared_helper_without_arguments(self):
        privilege = SimpleNamespace(run_helper=mock.Mock(return_value=0))
        with contextlib.redirect_stderr(io.StringIO()):
            first_use.install(SimpleNamespace(privilege=privilege))
        privilege.run_helper.assert_called_once_with(
            first_use.SYSTEM_INSTALLER,
            title="Install Android + Weston (about 1 GB)",
        )

    def test_cancelled_or_failed_setup_is_retryable_failure(self):
        privilege = SimpleNamespace(run_helper=mock.Mock(return_value=1))
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaisesRegex(
                runtime.LaunchError, "launch again to retry"):
            first_use.install(SimpleNamespace(privilege=privilege))


if __name__ == "__main__":
    unittest.main()
