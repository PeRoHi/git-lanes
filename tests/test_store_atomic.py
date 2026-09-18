from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class AtomicWriteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["APPDATA"] = str(Path(self.tmp.name) / "appdata")
        Path(os.environ["APPDATA"]).mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_save_config_roundtrip(self):
        from git_lanes.store import load_config, save_config

        save_config({"repos": [], "scan_roots": ["/tmp/example"]})
        cfg = load_config()
        self.assertEqual(cfg["scan_roots"], ["/tmp/example"])
        path = Path(os.environ["APPDATA"]) / "git-lanes" / "config.json"
        self.assertTrue(path.is_file())
        self.assertGreater(path.stat().st_size, 0)
        leftover = path.with_name(path.name + ".tmp")
        self.assertFalse(leftover.exists())

    def test_refuse_empty_write(self):
        from git_lanes import store

        dest = Path(self.tmp.name) / "keep.json"
        dest.write_text('{"keep": true}\n', encoding="utf-8")
        orig = store.json.dumps
        store.json.dumps = lambda *args, **kwargs: ""
        try:
            with self.assertRaises(OSError):
                store._write_json(dest, {"repos": []})
        finally:
            store.json.dumps = orig
        self.assertEqual(dest.read_text(encoding="utf-8"), '{"keep": true}\n')

    def test_refuse_dest_symlink(self):
        from git_lanes.store import _write_json

        target = Path(self.tmp.name) / "real.json"
        target.write_text("{}\n", encoding="utf-8")
        dest = Path(self.tmp.name) / "link.json"
        try:
            dest.symlink_to(target)
        except OSError as exc:
            self.skipTest("symlink not available: " + type(exc).__name__)
        with self.assertRaises(OSError):
            _write_json(dest, {"repos": []})
        self.assertEqual(target.read_text(encoding="utf-8"), "{}\n")

    def test_leftover_regular_tmp_is_replaced(self):
        from git_lanes.store import _write_json

        dest = Path(self.tmp.name) / "cfg.json"
        dest.write_text('{"old": true}\n', encoding="utf-8")
        leftover = dest.with_name(dest.name + ".tmp")
        leftover.write_text("stale", encoding="utf-8")
        _write_json(dest, {"repos": []})
        self.assertTrue(dest.is_file())
        self.assertFalse(leftover.exists())

    def test_symlink_tmp_is_refused_without_unlink(self):
        from git_lanes.store import _write_json

        victim = Path(self.tmp.name) / "victim.json"
        victim.write_text("keep-me\n", encoding="utf-8")
        dest = Path(self.tmp.name) / "cfg.json"
        tmp = dest.with_name(dest.name + ".tmp")
        try:
            tmp.symlink_to(victim)
        except OSError as exc:
            self.skipTest("symlink not available: " + type(exc).__name__)
        with self.assertRaises(OSError):
            _write_json(dest, {"repos": []})
        self.assertTrue(tmp.is_symlink())
        self.assertEqual(victim.read_text(encoding="utf-8"), "keep-me\n")

    def test_broken_config_is_load_failed(self):
        from git_lanes.store import StoreError, config_unreadable, load_config, save_config

        path = Path(os.environ["APPDATA"]) / "git-lanes" / "config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{broken", encoding="utf-8")
        cfg = load_config()
        self.assertEqual(cfg["repos"], [])
        self.assertTrue(config_unreadable())
        with self.assertRaises(StoreError):
            save_config({"repos": [], "scan_roots": []})
        self.assertEqual(path.read_text(encoding="utf-8"), "{broken")

    def test_empty_config_is_load_failed(self):
        from git_lanes.store import StoreError, config_unreadable, load_config, save_config

        path = Path(os.environ["APPDATA"]) / "git-lanes" / "config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
        load_config()
        self.assertTrue(config_unreadable())
        with self.assertRaises(StoreError):
            save_config({"repos": [], "scan_roots": []})
        self.assertEqual(path.stat().st_size, 0)

    def test_symlink_config_is_load_failed(self):
        from git_lanes.store import StoreError, config_unreadable, load_config, save_config

        app = Path(os.environ["APPDATA"]) / "git-lanes"
        app.mkdir(parents=True, exist_ok=True)
        target = Path(self.tmp.name) / "real-config.json"
        target.write_text('{"repos": [], "scan_roots": []}\n', encoding="utf-8")
        dest = app / "config.json"
        try:
            dest.symlink_to(target)
        except OSError as exc:
            self.skipTest("symlink not available: " + type(exc).__name__)
        load_config()
        self.assertTrue(config_unreadable())
        with self.assertRaises(StoreError):
            save_config({"repos": [{"id": "x", "name": "x", "path": "/x"}], "scan_roots": []})
        self.assertEqual(target.read_text(encoding="utf-8"), '{"repos": [], "scan_roots": []}\n')


if __name__ == "__main__":
    unittest.main()
