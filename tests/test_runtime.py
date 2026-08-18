from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest import mock

from kilix_waydroid import runtime, system


class FakeNested:
    next_exit = SimpleNamespace(source="compositor", returncode=0)
    instance = None

    def __init__(self, session, exclusive=None):
        self.session = session
        self.exclusive = exclusive
        self.started = None
        self.launched = None
        self.closed = False
        FakeNested.instance = self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.closed = True

    def start_x11(self, width, height, executable="weston"):
        self.started = (width, height, executable)

    def launch_client(self, name, command, **kwargs):
        self.launched = (name, command, kwargs)
        return object()

    def wait(self, _client):
        return self.next_exit

    def compositor_diagnostic(self):
        return "fixture diagnostic"


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        FakeNested.next_exit = SimpleNamespace(source="compositor", returncode=0)
        self.host_sdk = SimpleNamespace(
            wayland=SimpleNamespace(NestedWaylandSession=FakeNested))

    def test_window_owns_one_nested_session_and_waydroid_process(self):
        stopped = system.WaydroidStatus(False, "STOPPED")
        with mock.patch.object(system, "waydroid_status", return_value=stopped):
            result = runtime.run_window(
                self.host_sdk,
                width=960,
                height=600,
                waydroid="/usr/bin/waydroid",
                weston="/usr/bin/weston",
            )
        self.assertEqual(result, 0)
        nested = FakeNested.instance
        self.assertEqual(nested.exclusive, "waydroid")
        self.assertEqual(nested.started, (960, 600, "/usr/bin/weston"))
        self.assertEqual(
            nested.launched[1],
            ["/usr/bin/waydroid", "show-full-ui"],
        )
        self.assertTrue(nested.closed)

    def test_existing_waydroid_session_is_never_rebound_or_stopped(self):
        running = system.WaydroidStatus(
            True, "RUNNING", wayland_display="wayland-existing")
        with mock.patch.object(system, "waydroid_status", return_value=running):
            with self.assertRaisesRegex(runtime.LaunchError, "already running"):
                runtime.run_window(
                    self.host_sdk,
                    width=960,
                    height=600,
                    waydroid="waydroid",
                    weston="weston",
                )
        self.assertIsNone(FakeNested.instance.started)
        self.assertTrue(FakeNested.instance.closed)

    def test_nonzero_compositor_exit_includes_its_diagnostic(self):
        FakeNested.next_exit = SimpleNamespace(source="compositor", returncode=4)
        stopped = system.WaydroidStatus(False, "STOPPED")
        with mock.patch.object(system, "waydroid_status", return_value=stopped):
            with self.assertRaisesRegex(
                runtime.LaunchError, "rc=4: fixture diagnostic"):
                runtime.run_window(
                    self.host_sdk,
                    width=960,
                    height=600,
                    waydroid="waydroid",
                    weston="weston",
                )

    def test_zero_client_exit_is_not_silently_called_success(self):
        FakeNested.next_exit = SimpleNamespace(source="client", returncode=0)
        stopped = system.WaydroidStatus(False, "STOPPED")
        with mock.patch.object(system, "waydroid_status", return_value=stopped):
            with self.assertRaisesRegex(runtime.LaunchError, "ended before"):
                runtime.run_window(
                    self.host_sdk,
                    width=960,
                    height=600,
                    waydroid="waydroid",
                    weston="weston",
                )


if __name__ == "__main__":
    unittest.main()
