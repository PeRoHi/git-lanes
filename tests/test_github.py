from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class GithubNameTest(unittest.TestCase):
    def test_normalize_https_ssh_and_nwo(self):
        from git_lanes.github import normalize_github_name

        want = "perohi/git-lanes"
        self.assertEqual(
            normalize_github_name("https://github.com/PeRoHi/git-lanes.git"),
            want,
        )
        self.assertEqual(
            normalize_github_name("git@github.com:PeRoHi/git-lanes.git"),
            want,
        )
        self.assertEqual(
            normalize_github_name("ssh://git@github.com/PeRoHi/git-lanes.git"),
            want,
        )
        self.assertEqual(normalize_github_name("PeRoHi/git-lanes"), want)
        self.assertEqual(normalize_github_name(""), "")

    def test_parse_login_banner(self):
        from git_lanes.github import DEVICE_URL, parse_login_banner

        code, uri = parse_login_banner(
            "\n! First copy your one-time code: 775E-0C89\n"
            "Open this URL to continue in your web browser: https://github.com/login/device\n"
        )
        self.assertEqual(code, "775E-0C89")
        self.assertEqual(uri, DEVICE_URL)
        self.assertEqual(parse_login_banner(""), ("", ""))

    def test_status_shape(self):
        from git_lanes.github import status

        st = status()
        self.assertIn("logged_in", st)
        self.assertIn("gh_ok", st)
        self.assertIn("remembered", st)
        self.assertIn("remembered_user", st)
        if st.get("logged_in"):
            self.assertTrue(st["user"])
            self.assertTrue(st["remembered"])
            self.assertEqual(st["remembered_user"], st["user"])

    def test_clone_parent_prefers_app_parent(self):
        from git_lanes.github import APP_ROOT, clone_parent

        parent = clone_parent()
        self.assertTrue(parent.is_dir())
        self.assertEqual(parent, APP_ROOT.parent)

    def test_invalid_clone_name(self):
        from git_lanes.gitio import GitError
        from git_lanes.github import clone_named

        with self.assertRaises(GitError):
            clone_named("../etc/passwd")
        with self.assertRaises(GitError):
            clone_named("not-a-nwo")


class GithubStatusApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["APPDATA"] = str(Path(self.tmp.name) / "appdata")
        Path(os.environ["APPDATA"]).mkdir(parents=True, exist_ok=True)
        from git_lanes.server import start_background, shutdown_async
        from git_lanes import HOST, PORT
        import json
        import time
        import urllib.request

        self.json = json
        self.time = time
        self.urllib = urllib.request
        self.HOST, self.PORT = HOST, PORT
        self.shutdown_async = shutdown_async
        start_background()
        url = f"http://{HOST}:{PORT}/api/health"
        for _ in range(50):
            try:
                with urllib.request.urlopen(url, timeout=0.4) as r:
                    if r.status == 200:
                        return
            except OSError:
                time.sleep(0.05)
        self.fail("server did not start")

    def tearDown(self):
        self.shutdown_async()
        self.time.sleep(0.2)
        self.tmp.cleanup()

    def test_github_status_endpoint(self):
        url = f"http://{self.HOST}:{self.PORT}/api/github/status"
        with self.urllib.urlopen(url, timeout=10) as resp:
            body = self.json.loads(resp.read().decode("utf-8"))
        self.assertIn("logged_in", body)
        self.assertIn("remembered", body)
        self.assertIn("remembered_user", body)
        if body["logged_in"]:
            self.assertTrue(body["user"])
            self.assertTrue(body["remembered"])
            self.assertEqual(body["remembered_user"], body["user"])


if __name__ == "__main__":
    unittest.main()
