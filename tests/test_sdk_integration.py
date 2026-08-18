from __future__ import annotations

import os
from pathlib import Path
import stat
import tempfile
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
                host_sdk = sdk.load("1.16")
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


if __name__ == "__main__":
    unittest.main()
