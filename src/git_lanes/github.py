from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

from git_lanes.discover import APP_ROOT, candidate_roots
from git_lanes.gitio import GitError, fetch_all, is_work_tree, origin_url, toplevel
from git_lanes.store import resolve_repo, upsert_repo, visible_repos

log = logging.getLogger("git_lanes.github")

CREATE_NEW_CONSOLE = 0x00000010
CREATE_NO_WINDOW = 0x08000000
INSTALL_URL = "https://cli.github.com/"

_GH_EXE: str | None = None


def gh_exe() -> str:
    global _GH_EXE
    if _GH_EXE:
        return _GH_EXE
    override = os.environ.get("GIT_LANES_GH")
    if override and Path(override).is_file():
        _GH_EXE = override
        return _GH_EXE
    found = shutil.which("gh")
    if found:
        _GH_EXE = found
        return _GH_EXE
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    local = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        Path(pf) / "GitHub CLI" / "gh.exe",
        Path(pf86) / "GitHub CLI" / "gh.exe",
    ]
    if local:
        candidates.append(Path(local) / "Programs" / "GitHub CLI" / "gh.exe")
    for path in candidates:
        if path.is_file():
            _GH_EXE = str(path)
            return _GH_EXE
    raise GitError("GitHub CLI (gh) not found. Install from " + INSTALL_URL)


def _run_gh(args: list[str], timeout: int = 60, *, hide: bool = True) -> str:
    flags = CREATE_NO_WINDOW if hide and os.name == "nt" else 0
    try:
        proc = subprocess.run(
            [gh_exe(), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            timeout=timeout,
            creationflags=flags,
        )
    except FileNotFoundError as exc:
        raise GitError("GitHub CLI (gh) not found. Install from " + INSTALL_URL) from exc
    except subprocess.TimeoutExpired as exc:
        raise GitError("gh timed out") from exc
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "gh failed").strip()
        if "not logged" in err.lower() or "no github hosts" in err.lower():
            raise GitError("not signed in to GitHub")
        raise GitError(err)
    return proc.stdout


