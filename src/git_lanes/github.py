from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import webbrowser
from pathlib import Path

from git_lanes.discover import APP_ROOT, candidate_roots
from git_lanes.gitio import GitError, fetch_all, is_work_tree, origin_url, toplevel
from git_lanes.store import load_state, resolve_repo, set_github_user, upsert_repo, visible_repos

log = logging.getLogger("git_lanes.github")

CREATE_NO_WINDOW = 0x08000000
INSTALL_URL = "https://cli.github.com/"
DEVICE_URL = "https://github.com/login/device"
CODE_RE = re.compile(r"one-time code:\s*([A-Z0-9]{4}-[A-Z0-9]{4})", re.I)
URI_RE = re.compile(r"https://github\.com/login/device[^\s]*")

_GH_EXE: str | None = None
_login_lock = threading.Lock()
_login = {
    "proc": None,
    "user_code": "",
    "verification_uri": "",
    "error": "",
    "lines": [],
}


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
        winget = Path(local) / "Microsoft" / "WinGet" / "Packages"
        if winget.is_dir():
            candidates.extend(sorted(winget.glob("GitHub.cli*/gh.exe")))
            candidates.extend(sorted(winget.glob("GitHub.cli*/*/gh.exe")))
    home = Path.home()
    candidates.extend(
        [
            home / "scoop" / "apps" / "gh" / "current" / "gh.exe",
            Path(os.environ.get("ProgramData", r"C:\ProgramData"))
            / "chocolatey"
            / "bin"
            / "gh.exe",
        ]
    )
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


def parse_login_banner(text: str) -> tuple[str, str]:
    code = ""
    uri = ""
    for match in CODE_RE.finditer(text or ""):
        code = match.group(1).upper()
    for match in URI_RE.finditer(text or ""):
        uri = match.group(0).rstrip(".,)>")
    return code, uri or (DEVICE_URL if code else "")


def _login_snapshot() -> dict:
    proc = _login["proc"]
    pending = bool(proc is not None and proc.poll() is None)
    return {
        "login_pending": pending,
        "user_code": _login["user_code"] if pending else "",
        "verification_uri": _login["verification_uri"] if pending else "",
        "login_error": _login["error"] if not pending else "",
    }


def _kill_login() -> None:
    with _login_lock:
        proc = _login["proc"]
        _login["proc"] = None
        _login["user_code"] = ""
        _login["verification_uri"] = ""
        _login["error"] = ""
        _login["lines"] = []
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=3)
    except Exception:
        try:
            proc.kill()
        except OSError:
            pass


def _open_system_browser(url: str) -> None:
    try:
        webbrowser.open(url, new=2)
    except Exception:
        log.exception("open browser %s", url)


def _consume_login(proc: subprocess.Popen) -> None:
    buf = ""
    try:
        assert proc.stderr is not None
        for line in proc.stderr:
            buf += line
            with _login_lock:
                _login["lines"].append(line)
                code, uri = parse_login_banner(buf)
                if code:
                    _login["user_code"] = code
                if uri:
                    _login["verification_uri"] = uri
        rc = proc.wait()
        with _login_lock:
            if rc == 0:
                _login["error"] = ""
            else:
                _login["error"] = buf.strip()[-500:] or "GitHub login did not finish"
        if rc == 0:
            try:
                _run_gh(["auth", "setup-git"])
            except GitError:
                log.exception("gh auth setup-git")
            try:
                raw = _run_gh(["api", "user"])
                login = str(json.loads(raw).get("login") or "")
                if login:
                    set_github_user(login)
            except (GitError, json.JSONDecodeError):
                log.exception("remember github user")
    except Exception as exc:
        log.exception("login reader")
        with _login_lock:
            _login["error"] = str(exc)


def _press_enter(proc: subprocess.Popen) -> None:
    # gh prints the device code then waits for Enter before it keeps polling.
    if proc.stdin is None:
        return
    try:
        proc.stdin.write("\n")
        proc.stdin.flush()
    except Exception:
        log.exception("gh login enter")


