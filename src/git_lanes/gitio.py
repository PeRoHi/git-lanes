from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger("git_lanes.gitio")

from git_lanes.lanes import Commit, assign_lanes

CREATE_NO_WINDOW = 0x08000000
UNCOMMITTED = "UNCOMMITTED"
RECORD_SEP = "\x1e"
FIELD_SEP = "\x1f"

_GIT_EXE: str | None = None

_GIT_OVERRIDE_KEYS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_COMMON_DIR",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
)


def child_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in _GIT_OVERRIDE_KEYS:
        env.pop(key, None)
    return env


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
            env=child_env(),
            creationflags=_creationflags(),
        )
    except FileNotFoundError as exc:
        raise GitError("git executable not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitError("git timed out") from exc
    if proc.returncode != 0:
        cmd = args[0] if args else "git"
        log.info("git failed rc=%s cmd=%s", proc.returncode, cmd)
        raise GitError("git failed")
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


def _check_rev(path: Path, rev: str) -> str:
    name = str(rev or "").strip()
    if not name:
        return ""
    if name.startswith("-") or ".." in name:
        raise GitError("invalid ref")
    if not re.fullmatch(r"[A-Za-z0-9._/\-@{}]+", name):
        raise GitError("invalid ref")
    try:
        run_git(path, ["rev-parse", "--verify", "--quiet", name + "^{commit}"])
    except GitError as exc:
        raise GitError("unknown ref") from exc
    return name


def _stash_commits(path: Path) -> list[Commit]:
    try:
        raw = run_git(
            path,
            [
                "stash",
                "list",
                f"--format=%H{FIELD_SEP}%P{FIELD_SEP}%an{FIELD_SEP}%at{FIELD_SEP}%s{FIELD_SEP}%gd",
            ],
        )
    except GitError:
        return []
    out: list[Commit] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        bits = line.split(FIELD_SEP)
        if len(bits) < 6:
            continue
        try:
            author_at = int((bits[3] or "0").strip() or "0")
        except ValueError:
            author_at = 0
        label = bits[5].strip() or "stash"
        out.append(
            Commit(
                hash=bits[0].strip(),
                parents=[p for p in bits[1].split() if p],
                author=bits[2],
                author_at=author_at,
                subject=bits[4],
                refs=[label],
                stash=True,
            )
        )
    return out


def list_changed_files(path: Path, chash: str) -> list[dict]:
    files: list[dict] = []
    if chash == UNCOMMITTED:
        raw = run_git(path, ["status", "--porcelain=v1"])
        for line in raw.splitlines():
            if len(line) < 4:
                continue
            status = line[:2].strip() or line[0]
            rel = line[3:]
            if rel.startswith('"') and rel.endswith('"'):
                rel = rel[1:-1]
            if " -> " in rel:
                rel = rel.split(" -> ", 1)[-1]
            files.append({"status": status, "path": rel})
        return files
    if not all(c in "0123456789abcdefABCDEF" for c in chash) or len(chash) < 7:
        raise GitError("invalid commit hash")
    spec = run_git(path, ["rev-list", "--parents", "-n", "1", chash]).strip().split()
    if len(spec) >= 2:
        raw = run_git(path, ["diff", "--name-status", "-M", spec[1], spec[0]])
    else:
        raw = run_git(
            path,
            ["diff-tree", "--no-commit-id", "--name-status", "-r", "--root", chash],
        )
    for line in raw.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) == 2:
            files.append({"status": parts[0], "path": parts[1]})
        elif len(parts) >= 3:
            files.append({"status": parts[0], "path": parts[-1], "from": parts[1]})
    return files


def search_commits(path: Path, query: str, limit: int = 25) -> list[dict]:
    q = str(query or "").strip()
    if not q or q.startswith("-") or "\n" in q or "\r" in q:
        return []
    if len(q) > 200:
        q = q[:200]
    limit = min(max(int(limit), 1), 50)
    pretty = f"%x1e%H%x1f%P%x1f%an%x1f%at%x1f%s%x1f%b"
    hits: list[Commit] = []
    if re.fullmatch(r"[0-9a-fA-F]{4,40}", q):
        try:
            raw = run_git(
                path,
                ["log", "-1", "--all", f"--pretty=format:{pretty}", q],
            )
            hits = _parse_log(raw)
        except GitError:
            hits = []
    if not hits:
        raw = run_git(
            path,
            [
                "log",
                "--all",
                "--date-order",
                "-i",
                "--fixed-strings",
                f"--grep={q}",
                f"-n{limit}",
                f"--pretty=format:{pretty}",
            ],
        )
        hits = _parse_log(raw)
    _, _, refs = _load_refs(path)
    out = []
    for c in hits[:limit]:
        c.refs = refs.get(c.hash, [])
        row = c.to_json()
        row["kind"] = "commit"
        row["name"] = (c.hash or "")[:8]
        out.append(row)
    return out


def load_graph(
    path: Path, offset: int = 0, limit: int = 300, rev: str = ""
) -> dict:
    if offset < 0 or limit < 1:
        raise GitError("invalid offset or limit")
    want = offset + limit + 1
    pretty = (
        f"%x1e%H%x1f%P%x1f%an%x1f%at%x1f%s%x1f%b"
    )
    checked = _check_rev(path, rev) if str(rev or "").strip() else ""
    log_cmd = [
        "log",
        "--date-order",
        f"-n{want}",
        f"--pretty=format:{pretty}",
    ]
    log_cmd.append(checked if checked else "--all")
    raw = run_git(path, log_cmd)
    git_commits = _parse_log(raw)
    has_more = len(git_commits) > offset + limit
    git_commits = git_commits[: offset + limit]
    head_hash, head_name, refs = _load_refs(path)
    if not git_commits:
        return {
            "head": head_name or (head_hash[:8] if head_hash else ""),
            "head_hash": head_hash,
            "ref": checked,
            "has_more": False,
            "lane_count": 1,
            "commits": [],
        }
    for c in git_commits:
        c.refs = refs.get(c.hash, [])

    extras: list[Commit] = []
    if not checked:
        if _has_uncommitted(path):
            parent = head_hash if head_hash else git_commits[0].hash
            extras.append(
                Commit(
                    hash=UNCOMMITTED,
                    parents=[parent],
                    author="",
                    author_at=git_commits[0].author_at,
                    subject="Uncommitted changes",
                    refs=[],
                    uncommitted=True,
                )
            )
        extras.extend(_stash_commits(path))
    stash_hashes = {c.hash for c in extras if c.stash}
    if stash_hashes:
        git_commits = [c for c in git_commits if c.hash not in stash_hashes]
    rows = extras + git_commits

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
        for e in c.edges:
            lane_count = max(
                lane_count, int(e.get("from_lane", 0)) + 1, int(e.get("to_lane", 0)) + 1
            )
    return {
        "head": head_name or head_hash[:8],
        "head_hash": head_hash,
        "ref": checked,
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
            "stash": False,
            "files": list_changed_files(path, UNCOMMITTED),
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
        "author_at": int(parts[3] or "0") if str(parts[3] or "0").strip().isdigit() else 0,
        "subject": parts[4],
        "body": parts[5].strip("\n"),
        "refs": refs.get(full, []),
        "uncommitted": False,
        "stash": False,
        "files": list_changed_files(path, full),
        "head": head_name,
    }