def normalize_github_name(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    raw = raw.removesuffix(".git")
    ssh = re.match(r"^git@[^:]+:(.+)$", raw)
    if ssh:
        return ssh.group(1).strip("/").casefold()
    ssh2 = re.match(r"^ssh://git@[^/]+/(.+)$", raw)
    if ssh2:
        return ssh2.group(1).strip("/").casefold()
    m = re.search(r"github\.com[/:](.+)$", raw, re.I)
    if m:
        return m.group(1).strip("/").casefold()
    return raw.strip("/").casefold()


def clone_parent() -> Path:
    roots = candidate_roots()
    parent = APP_ROOT.parent
    for root in roots:
        try:
            if root == parent or parent.is_relative_to(root):
                return root
        except (ValueError, OSError):
            if root == parent:
                return root
    if roots:
        return roots[0]
    parent.mkdir(parents=True, exist_ok=True)
    return parent


def status() -> dict:
    try:
        exe = gh_exe()
    except GitError as exc:
        return {
            "gh_ok": False,
            "logged_in": False,
            "user": "",
            "install_url": INSTALL_URL,
            "error": str(exc),
        }
    try:
        raw = _run_gh(["api", "user"])
        data = json.loads(raw)
        login = str(data.get("login") or "")
        return {
            "gh_ok": True,
            "logged_in": bool(login),
            "user": login,
            "install_url": INSTALL_URL,
            "error": "",
            "gh": exe,
        }
    except GitError as exc:
        msg = str(exc)
        if "gh auth login" in msg.lower() or "not logged" in msg.lower() or "no github hosts" in msg.lower():
            msg = ""
        return {
            "gh_ok": True,
            "logged_in": False,
            "user": "",
            "install_url": INSTALL_URL,
            "error": msg,
            "gh": exe,
        }
    except json.JSONDecodeError:
        return {
            "gh_ok": True,
            "logged_in": False,
            "user": "",
            "install_url": INSTALL_URL,
            "error": "gh api user returned invalid json",
            "gh": exe,
        }


def start_login() -> dict:
    st = status()
    if st.get("logged_in"):
        return {"started": False, "already": True, **st}
    if not st.get("gh_ok"):
        raise GitError(st.get("error") or "gh not found")
    gh = st.get("gh") or gh_exe()
    script = (
        f'"{gh}" auth login --hostname github.com --git-protocol https'
        " --web --skip-ssh-key --clipboard"
        f' && "{gh}" auth setup-git'
        " && echo Login finished. You can close this window."
        " && pause"
    )
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = CREATE_NEW_CONSOLE
    subprocess.Popen(["cmd.exe", "/c", script], **kwargs)
    log.info("started gh auth login")
    return {"started": True, "already": False, **st}


def logout() -> dict:
    st = status()
    user = st.get("user") or ""
    args = ["auth", "logout", "--hostname", "github.com"]
    if user:
        args.extend(["--user", user])
    try:
        _run_gh(args)
    except GitError as exc:
        if st.get("logged_in"):
            raise
        log.info("logout: %s", exc)
    return status()


def _local_by_github_name() -> dict[str, dict]:
    found: dict[str, dict] = {}
    for rec in visible_repos():
        path = Path(rec["path"])
        key = ""
        if path.exists():
            key = normalize_github_name(origin_url(path))
        if not key:
            key = normalize_github_name(rec["name"])
        if key:
            found[key] = rec
        found[rec["name"].casefold()] = rec
    return found


def list_remote_repos() -> dict:
    st = status()
    if not st.get("logged_in"):
        return {"repos": [], **st}
    raw = _run_gh(
        [
            "repo",
            "list",
            "--limit",
            "200",
            "--json",
            "name,nameWithOwner,url,isPrivate,isFork,updatedAt",
        ],
        timeout=90,
    )
    try:
        items = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GitError("gh repo list returned invalid json") from exc
    if not isinstance(items, list):
        items = []
    local = _local_by_github_name()
    repos = []
    for item in items:
        if not isinstance(item, dict):
            continue
        nwo = str(item.get("nameWithOwner") or "")
        name = str(item.get("name") or "")
        url = str(item.get("url") or "")
        key = normalize_github_name(nwo or url)
        match = local.get(key) or local.get(name.casefold())
        repos.append(
            {
                "name": name,
                "nameWithOwner": nwo,
                "url": url,
                "private": bool(item.get("isPrivate")),
                "fork": bool(item.get("isFork")),
                "updated_at": str(item.get("updatedAt") or ""),
                "local": match,
            }
        )
    repos.sort(key=lambda r: (r["local"] is None, r["nameWithOwner"].casefold()))
    dest = str(clone_parent())
    return {"repos": repos, "clone_parent": dest, **st}


def clone_named(name_with_owner: str) -> dict:
    nwo = name_with_owner.strip().strip("/")
    if not re.match(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$", nwo):
        raise GitError("invalid repo name")
    parent = clone_parent()
    folder = parent / nwo.split("/")[-1]
    if folder.exists():
        if is_work_tree(folder):
            rec = upsert_repo(toplevel(folder), select=True)
            return {"repo": rec, "cloned": False, "path": str(folder)}
        raise GitError("folder exists and is not a git repository")
    log.info("clone %s into %s", nwo, parent)
    _run_gh(["repo", "clone", nwo, str(folder)], timeout=300)
    if not is_work_tree(folder):
        raise GitError("clone finished but not a git repository")
    rec = upsert_repo(toplevel(folder), select=True)
    return {"repo": rec, "cloned": True, "path": str(folder)}


def fetch_named(repo_id: str) -> dict:
    path = resolve_repo(repo_id)
    if path is None:
        raise GitError("unknown repo")
    out = fetch_all(path)
    return {"ok": True, "repo_id": repo_id, "output": (out or "").strip()[:500]}
