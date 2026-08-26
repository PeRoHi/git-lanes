from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["APPDATA"] = str(Path(self.tmp.name) / "appdata")
        Path(os.environ["APPDATA"]).mkdir(parents=True, exist_ok=True)
        from git_lanes.server import start_background, shutdown_async
        from git_lanes import HOST, PORT

        self.HOST, self.PORT = HOST, PORT
        self.shutdown_async = shutdown_async
        self.httpd = start_background()
        self._wait_health()

    def tearDown(self):
        self.shutdown_async()
        time.sleep(0.2)
        self.tmp.cleanup()

    def _wait_health(self):
        url = f"http://{self.HOST}:{self.PORT}/api/health"
        for _ in range(50):
            try:
                with urllib.request.urlopen(url, timeout=0.4) as r:
                    if r.status == 200:
                        return
            except OSError:
                time.sleep(0.05)
        self.fail("server did not start")

    def _json(self, path, data=None, method=None):
        url = f"http://{self.HOST}:{self.PORT}{path}"
        if data is None and method is None:
            req = urllib.request.Request(url)
        else:
            raw = json.dumps(data or {}).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=raw,
                method=method or "POST",
                headers={"Content-Type": "application/json"},
            )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                return resp.status, body
        except urllib.error.HTTPError as exc:
            body = json.loads(exc.read().decode("utf-8"))
            return exc.code, body

    def _git(self, cwd: Path, args: list[str]) -> None:
        subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            check=True,
            capture_output=True,
            text=True,
        )

    def test_health_open_graph_commit_and_invalid(self):
        status, body = self._json("/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])

        status, body = self._json("/api/graph")
        self.assertEqual(status, 200)
        self.assertTrue(body.get("need_open"))

        repo = Path(self.tmp.name) / "r"
        repo.mkdir()
        self._git(repo, ["init", "-b", "main"])
        self._git(repo, ["config", "user.email", "t@example.com"])
        self._git(repo, ["config", "user.name", "Test"])
        (repo / "a.txt").write_text("a", encoding="utf-8")
        self._git(repo, ["add", "a.txt"])
        env = os.environ.copy()
        env["GIT_AUTHOR_DATE"] = "2026-01-01T00:00:00"
        env["GIT_COMMITTER_DATE"] = "2026-01-01T00:00:00"
        subprocess.run(
            ["git", "commit", "-m", "a"],
            cwd=str(repo),
            check=True,
            capture_output=True,
            env=env,
        )

        status, body = self._json("/api/repos/open", {"path": str(repo)})
        self.assertEqual(status, 200, body)
        rid = body["repo"]["id"]

        status, body = self._json(f"/api/graph?repo_id={rid}")
        self.assertEqual(status, 200, body)
        self.assertFalse(body.get("need_open"))
        self.assertGreaterEqual(len(body["commits"]), 1)
        chash = body["commits"][0]["hash"]

        status, body = self._json(f"/api/commit?repo_id={rid}&hash={chash}")
        self.assertEqual(status, 200, body)
        self.assertEqual(body["subject"], "a")

        status, body = self._json(f"/api/refs?repo_id={rid}")
        self.assertEqual(status, 200, body)
        names = {r["name"] for r in body["refs"]}
        self.assertIn("main", names)
        tip = next(r for r in body["refs"] if r["name"] == "main")
        self.assertEqual(tip["kind"], "local")
        self.assertEqual(tip["hash"], chash)
        self.assertEqual(tip["subject"], "a")

        bogus = Path(self.tmp.name) / "nogit"
        bogus.mkdir()
        status, body = self._json("/api/repos/open", {"path": str(bogus)})
        self.assertEqual(status, 400)
        self.assertIn("git", body["error"].lower())

    def test_scan_and_workspace_open(self):
        ws = Path(self.tmp.name) / "ws"
        one = ws / "one"
        two = ws / "nest" / "two"
        for repo in (one, two):
            repo.mkdir(parents=True)
            self._git(repo, ["init", "-b", "main"])
            self._git(repo, ["config", "user.email", "t@example.com"])
            self._git(repo, ["config", "user.name", "Test"])
            (repo / "a.txt").write_text("a", encoding="utf-8")
            self._git(repo, ["add", "a.txt"])
            subprocess.run(
                ["git", "commit", "-m", "a"],
                cwd=str(repo),
                check=True,
                capture_output=True,
            )

        status, body = self._json("/api/repos/scan", {"roots": [str(ws)]})
        self.assertEqual(status, 200, body)
        names = {r["name"] for r in body["repos"]}
        self.assertEqual(names, {"one", "two"})
        self.assertEqual(len(body["added"]), 2)

        other = Path(self.tmp.name) / "other"
        three = other / "three"
        three.mkdir(parents=True)
        self._git(three, ["init", "-b", "main"])
        self._git(three, ["config", "user.email", "t@example.com"])
        self._git(three, ["config", "user.name", "Test"])
        (three / "a.txt").write_text("a", encoding="utf-8")
        self._git(three, ["add", "a.txt"])
        subprocess.run(
            ["git", "commit", "-m", "a"],
            cwd=str(three),
            check=True,
            capture_output=True,
        )
        status, body = self._json("/api/repos/open", {"path": str(other)})
        self.assertEqual(status, 200, body)
        self.assertTrue(body.get("workspace"))
        names = {r["name"] for r in body["repos"]}
        self.assertIn("three", names)
        self.assertIn("one", names)


if __name__ == "__main__":
    unittest.main()
