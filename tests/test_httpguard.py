from __future__ import annotations

import http.client
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from git_lanes import PORT
from git_lanes.gitio import GitError
from git_lanes.httpguard import (
    check_request,
    client_error_message,
    host_allowed,
    origin_allowed,
    resolve_web_file,
)


class HttpGuardUnitTest(unittest.TestCase):
    def test_host_requires_loopback_port(self):
        self.assertTrue(host_allowed("127.0.0.1:17920", expected_port=PORT))
        self.assertTrue(host_allowed("LOCALHOST:17920", expected_port=PORT))
        self.assertTrue(host_allowed("[::1]:17920", expected_port=PORT))
        self.assertFalse(host_allowed("127.0.0.1", expected_port=PORT))
        self.assertFalse(host_allowed("localhost", expected_port=PORT))
        self.assertFalse(host_allowed("0.0.0.0:17920", expected_port=PORT))
        self.assertFalse(host_allowed("evil.example:17920", expected_port=PORT))
        self.assertFalse(host_allowed("127.0.0.1:80", expected_port=PORT))

    def test_origin_is_allowlist_not_host_equality(self):
        self.assertTrue(origin_allowed("http://127.0.0.1:17920", expected_port=PORT))
        self.assertTrue(origin_allowed("http://localhost:17920", expected_port=PORT))
        self.assertTrue(origin_allowed("http://[::1]:17920", expected_port=PORT))
        self.assertFalse(origin_allowed("https://127.0.0.1:17920", expected_port=PORT))
        self.assertFalse(origin_allowed("http://127.0.0.1", expected_port=PORT))
        self.assertFalse(origin_allowed("http://evil.example", expected_port=PORT))
        self.assertFalse(origin_allowed("null", expected_port=PORT))
        # Matching a spoofed Host is not enough; Origin must be loopback.
        headers = {"Host": "127.0.0.1:17920", "Origin": "http://127.0.0.1:17920"}
        ok, status, _ = check_request(headers, method="POST", expected_port=PORT)
        self.assertTrue(ok)
        self.assertEqual(status, 200)
        headers = {"Host": "127.0.0.1:17920", "Origin": "http://evil.example"}
        ok, status, msg = check_request(headers, method="POST", expected_port=PORT)
        self.assertFalse(ok)
        self.assertEqual(status, 403)
        self.assertEqual(msg, "invalid origin")

    def test_client_errors_drop_paths_and_stderr(self):
        self.assertEqual(client_error_message(GitError("unknown repo")), "unknown repo")
        self.assertEqual(
            client_error_message(GitError("fatal: not a git repository: /home/u/secret")),
            "request failed",
        )
        self.assertEqual(client_error_message(RuntimeError("boom /tmp/x")), "internal")
        self.assertEqual(
            client_error_message(
                GitError("GitHub CLI (gh) not found. Install from https://cli.github.com/")
            ),
            "GitHub CLI (gh) not found. Install from https://cli.github.com/",
        )

    def test_static_jail_rejects_dotdot_and_nested_encoding(self):
        with tempfile.TemporaryDirectory() as raw:
            web = Path(raw) / "web"
            web.mkdir()
            (web / "index.html").write_text("ok", encoding="utf-8")
            outside = Path(raw) / "secret.txt"
            outside.write_text("nope", encoding="utf-8")
            self.assertEqual(
                resolve_web_file(web, "/index.html").read_text(encoding="utf-8"),
                "ok",
            )
            self.assertIsNone(resolve_web_file(web, "/../secret.txt"))
            self.assertIsNone(resolve_web_file(web, "/%2e%2e/secret.txt"))
            self.assertIsNone(resolve_web_file(web, "/%252e%252e/secret.txt"))
            self.assertIsNone(resolve_web_file(web, "/..%2fsecret.txt"))

    def test_static_jail_refuses_symlinks(self):
        with tempfile.TemporaryDirectory() as raw:
            web = Path(raw) / "web"
            web.mkdir()
            (web / "index.html").write_text("ok", encoding="utf-8")
            outside = Path(raw) / "secret.txt"
            outside.write_text("nope", encoding="utf-8")
            link = web / "leak.txt"
            try:
                link.symlink_to(outside)
            except OSError as exc:
                self.skipTest("symlink not available: " + type(exc).__name__)
            self.assertIsNone(resolve_web_file(web, "/leak.txt"))
            nested = web / "sub"
            nested.mkdir()
            nested_link = nested / "up"
            try:
                nested_link.symlink_to(Path(raw))
            except OSError as exc:
                self.skipTest("symlink not available: " + type(exc).__name__)
            self.assertIsNone(resolve_web_file(web, "/sub/up/secret.txt"))


class HttpGuardApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["APPDATA"] = str(Path(self.tmp.name) / "appdata")
        Path(os.environ["APPDATA"]).mkdir(parents=True, exist_ok=True)
        from git_lanes.server import start_background, shutdown_async
        from git_lanes import HOST

        self.HOST = HOST
        self.shutdown_async = shutdown_async
        start_background()
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                conn = http.client.HTTPConnection(self.HOST, PORT, timeout=0.4)
                conn.request("GET", "/api/health", headers={"Host": f"{self.HOST}:{PORT}"})
                resp = conn.getresponse()
                resp.read()
                conn.close()
                if resp.status == 200:
                    return
            except OSError:
                time.sleep(0.05)
        self.fail("server did not start")

    def tearDown(self):
        self.shutdown_async()
        from git_lanes.server import wait_stopped

        wait_stopped()
        self.tmp.cleanup()

    def _raw(self, method, path, headers, body=None):
        conn = http.client.HTTPConnection(self.HOST, PORT, timeout=5)
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, data

    def test_rejects_host_without_port_and_foreign_origin(self):
        status, body = self._raw(
            "GET",
            "/api/health",
            {"Host": "127.0.0.1"},
        )
        self.assertEqual(status, 403)
        self.assertIn(b"invalid host", body)

        status, body = self._raw(
            "POST",
            "/api/shutdown",
            {
                "Host": f"{self.HOST}:{PORT}",
                "Origin": "http://evil.example",
                "Content-Type": "application/json",
                "Content-Length": "2",
            },
            b"{}",
        )
        self.assertEqual(status, 403)
        self.assertIn(b"invalid origin", body)

        status, body = self._raw(
            "GET",
            "/api/health",
            {"Host": f"{self.HOST}:{PORT}"},
        )
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body.decode("utf-8"))["ok"])

    def test_static_traversal_is_forbidden(self):
        status, body = self._raw(
            "GET",
            "/../src/git_lanes/server.py",
            {"Host": f"{self.HOST}:{PORT}"},
        )
        self.assertIn(status, (403, 404))
        self.assertNotIn(b"from git_lanes", body)


class GitStderrTest(unittest.TestCase):
    def test_run_git_hides_stderr(self):
        from git_lanes.gitio import run_git

        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaises(GitError) as cm:
                run_git(Path(raw), ["rev-parse", "definitely-not-a-rev"])
        self.assertEqual(str(cm.exception), "git failed")
        self.assertNotIn("fatal", str(cm.exception).lower())


if __name__ == "__main__":
    unittest.main()
