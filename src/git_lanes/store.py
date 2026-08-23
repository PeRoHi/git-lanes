from __future__ import annotations

import json
import os
import re
from pathlib import Path

APP_DIR_NAME = "git-lanes"


def app_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    d = Path(base) / APP_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _config_path() -> Path:
    return app_dir() / "config.json"


def _state_path() -> Path:
    return app_dir() / "state.json"


def _read_json(path: Path, default):
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, data) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def load_config() -> dict:
    data = _read_json(_config_path(), {"repos": [], "scan_roots": []})
    repos = data.get("repos") if isinstance(data, dict) else None
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
    data = _read_json(_state_path(), {})
    if not isinstance(data, dict):
        return {}
    return {
        "last_opened": str(data.get("last_opened") or ""),
    }


def save_config(cfg: dict) -> None:
    _write_json(_config_path(), cfg)


def save_state(state: dict) -> None:
    _write_json(_state_path(), state)


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
