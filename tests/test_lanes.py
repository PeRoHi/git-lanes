from __future__ import annotations

import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from git_lanes.lanes import Commit, assign_lanes


def _c(h: str, parents: list[str], subject: str = "") -> Commit:
    return Commit(
        hash=h,
        parents=parents,
        author="t",
        author_at=1,
        subject=subject or h,
    )


class AssignLanesTest(unittest.TestCase):
    def test_linear_single_lane_parent1_only(self):
        commits = [_c("c", ["b"]), _c("b", ["a"]), _c("a", [])]
        assign_lanes(commits)
        self.assertEqual([x.lane for x in commits], [0, 0, 0])
        for x in commits:
            kinds = [e["kind"] for e in x.edges]
            self.assertNotIn("merge", kinds)

    def test_merge_no_ff_joins_second_parent(self):
        # newest: M (A, B), B (A), A
        commits = [
            _c("M", ["A", "B"], "merge"),
            _c("B", ["A"], "feat"),
            _c("A", [], "base"),
        ]
        assign_lanes(commits)
        merge = commits[0]
        self.assertEqual(merge.lane, 0)
        kinds = {e["kind"] for e in merge.edges}
        self.assertIn("merge", kinds)
        self.assertEqual(len(merge.parents), 2)
        feat = commits[1]
        self.assertEqual(feat.lane, 1)
        base = commits[2]
        self.assertEqual(base.lane, 0)
        self.assertIn(1, base.joins)

    def test_squash_has_no_merge_edge(self):
        # S onto A, feature B still reachable
        commits = [
            _c("S", ["A"], "squash"),
            _c("B", ["A"], "feat"),
            _c("A", [], "base"),
        ]
        assign_lanes(commits)
        squash = commits[0]
        self.assertEqual(len(squash.parents), 1)
        self.assertNotIn("merge", [e["kind"] for e in squash.edges])
        self.assertEqual(commits[1].lane, 1)


class FixtureGitTest(unittest.TestCase):
    def _git(self, cwd: Path, args: list[str], env: dict | None = None) -> None:
        e = os.environ.copy()
        if env:
            e.update(env)
        subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            check=True,
            capture_output=True,
            text=True,
            env=e,
        )

    def _init(self, cwd: Path) -> None:
        cwd.mkdir()
        self._git(cwd, ["init", "-b", "main"])
        self._git(cwd, ["config", "user.email", "t@example.com"])
        self._git(cwd, ["config", "user.name", "Test"])

    def _commit(self, cwd: Path, name: str, ts: int) -> str:
        (cwd / f"{name}.txt").write_text(name, encoding="utf-8")
        self._git(cwd, ["add", f"{name}.txt"])
        date = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ts))
        env = {
            "GIT_AUTHOR_DATE": date,
            "GIT_COMMITTER_DATE": date,
        }
        self._git(cwd, ["commit", "-m", name], env=env)
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(cwd),
            check=True,
            capture_output=True,
            text=True,
        )
        return out.stdout.strip()

    def test_real_linear_merge_squash_uncommitted_and_invalid(self):
        from git_lanes.gitio import (
            GitError,
            list_changed_files,
            list_refs,
            load_commit,
            load_graph,
            search_commits,
            toplevel,
        )

        import tempfile

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            linear = root / "linear"
            self._init(linear)
            self._commit(linear, "a", 1_700_000_000)
            self._commit(linear, "b", 1_700_000_100)
            self._commit(linear, "c", 1_700_000_200)
            g = load_graph(linear, 0, 300)
            self.assertEqual(g["lane_count"], 1)
            self.assertTrue(all(c["lane"] == 0 for c in g["commits"]))
            self.assertTrue(
                all(
                    "merge" not in [e["kind"] for e in c["edges"]]
                    for c in g["commits"]
                )
            )

            merged = root / "merged"
            self._init(merged)
            self._commit(merged, "base", 1_700_000_000)
            self._git(merged, ["checkout", "-b", "feat"])
            self._commit(merged, "feat", 1_700_000_100)
            self._git(merged, ["checkout", "main"])
            self._git(merged, ["merge", "--no-ff", "-m", "merge feat", "feat"])
            g = load_graph(merged, 0, 300)
            merge_c = g["commits"][0]
            self.assertEqual(len(merge_c["parents"]), 2)
            self.assertIn("merge", [e["kind"] for e in merge_c["edges"]])
            lanes = {c["lane"] for c in g["commits"]}
            self.assertGreaterEqual(len(lanes), 2)
            refs = list_refs(merged)
            names = {r["name"] for r in refs["refs"]}
            self.assertIn("main", names)
            self.assertIn("feat", names)
            feat = next(r for r in refs["refs"] if r["name"] == "feat")
            self.assertEqual(feat["kind"], "local")
            self.assertTrue(feat["hash"])
            self.assertIn("feat", feat["subject"])
            feat_only = load_graph(merged, 0, 300, rev="feat")
            feat_subjects = [c["subject"] for c in feat_only["commits"]]
            self.assertIn("feat", feat_subjects)
            self.assertTrue(
                all("merge feat" not in c["subject"] for c in feat_only["commits"])
            )
            hits = search_commits(merged, "merge feat")
            self.assertTrue(any("merge" in (h.get("subject") or "") for h in hits))
            merge_files = list_changed_files(merged, merge_c["hash"])
            self.assertTrue(merge_files)
            with self.assertRaises(GitError):
                load_graph(merged, 0, 10, rev="no-such-branch")

            squashed = root / "squashed"
            self._init(squashed)
            self._commit(squashed, "base", 1_700_000_000)
            self._git(squashed, ["checkout", "-b", "feat"])
            self._commit(squashed, "feat", 1_700_000_100)
            self._git(squashed, ["checkout", "main"])
            self._git(squashed, ["merge", "--squash", "feat"])
            date = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(1_700_000_200))
            self._git(
                squashed,
                ["commit", "-m", "squash feat"],
                {
                    "GIT_AUTHOR_DATE": date,
                    "GIT_COMMITTER_DATE": date,
                },
            )
            g = load_graph(squashed, 0, 300)
            squash_c = next(
                c for c in g["commits"] if "squash" in c["subject"]
            )
            self.assertEqual(len(squash_c["parents"]), 1)
            self.assertNotIn("merge", [e["kind"] for e in squash_c["edges"]])

            dirty = root / "dirty"
            self._init(dirty)
            self._commit(dirty, "a", 1_700_000_000)
            (dirty / "wip.txt").write_text("x", encoding="utf-8")
            g = load_graph(dirty, 0, 300)
            self.assertTrue(g["commits"][0]["uncommitted"])
            detail = load_commit(dirty, "UNCOMMITTED")
            self.assertIn("wip.txt", detail["body"])
            self.assertTrue(
                any(f.get("path") == "wip.txt" for f in detail.get("files") or [])
            )
            self._git(dirty, ["stash", "push", "-u", "-m", "park"])
            stashed = load_graph(dirty, 0, 300)
            self.assertTrue(any(c.get("stash") for c in stashed["commits"]))

            bogus = root / "notgit"
            bogus.mkdir()
            with self.assertRaises(GitError):
                toplevel(bogus)


if __name__ == "__main__":
    unittest.main()
