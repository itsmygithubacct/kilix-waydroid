from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def test_catalog_entry_is_a_system_xpane_not_an_app_local_installer(self):
        manifest = json.loads(
            (ROOT / "packaging" / "kilix-content.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema_version"], 3)
        self.assertEqual(len(manifest["content"]), 1)
        entry = manifest["content"][0]
        self.assertEqual(entry["id"], "kilix-waydroid")
        self.assertEqual(entry["source"], {"type": "system"})
        self.assertEqual(entry["launch"]["mode"], "xpane")
        self.assertTrue(entry["lifecycle"]["single_instance"])
        self.assertEqual(entry["command"][0], "kilix-waydroid")
        self.assertIn("installs on first use", entry["description"])
        serialized = json.dumps(manifest).casefold()
        self.assertNotIn("curl", serialized)
        self.assertNotIn("sudo", serialized)
        self.assertNotIn("waydroid init", serialized)


if __name__ == "__main__":
    unittest.main()