def open_device_page() -> dict:
    with _login_lock:
        uri = _login["verification_uri"] or DEVICE_URL
        code = _login["user_code"]
    _open_system_browser(uri)
    return {"ok": True, "verification_uri": uri, "user_code": code}


def open_install_page() -> dict:
    _open_system_browser(INSTALL_URL)
    return {"ok": True, "install_url": INSTALL_URL}


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
        st = {
            "gh_ok": False,
            "logged_in": False,
            "user": "",
            "install_url": INSTALL_URL,
            "error": str(exc),
        }
        with _login_lock:
            st.update(_login_snapshot())
        st["remembered"] = False
        st["remembered_user"] = load_state().get("github_user") or ""
        return st
    try:
        raw = _run_gh(["api", "user"])
        data = json.loads(raw)
        login = str(data.get("login") or "")
        st = {
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
        st = {
            "gh_ok": True,
            "logged_in": False,
            "user": "",
            "install_url": INSTALL_URL,
            "error": msg,
            "gh": exe,
        }
    except json.JSONDecodeError:
        st = {
            "gh_ok": True,
            "logged_in": False,
            "user": "",
            "install_url": INSTALL_URL,
            "error": "gh api user returned invalid json",
            "gh": exe,
        }
    with _login_lock:
        st.update(_login_snapshot())
        if st.get("logged_in"):
            proc = _login["proc"]
            if proc is not None and proc.poll() is not None:
                _login["proc"] = None
                _login["user_code"] = ""
                _login["verification_uri"] = ""
                _login["error"] = ""
            st["login_pending"] = False
            st["user_code"] = ""
            st["verification_uri"] = ""
    if st.get("logged_in") and st.get("user"):
        set_github_user(st["user"])
        st["remembered"] = True
        st["remembered_user"] = st["user"]
    else:
        st["remembered"] = False
        st["remembered_user"] = load_state().get("github_user") or ""
    return st


def start_login() -> dict:
    st = status()
    if st.get("logged_in"):
        return {"started": False, "already": True, **st}
    if not st.get("gh_ok"):
        raise GitError(st.get("error") or "gh not found")

    with _login_lock:
        proc = _login["proc"]
        if proc is not None and proc.poll() is None and _login["user_code"]:
            uri = _login["verification_uri"] or DEVICE_URL
            code = _login["user_code"]
            reuse = True
        else:
            reuse = False
            code = ""
            uri = DEVICE_URL

    if reuse:
        _press_enter(proc)
        _open_system_browser(uri)
        st = status()
        return {"started": True, "already": False, **st}

    env = os.environ.copy()
    env["BROWSER"] = "false"
    env["GH_BROWSER"] = "false"
    flags = CREATE_NO_WINDOW if os.name == "nt" else 0
    _kill_login()
    proc = subprocess.Popen(
        [
            gh_exe(),
            "auth",
            "login",
            "--hostname",
            "github.com",
            "--git-protocol",
            "https",
            "--web",
            "--skip-ssh-key",
            "--scopes",
            "repo,read:org,gist",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        creationflags=flags,
    )
    with _login_lock:
        _login["proc"] = proc
        _login["user_code"] = ""
        _login["verification_uri"] = ""
        _login["error"] = ""
        _login["lines"] = []
    threading.Thread(target=_consume_login, args=(proc,), daemon=True).start()

    deadline = time.time() + 10
    code = ""
    uri = ""
    while time.time() < deadline:
        with _login_lock:
            code = _login["user_code"]
            uri = _login["verification_uri"]
            alive = _login["proc"] is not None and _login["proc"].poll() is None
            err = _login["error"]
        if code:
            _press_enter(proc)
            break
        if not alive and not code:
            _kill_login()
            raise GitError(err or "could not start GitHub login")
        time.sleep(0.1)
    if not code:
        with _login_lock:
            tail = "".join(_login["lines"])[-300:]
        _kill_login()
        raise GitError("could not read GitHub login code. " + tail)

    _open_system_browser(uri or DEVICE_URL)
    log.info("github device login code issued")
    st = status()
    return {"started": True, "already": False, **st}


def logout() -> dict:
    _kill_login()
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
    set_github_user("")
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
