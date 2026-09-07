from __future__ import annotations

import logging
import time
from pathlib import Path

from git_lanes.gitio import GitError, is_work_tree, toplevel
from git_lanes.store import (
    add_scan_root,
    load_config,
    load_state,
    pick_last_or_none,
    save_state,
    upsert_repo,
    visible_repos,
)

log = logging.getLogger("git_lanes.discover")

APP_ROOT = Path(__file__).resolve().parents[2]

SKIP_DIR_NAMES = {
    "$recycle.bin",
    ".cache",
    ".cursor",
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".svn",
    ".venv",
    "__pycache__",
    "appdata",
    "build",
    "dist",
    "edge-profile",
    "env",
    "node_modules",
    "system volume information",
    "user-data",
    "venv",
    "windows",
}

MAX_DEPTH = 4
MAX_VISITS = 1200
MAX_REPOS = 120
SCAN_SECONDS = 8


def _exists_dir(path: Path) -> Path | None:
    try:
        if path.is_dir():
            return path.resolve()
    except OSError:
        return None
    return None


def candidate_roots(
    *,
    home: Path | None = None,
    app_root: Path | None = None,
    extra: list[str] | None = None,
) -> list[Path]:
    """Personal workspace folders. No machine-specific paths in source."""
    home = home or Path.home()
    app_root = app_root or APP_ROOT
    found: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        resolved = _exists_dir(path)
        if resolved is None:
            return
        key = str(resolved).casefold()
        if key in seen:
            return
        seen.add(key)
        found.append(resolved)

    relatives = (
        Path("Desktop") / "program",
        Path("Desktop") / "個人用" / "program file",
        Path("Desktop") / "life",
        Path("Documents") / "HDLSim",
        Path("OneDrive") / "Desktop" / "program",
        Path("OneDrive") / "Desktop" / "個人用" / "program file",
    )
    for rel in relatives:
        add(home / rel)

    add(app_root)
    add(app_root.parent)

    if extra is None:
        extra = load_config().get("scan_roots") or []
    for raw in extra:
        add(Path(str(raw)).expanduser())

    return found


def looks_like_git(path: Path) -> bool:
    git = path / ".git"
    try:
        return git.is_dir() or git.is_file()
    except OSError:
        return False


def walk_repos(
    roots: list[Path],
    *,
    max_depth: int = MAX_DEPTH,
    max_visits: int = MAX_VISITS,
    max_repos: int = MAX_REPOS,
    deadline: float | None = None,
) -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()
    visits = 0
    if deadline is None:
        deadline = time.monotonic() + SCAN_SECONDS

    stack: list[tuple[Path, int]] = []
    for root in roots:
        resolved = _exists_dir(root)
        if resolved is not None:
            stack.append((resolved, 0))

    while stack:
        if time.monotonic() > deadline or visits >= max_visits or len(found) >= max_repos:
            break
        cur, depth = stack.pop()
        visits += 1
        if looks_like_git(cur):
            key = str(cur).casefold()
            if key not in seen:
                seen.add(key)
                found.append(cur)
            continue
        if depth >= max_depth:
            continue
        try:
            children = list(cur.iterdir())
        except OSError:
            continue
        for child in children:
            try:
                if not child.is_dir():
                    continue
            except OSError:
                continue
            name = child.name
            if name.startswith(".") or name.casefold() in SKIP_DIR_NAMES:
                continue
            stack.append((child, depth + 1))
    return found


def _is_under(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (OSError, ValueError):
        return False


def scan_and_merge(roots: list[Path] | None = None) -> dict:
    if roots is None:
        roots = candidate_roots()
    found = walk_repos(roots)
    added: list[dict] = []
    before = {r["id"] for r in load_config()["repos"]}
    for path in found:
        if not is_work_tree(path):
            continue
        try:
            top = toplevel(path)
        except GitError:
            log.info("skip %s: not a work tree", path)
            continue
        rec = upsert_repo(top, select=False)
        if rec["id"] not in before:
            added.append(rec)
            before.add(rec["id"])
    return {
        "added": added,
        "found": len(found),
        "repos": visible_repos(),
        "repo": pick_last_or_none(),
    }


def open_user_path(raw: str) -> dict:
    path = Path(raw).expanduser()
    if not path.exists():
        raise GitError("path not found")
    path = path.resolve()
    if is_work_tree(path):
        rec = upsert_repo(toplevel(path), select=True)
        return {
            "repo": rec,
            "added": [rec],
            "workspace": False,
            "repos": visible_repos(),
        }

    add_scan_root(path)
    result = scan_and_merge([path])
    under = [r for r in result["repos"] if _is_under(Path(r["path"]), path)]
    if not under:
        raise GitError("no git repository found")
    last = result.get("repo")
    if last is None or not _is_under(Path(last["path"]), path):
        chosen = under[0]
        st = load_state()
        st["last_opened"] = chosen["id"]
        save_state(st)
    else:
        chosen = last
    return {
        "repo": chosen,
        "added": result["added"],
        "workspace": True,
        "repos": visible_repos(),
    }
