from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from git_lanes.lanes import Commit, assign_lanes

CREATE_NO_WINDOW = 0x08000000
UNCOMMITTED = "UNCOMMITTED"
RECORD_SEP = "\x1e"
FIELD_SEP = "\x1f"

_GIT_EXE: str | None = None


class GitError(Exception):
    pass


def git_exe() -> str:
    """Locate git without assuming it is already on PATH (fresh Windows)."""
    global _GIT_EXE
    if _GIT_EXE:
        return _GIT_EXE
    override = os.environ.get("GIT_LANES_GIT")
    if override and Path(override).is_file():
        _GIT_EXE = override
        return _GIT_EXE
    found = shutil.which("git")
    if found:
        _GIT_EXE = found
        return _GIT_EXE
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    local = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        Path(pf) / "Git" / "cmd" / "git.exe",
        Path(pf) / "Git" / "bin" / "git.exe",
        Path(pf86) / "Git" / "cmd" / "git.exe",
        Path(pf86) / "Git" / "bin" / "git.exe",
    ]
    if local:
        candidates.extend(
            [
                Path(local) / "Programs" / "Git" / "cmd" / "git.exe",
                Path(local) / "Programs" / "Git" / "bin" / "git.exe",
            ]
        )
    for path in candidates:
        if path.is_file():
            _GIT_EXE = str(path)
            return _GIT_EXE
    raise GitError("git executable not found")


def _creationflags() -> int:
    return CREATE_NO_WINDOW if os.name == "nt" else 0


def run_git(cwd: Path, args: list[str], timeout: int = 30) -> str:
    try:
        proc = subprocess.run(
            [git_exe(), *args],
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
        if not path.is_dir():
            return False
    except OSError:
        return False
    try:
        out = run_git(path, ["rev-parse", "--is-inside-work-tree"])
    except GitError:
        return False
    return out.strip() == "true"


def toplevel(path: Path) -> Path:
    out = run_git(path, ["rev-parse", "--show-toplevel"]).strip()
    return Path(out)


def origin_url(path: Path) -> str:
    try:
        return run_git(path, ["remote", "get-url", "origin"]).strip()
    except GitError:
        return ""


def fetch_all(path: Path) -> str:
    return run_git(path, ["fetch", "--all", "--prune"], timeout=120)


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


def _parse_track(raw: str) -> dict:
    text = str(raw or "").strip()
    ahead = 0
    behind = 0
    m = re.search(r"ahead (\d+)", text)
    if m:
        ahead = int(m.group(1))
    m = re.search(r"behind (\d+)", text)
    if m:
        behind = int(m.group(1))
    return {
        "ahead": ahead,
        "behind": behind,
        "gone": "gone" in text.lower(),
        "raw": text,
    }


def list_refs(path: Path) -> dict:
    """Tips of local / remote / tag refs, with optional upstream track."""
    head_hash, head_name, _labels = _load_refs(path)
    raw = run_git(
        path,
        [
            "for-each-ref",
            "--sort=-creatordate",
            "--format=%(*objectname)%1f%(objectname)%1f%(refname)%1f%(HEAD)%1f%(objecttype)%1f%(creatordate:unix)%1f%(authorname)%1f%(contents:subject)%1f%(upstream:short)%1f%(upstream:track,nobracket)",
            "refs/heads",
            "refs/remotes",
            "refs/tags",
        ],
    )
    refs: list[dict] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        bits = line.split("\x1f")
        if len(bits) < 8:
            continue
        peeled = bits[0].strip()
        obj = bits[1].strip()
        refname = bits[2]
        current = bits[3].strip() == "*"
        kind_raw = bits[4]
        try:
            author_at = int((bits[5] or "0").strip() or "0")
        except ValueError:
            author_at = 0
        author = bits[6]
        subject = bits[7]
        upstream = bits[8] if len(bits) > 8 else ""
        track_raw = bits[9] if len(bits) > 9 else ""
        tip = peeled or obj
        if not tip or not refname:
            continue
        if refname.startswith("refs/heads/"):
            kind = "local"
            name = refname[len("refs/heads/") :]
        elif refname.startswith("refs/remotes/"):
            kind = "remote"
            name = refname[len("refs/remotes/") :]
        elif refname.startswith("refs/tags/"):
            kind = "tag"
            name = refname[len("refs/tags/") :]
        else:
            kind = kind_raw or "other"
            name = refname
        track = _parse_track(track_raw)
        refs.append(
            {
                "name": name,
                "kind": kind,
                "hash": tip,
                "current": current,
                "author": author,
                "author_at": author_at,
                "subject": subject,
                "upstream": upstream,
                "ahead": track["ahead"],
                "behind": track["behind"],
                "gone": track["gone"],
            }
        )
    return {
        "head": head_name,
        "head_hash": head_hash,
        "refs": refs,
    }


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
