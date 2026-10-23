from __future__ import annotations

import os
from pathlib import Path
import stat
import tempfile
import time
import textwrap
import unittest
from unittest import mock

from kilix_waydroid import runtime, sdk


KILIX_HOME = os.environ.get("KILIX_WAYDROID_TEST_KILIX_HOME", "")


@unittest.skipUnless(KILIX_HOME, "set KILIX_WAYDROID_TEST_KILIX_HOME for SDK integration")
class SDKIntegrationTests(unittest.TestCase):
    def test_app_uses_the_real_sdk_owner_from_start_through_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            weston = root / "fixture-weston"
            weston.write_text(
                textwrap.dedent("""\
                    #!/usr/bin/env python3
                    import os
                    import socket
                    import sys
                    import time

                    name = next(
                        item.split("=", 1)[1]
                        for item in sys.argv[1:]
                        if item.startswith("--socket=")
                    )
                    endpoint = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    endpoint.bind(os.path.join(os.environ["XDG_RUNTIME_DIR"], name))
                    endpoint.listen(1)
                    time.sleep(0.3)
                    endpoint.close()
                """),
                encoding="utf-8",
            )
            waydroid = root / "fixture-waydroid"
            waydroid.write_text(
                textwrap.dedent("""\
                    #!/usr/bin/env python3
                    import sys
                    import time

                    if sys.argv[-1:] == ["status"]:
                        print("Session:\tSTOPPED")
                    elif sys.argv[-1:] == ["show-full-ui"]:
                        time.sleep(30)
                """),
                encoding="utf-8",
            )
            for executable in (weston, waydroid):
                executable.chmod(executable.stat().st_mode | stat.S_IXUSR)

            environment = {
                "DISPLAY": ":77",
                "KILIX_HOME": KILIX_HOME,
                "KILIX_SESSION_HOME": str(root / "session"),
            }
            with mock.patch.dict(os.environ, environment, clear=True):
                host_sdk = sdk.load("1.19")
                result = runtime.run_window(
                    host_sdk,
                    width=960,
                    height=600,
                    waydroid=str(waydroid),
                    weston=str(weston),
                )

            self.assertEqual(result, 0)
            stream_root = root / "session" / "stream"
            leftovers = [
                item for item in stream_root.glob("waydroid-*")
                if item.is_dir()
            ] if stream_root.exists() else []
            self.assertEqual(leftovers, [])


    def test_owned_descendants_and_startup_failure_are_cleaned(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            compositor = root / "weston-fixture"
            compositor.write_text(
                "#!/usr/bin/python3\n"
                "import os, socket, sys, time\n"
                "s = socket.socket(socket.AF_UNIX)\n"
                "name = next(x.split('=', 1)[1] for x in sys.argv if x.startswith('--socket='))\n"
                "s.bind(os.path.join(os.environ['XDG_RUNTIME_DIR'], name))\n"
                "s.listen(4)\n"
                "time.sleep(30)\n", encoding="utf-8")
            compositor.chmod(0o700)
            pidfile = root / "descendant.pid"
            client_script = root / "client.py"
            client_script.write_text(
                "import os, pathlib, subprocess, sys, time\n"
                "child = subprocess.Popen(['/usr/bin/python3', '-c', 'import time; time.sleep(60)'], start_new_session=True)\n"
                "pathlib.Path(sys.argv[1]).write_text(str(child.pid))\n"
                "time.sleep(60)\n", encoding="utf-8")
            environment = {"DISPLAY": ":77", "KILIX_HOME": KILIX_HOME,
                           "KILIX_SESSION_HOME": str(root / "session")}
            with mock.patch.dict(os.environ, environment, clear=True):
                host_sdk = sdk.load("1.19")
                with host_sdk.wayland.NestedWaylandSession("fixture-descendants", exclusive="waydroid-integration-test") as nested:
                    nested.start_x11(960, 600, executable=str(compositor))
                    client = nested.launch_client("fixture-client", ["/usr/bin/python3", str(client_script), str(pidfile)])
                    deadline = time.monotonic() + 5
                    while not pidfile.exists() and time.monotonic() < deadline:
                        time.sleep(0.02)
                    self.assertTrue(pidfile.exists(), "fixture child did not start")
                    descendant = int(pidfile.read_text())
                    self.assertIsNone(client.poll())
                self.assertIsNotNone(client.poll())
                deadline = time.monotonic() + 3
                while Path(f"/proc/{descendant}").exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertFalse(Path(f"/proc/{descendant}").exists())
                with self.assertRaisesRegex(RuntimeError, "before readiness"):
                    with host_sdk.wayland.NestedWaylandSession("fixture-failure", exclusive="waydroid-integration-test") as failed:
                        failed.start_x11(960, 600, executable="/usr/bin/false")
                self.assertFalse(Path(failed.supervisor.runtime_dir).exists())
                self.assertFalse(Path(nested.supervisor.runtime_dir).exists())


if __name__ == "__main__":
    unittest.main()
