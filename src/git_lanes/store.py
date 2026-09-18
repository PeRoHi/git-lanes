from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path

APP_DIR_NAME = "git-lanes"


class StoreError(Exception):
    pass


_config_load_failed = False
_state_load_failed = False


def app_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    d = Path(base) / APP_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _config_path() -> Path:
    return app_dir() / "config.json"


def _state_path() -> Path:
    return app_dir() / "state.json"


def _is_symlink(path: Path) -> bool:
    try:
        return path.is_symlink()
    except OSError:
        return True


def _read_json(path: Path, default) -> tuple[object, bool]:
    if _is_symlink(path):
        return default, True
    try:
        if not path.exists():
            return default, False
    except OSError:
        return default, True
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(str(path), flags)
    except OSError:
        return default, True
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return default, True
        if st.st_size == 0:
            return default, True
        raw = os.read(fd, st.st_size)
    except OSError:
        return default, True
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return default, True
    return data, False


def _prepare_tmp(tmp: Path) -> None:
    if _is_symlink(tmp):
        raise OSError("refuse symlink write")
    try:
        exists = tmp.exists()
    except OSError as exc:
        raise OSError("refuse leftover tmp") from exc
    if not exists:
        return
    try:
        if tmp.is_file() and not _is_symlink(tmp):
            tmp.unlink()
            return
    except OSError as exc:
        raise OSError("refuse leftover tmp") from exc
    raise OSError("refuse leftover tmp")


def _write_json(path: Path, data) -> None:
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if not payload.strip():
        raise OSError("refuse empty write")
    dest = path
    parent = dest.parent
    tmp = dest.with_name(dest.name + ".tmp")
    parent.mkdir(parents=True, exist_ok=True)
    if _is_symlink(dest) or _is_symlink(parent) or _is_symlink(tmp):
        raise OSError("refuse symlink write")
    if dest.exists() and not _is_symlink(dest):
        try:
            size = dest.stat().st_size if dest.is_file() else -1
        except OSError as exc:
            raise OSError("refuse unreadable dest") from exc
        if size > 0 and not payload.strip():
            raise OSError("refuse empty overwrite")
    _prepare_tmp(tmp)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(str(tmp), flags, 0o644)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fd = -1
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
    except Exception:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        if not _is_symlink(tmp):
            try:
                tmp.unlink()
            except OSError:
                pass
        raise
    os.replace(str(tmp), str(dest))
    try:
        dir_fd = os.open(str(parent), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        os.close(dir_fd)


def load_config() -> dict:
    global _config_load_failed
    data, failed = _read_json(_config_path(), {"repos": [], "scan_roots": []})
    _config_load_failed = failed
    if failed:
        return {"repos": [], "scan_roots": []}
    repos = data.get("repos") if isinstance(data, dict) else None
    if not isinstance(data, dict):
        _config_load_failed = True
        return {"repos": [], "scan_roots": []}
    if not isinstance(repos, list):
        repos = []
    clean = []
    for r in repos:
        if not isinstance(r, dict):
            continue
        rid = str(r.get("id") or "")
        path = str(r.get("path") or "")
        name = str(r.get("name") or Path(path).name or rid)
        if rid and path:
            clean.append({"id": rid, "name": name, "path": path})
    roots = data.get("scan_roots") if isinstance(data, dict) else None
    if not isinstance(roots, list):
        roots = []
    clean_roots = []
    seen_roots: set[str] = set()
    for raw in roots:
        if not isinstance(raw, str):
            continue
        item = raw.strip()
        if not item:
            continue
        key = item.casefold()
        if key in seen_roots:
            continue
        seen_roots.add(key)
        clean_roots.append(item)
    return {"repos": clean, "scan_roots": clean_roots}


def load_state() -> dict:
    global _state_load_failed
    data, failed = _read_json(_state_path(), {})
    if failed or not isinstance(data, dict):
        _state_load_failed = True
        return {"last_opened": "", "github_user": ""}
    _state_load_failed = False
    return {
        "last_opened": str(data.get("last_opened") or ""),
        "github_user": str(data.get("github_user") or ""),
    }


def config_unreadable() -> bool:
    load_config()
    return _config_load_failed


def state_unreadable() -> bool:
    load_state()
    return _state_load_failed


def set_github_user(login: str) -> None:
    st = load_state()
    name = str(login or "").strip()
    if st.get("github_user") == name:
        return
    st["github_user"] = name
    save_state(st)


def save_config(cfg: dict) -> None:
    if config_unreadable():
        raise StoreError("store unreadable")
    _write_json(_config_path(), cfg)


def save_state(state: dict) -> None:
    prev = load_state()
    if _state_load_failed:
        raise StoreError("store unreadable")
    merged = {
        "last_opened": str(
            state["last_opened"] if "last_opened" in state else prev.get("last_opened") or ""
        ),
        "github_user": str(
            state["github_user"] if "github_user" in state else prev.get("github_user") or ""
        ),
    }
    _write_json(_state_path(), merged)


def _slug(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-").lower()
    return s or "repo"


def make_id(path: Path, existing: set[str]) -> str:
    base = _slug(path.name)
    if base not in existing:
        return base
    n = 2
    while f"{base}-{n}" in existing:
        n += 1
    return f"{base}-{n}"


def _path_exists(raw: str) -> bool:
    try:
        return Path(raw).exists()
    except OSError:
        return False


def _same_path(raw: str, path: Path) -> bool:
    try:
        return Path(raw).resolve() == path.resolve()
    except OSError:
        return os.path.normcase(os.path.normpath(raw)) == os.path.normcase(str(path))


def visible_repos() -> list[dict]:
    out = []
    for rec in load_config()["repos"]:
        if _path_exists(rec["path"]):
            out.append(rec)
    out.sort(key=lambda r: r["name"].casefold())
    return out


def add_scan_root(path: Path) -> None:
    try:
        raw = str(path.resolve())
    except OSError:
        raw = str(path)
    cfg = load_config()
    key = raw.casefold()
    for existing in cfg["scan_roots"]:
        if existing.casefold() == key:
            return
    cfg["scan_roots"].append(raw)
    save_config(cfg)


def resolve_repo(repo_id: str) -> Path | None:
    cfg = load_config()
    for r in cfg["repos"]:
        if r["id"] == repo_id:
            p = Path(r["path"])
            if _path_exists(r["path"]):
                return p
            return None
    return None


def upsert_repo(path: Path, name: str | None = None, *, select: bool = True) -> dict:
    path = path.resolve()
    cfg = load_config()
    for r in cfg["repos"]:
        if _same_path(r["path"], path):
            if select:
                st = load_state()
                st["last_opened"] = r["id"]
                save_state(st)
            return r
    existing = {r["id"] for r in cfg["repos"]}
    rid = make_id(path, existing)
    rec = {"id": rid, "name": name or path.name, "path": str(path)}
    cfg["repos"].append(rec)
    save_config(cfg)
    if select:
        st = load_state()
        st["last_opened"] = rid
        save_state(st)
    return rec


def pick_last_or_none() -> dict | None:
    visible = visible_repos()
    if not visible:
        return None
    st = load_state()
    last = st.get("last_opened") or ""
    by_id = {r["id"]: r for r in visible}
    if last in by_id:
        return by_id[last]
    return visible[0]
