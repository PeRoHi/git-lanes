from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class DiscoverTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["APPDATA"] = str(Path(self.tmp.name) / "appdata")
        Path(os.environ["APPDATA"]).mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.tmp.cleanup()

    def _git(self, cwd: Path, args: list[str]) -> None:
        subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            check=True,
            capture_output=True,
            text=True,
        )

    def _init_repo(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        self._git(path, ["init", "-b", "main"])
        self._git(path, ["config", "user.email", "t@example.com"])
        self._git(path, ["config", "user.name", "Test"])
        (path / "a.txt").write_text("a", encoding="utf-8")
        self._git(path, ["add", "a.txt"])
        env = os.environ.copy()
        env["GIT_AUTHOR_DATE"] = "2026-01-01T00:00:00"
        env["GIT_COMMITTER_DATE"] = "2026-01-01T00:00:00"
        subprocess.run(
            ["git", "commit", "-m", "a"],
            cwd=str(path),
            check=True,
            capture_output=True,
            env=env,
        )

    def test_candidate_roots_skips_missing_and_dedupes(self):
        from git_lanes.discover import candidate_roots

        home = Path(self.tmp.name) / "home"
        program = home / "Desktop" / "program"
        program.mkdir(parents=True)
        app = program / "git-lanes"
        app.mkdir()
        roots = candidate_roots(home=home, app_root=app, extra=[str(program)])
        self.assertIn(program.resolve(), roots)
        self.assertEqual(roots.count(program.resolve()), 1)
        self.assertNotIn(home / "Documents" / "HDLSim", roots)

    def test_walk_repos_depth_and_skips_node_modules(self):
        from git_lanes.discover import walk_repos

        root = Path(self.tmp.name) / "ws"
        keep = root / "keep"
        nested = root / "group" / "inner"
        skip = root / "skip" / "node_modules" / "fake"
        for path in (keep, nested, skip):
            path.mkdir(parents=True)
            (path / ".git").mkdir()
        found = {p.name for p in walk_repos([root])}
        self.assertIn("keep", found)
        self.assertIn("inner", found)
        self.assertNotIn("fake", found)

    def test_walk_repos_skips_directory_symlinks(self):
        from git_lanes.discover import walk_repos

        root = Path(self.tmp.name) / "ws"
        root.mkdir()
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        (outside / ".git").mkdir()
        link = root / "linked"
        try:
            link.symlink_to(outside)
        except OSError as exc:
            self.skipTest("symlink not available: " + type(exc).__name__)
        found = {p.name for p in walk_repos([root])}
        self.assertNotIn("linked", found)
        self.assertNotIn("outside", found)

    def test_scan_merges_without_stealing_last_opened(self):
        from git_lanes.discover import scan_and_merge
        from git_lanes.store import load_state, pick_last_or_none, upsert_repo

        ws = Path(self.tmp.name) / "ws"
        first = ws / "life"
        second = ws / "git-lanes"
        self._init_repo(first)
        self._init_repo(second)
        upsert_repo(first, select=True)
        self.assertEqual(load_state()["last_opened"], "life")
        result = scan_and_merge([ws])
        names = {r["name"] for r in result["repos"]}
        self.assertEqual(names, {"life", "git-lanes"})
        self.assertEqual(load_state()["last_opened"], "life")
        self.assertEqual(pick_last_or_none()["id"], "life")
        added_names = {r["name"] for r in result["added"]}
        self.assertEqual(added_names, {"git-lanes"})

    def test_pick_last_skips_missing_path(self):
        from git_lanes.store import pick_last_or_none, save_config, save_state

        alive = Path(self.tmp.name) / "alive"
        alive.mkdir()
        save_config(
            {
                "repos": [
                    {"id": "gone", "name": "gone", "path": str(Path(self.tmp.name) / "gone")},
                    {"id": "alive", "name": "alive", "path": str(alive)},
                ],
                "scan_roots": [],
            }
        )
        save_state({"last_opened": "gone"})
        rec = pick_last_or_none()
        self.assertIsNotNone(rec)
        self.assertEqual(rec["id"], "alive")

    def test_github_user_survives_last_opened_save(self):
        from git_lanes.store import load_state, save_state, set_github_user

        set_github_user("PeRoHi")
        self.assertEqual(load_state()["github_user"], "PeRoHi")
        save_state({"last_opened": "alive"})
        st = load_state()
        self.assertEqual(st["github_user"], "PeRoHi")
        self.assertEqual(st["last_opened"], "alive")
        set_github_user("")
        self.assertEqual(load_state()["github_user"], "")

    def test_open_workspace_adds_nested_repos(self):
        from git_lanes.discover import open_user_path

        ws = Path(self.tmp.name) / "ws"
        self._init_repo(ws / "alpha")
        self._init_repo(ws / "group" / "beta")
        data = open_user_path(str(ws))
        self.assertTrue(data["workspace"])
        names = {r["name"] for r in data["repos"]}
        self.assertEqual(names, {"alpha", "beta"})
        self.assertIn(data["repo"]["name"], names)


if __name__ == "__main__":
    unittest.main()
