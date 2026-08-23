from __future__ import annotations

import os
import subprocess
from pathlib import Path

from git_lanes.lanes import Commit, assign_lanes

CREATE_NO_WINDOW = 0x08000000
UNCOMMITTED = "UNCOMMITTED"
RECORD_SEP = "\x1e"
FIELD_SEP = "\x1f"


class GitError(Exception):
    pass


def _creationflags() -> int:
    return CREATE_NO_WINDOW if os.name == "nt" else 0


def run_git(cwd: Path, args: list[str], timeout: int = 30) -> str:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            timeout=timeout,
            creationflags=_creationflags(),
        )
    except FileNotFoundError as exc:
        raise GitError("git executable not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitError("git timed out") from exc
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "git failed").strip()
        raise GitError(err)
    return proc.stdout


def is_work_tree(path: Path) -> bool:
    try:
        out = run_git(path, ["rev-parse", "--is-inside-work-tree"])
    except GitError:
        return False
    return out.strip() == "true"


def toplevel(path: Path) -> Path:
    out = run_git(path, ["rev-parse", "--show-toplevel"]).strip()
    return Path(out)


def _parse_log(raw: str) -> list[Commit]:
    commits: list[Commit] = []
    if not raw:
        return commits
    for rec in raw.split(RECORD_SEP):
        if not rec.strip("\n"):
            continue
        parts = rec.split(FIELD_SEP)
        if len(parts) < 6:
            continue
        chash, parents_s, author, at_s, subject, body = (
            parts[0],
            parts[1],
            parts[2],
            parts[3],
            parts[4],
            parts[5],
        )
        chash = chash.strip()
        if not chash:
            continue
        try:
            author_at = int(at_s.strip() or "0")
        except ValueError:
            author_at = 0
        parents = [p for p in parents_s.split() if p]
        commits.append(
            Commit(
                hash=chash,
                parents=parents,
                author=author,
                author_at=author_at,
                subject=subject,
                body=body.strip("\n"),
            )
        )
    return commits


def _load_refs(path: Path) -> tuple[str, str, dict[str, list[str]]]:
    """Return (head_hash, head_name, hash -> ref labels)."""
    head_hash = run_git(path, ["rev-parse", "HEAD"]).strip()
    try:
        head_name = run_git(
            path, ["symbolic-ref", "--quiet", "--short", "HEAD"]
        ).strip()
    except GitError:
        head_name = ""

    raw = run_git(
        path,
        [
            "for-each-ref",
            "--sort=-creatordate",
            "--format=%(objectname)%1f%(refname)%1f%(HEAD)",
            "refs/heads",
            "refs/remotes",
            "refs/tags",
        ],
    )
    by_hash: dict[str, list[str]] = {}
    for line in raw.splitlines():
        if not line.strip():
            continue
        bits = line.split("\x1f")
        if len(bits) < 2:
            continue
        obj, refname = bits[0], bits[1]
        if refname.startswith("refs/heads/"):
            label = refname[len("refs/heads/") :]
        elif refname.startswith("refs/remotes/"):
            label = refname[len("refs/remotes/") :]
        elif refname.startswith("refs/tags/"):
            label = "tag: " + refname[len("refs/tags/") :]
        else:
            label = refname
        by_hash.setdefault(obj, []).append(label)

    if head_name:
        head_label = f"HEAD -> {head_name}"
    else:
        head_label = "HEAD"
    by_hash.setdefault(head_hash, [])
    if head_label not in by_hash[head_hash]:
        by_hash[head_hash].insert(0, head_label)
    return head_hash, head_name, by_hash


def _has_uncommitted(path: Path) -> bool:
    raw = run_git(path, ["status", "--porcelain=v1"])
    return bool(raw.strip())


def load_graph(
    path: Path, offset: int = 0, limit: int = 300
) -> dict:
    if offset < 0 or limit < 1:
        raise GitError("invalid offset or limit")
    want = offset + limit + 1
    pretty = (
        f"%x1e%H%x1f%P%x1f%an%x1f%at%x1f%s%x1f%b"
    )
    raw = run_git(
        path,
        [
            "log",
            "--all",
            "--date-order",
            f"-n{want}",
            f"--pretty=format:{pretty}",
        ],
    )
    git_commits = _parse_log(raw)
    has_more = len(git_commits) > offset + limit
    git_commits = git_commits[: offset + limit]
    if not git_commits:
        return {
            "head": "",
            "head_hash": "",
            "has_more": False,
            "lane_count": 1,
            "commits": [],
        }
    head_hash, head_name, refs = _load_refs(path)
    for c in git_commits:
        c.refs = refs.get(c.hash, [])

    rows = git_commits
    if _has_uncommitted(path) and git_commits:
        parent = head_hash if head_hash else git_commits[0].hash
        rows = [
            Commit(
                hash=UNCOMMITTED,
                parents=[parent],
                author="",
                author_at=git_commits[0].author_at,
                subject="Uncommitted changes",
                refs=[],
                uncommitted=True,
            ),
            *git_commits,
        ]

    assign_lanes(rows)
    page = rows[offset : offset + limit]
    lane_count = 1
    for c in page:
        lane_count = max(
            lane_count,
            c.lane + 1,
            (max(c.through) + 1) if c.through else 1,
            (max(c.joins) + 1) if c.joins else 1,
        )
    return {
        "head": head_name or head_hash[:8],
        "head_hash": head_hash,
        "has_more": has_more,
        "lane_count": lane_count,
        "commits": [c.to_json() for c in page],
    }


def load_commit(path: Path, chash: str) -> dict:
    if chash == UNCOMMITTED:
        status = run_git(path, ["status", "--porcelain=v1", "-b"])
        head_hash, head_name, _refs = _load_refs(path)
        return {
            "hash": UNCOMMITTED,
            "parents": [head_hash],
            "author": "",
            "author_at": 0,
            "subject": "Uncommitted changes",
            "body": status.strip("\n"),
            "refs": [],
            "uncommitted": True,
            "head": head_name,
        }
    if not all(c in "0123456789abcdefABCDEF" for c in chash) or len(chash) < 7:
        raise GitError("invalid commit hash")
    pretty = "%H%x1f%P%x1f%an%x1f%at%x1f%s%x1f%b"
    raw = run_git(
        path,
        ["log", "-1", f"--pretty=format:{pretty}", chash],
    )
    parts = raw.split(FIELD_SEP)
    if len(parts) < 6:
        raise GitError("commit not found")
    _h, head_name, refs = _load_refs(path)
    full = parts[0].strip()
    return {
        "hash": full,
        "parents": [p for p in parts[1].split() if p],
        "author": parts[2],
        "author_at": int(parts[3] or "0"),
        "subject": parts[4],
        "body": parts[5].strip("\n"),
        "refs": refs.get(full, []),
        "uncommitted": False,
        "head": head_name,
    }
