from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from git_lanes import HOST, INITIAL_LOAD, LOAD_MORE, PORT
from git_lanes.discover import open_user_path, scan_and_merge
from git_lanes.gitio import GitError, is_work_tree, load_commit, load_graph
from git_lanes.store import (
    load_state,
    pick_last_or_none,
    resolve_repo,
    save_state,
    visible_repos,
)

log = logging.getLogger("git_lanes.server")

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"

_httpd: ThreadingHTTPServer | None = None
_shutdown_lock = threading.Lock()
_shutting_down = False


def _json_bytes(data, status=200):
    return status, "application/json; charset=utf-8", json.dumps(
        data, ensure_ascii=False
    ).encode("utf-8")


def _choose_folder() -> str | None:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    try:
        root.wm_attributes("-topmost", True)
    except tk.TclError:
        pass
    path = filedialog.askdirectory(parent=root, mustexist=True)
    root.destroy()
    return path or None


def _repo_from_id(repo_id: str | None):
    if repo_id:
        path = resolve_repo(repo_id)
        if path is None:
            raise GitError("unknown repo")
        rec = next(r for r in visible_repos() if r["id"] == repo_id)
        return rec, path
    rec = pick_last_or_none()
    if rec is None:
        return None, None
    path = Path(rec["path"])
    if not path.exists():
        return rec, None
    return rec, path


def _handle_api(method: str, parsed, body: bytes):
    path = parsed.path
    qs = parse_qs(parsed.query)

    if path == "/api/health" and method == "GET":
        return _json_bytes({"ok": True, "name": "git-lanes"})

    if path == "/api/repos" and method == "GET":
        st = load_state()
        visible = visible_repos()
        last = st.get("last_opened") or ""
        if last and not any(r["id"] == last for r in visible):
            last = ""
        return _json_bytes({"repos": visible, "last_opened": last})

    if path == "/api/repos/browse" and method == "POST":
        chosen = _choose_folder()
        if not chosen:
            return _json_bytes({"cancelled": True})
        data = open_user_path(chosen)
        data["cancelled"] = False
        return _json_bytes(data)

    if path == "/api/repos/open" and method == "POST":
        try:
            payload = json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError as exc:
            raise GitError("invalid json") from exc
        raw = str(payload.get("path") or "")
        if not raw:
            raise GitError("path required")
        return _json_bytes(open_user_path(raw))

    if path == "/api/repos/scan" and method == "POST":
        roots = None
        if body:
            try:
                payload = json.loads(body.decode("utf-8") or "{}")
            except json.JSONDecodeError as exc:
                raise GitError("invalid json") from exc
            raw_roots = payload.get("roots") if isinstance(payload, dict) else None
            if raw_roots is not None:
                if not isinstance(raw_roots, list):
                    raise GitError("roots must be a list")
                roots = []
                for item in raw_roots:
                    p = Path(str(item)).expanduser()
                    if not p.exists():
                        raise GitError("path not found")
                    roots.append(p)
        return _json_bytes(scan_and_merge(roots))

    if path == "/api/repos/select" and method == "POST":
        try:
            payload = json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError as exc:
            raise GitError("invalid json") from exc
        rid = str(payload.get("id") or "")
        path_r = resolve_repo(rid)
        if path_r is None:
            raise GitError("unknown repo")
        st = load_state()
        st["last_opened"] = rid
        save_state(st)
        rec = next(r for r in visible_repos() if r["id"] == rid)
        return _json_bytes({"repo": rec})

    if path == "/api/graph" and method == "GET":
        rec, repo_path = _repo_from_id((qs.get("repo_id") or [""])[0] or None)
        if rec is None:
            return _json_bytes({"need_open": True, "commits": []})
        if repo_path is None or not is_work_tree(repo_path):
            raise GitError("not a git repository")
        try:
            offset = int((qs.get("offset") or ["0"])[0])
            limit = int((qs.get("limit") or [str(INITIAL_LOAD)])[0])
        except ValueError as exc:
            raise GitError("invalid paging") from exc
        limit = min(max(limit, 1), LOAD_MORE * 2)
        data = load_graph(repo_path, offset=offset, limit=limit)
        data["need_open"] = False
        data["repo"] = {
            "id": rec["id"],
            "name": rec["name"],
            "path": rec["path"],
            "head": data.get("head") or "",
        }
        return _json_bytes(data)

    if path == "/api/commit" and method == "GET":
        rec, repo_path = _repo_from_id((qs.get("repo_id") or [""])[0] or None)
        if repo_path is None:
            raise GitError("unknown repo")
        chash = (qs.get("hash") or [""])[0]
        if not chash:
            raise GitError("hash required")
        data = load_commit(repo_path, chash)
        data["repo_id"] = rec["id"]
        return _json_bytes(data)

    if path == "/api/shutdown" and method == "POST":
        shutdown_async()
        return _json_bytes({"ok": True})

    return 404, "application/json; charset=utf-8", b'{"error":"not found"}'


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:
        log.info("%s - %s", self.address_string(), fmt % args)

    def _send(self, status: int, ctype: str, payload: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _static(self, rel: str) -> None:
        if rel in ("", "/"):
            rel = "/index.html"
        name = rel.lstrip("/").replace("\\", "/")
        if ".." in name.split("/"):
            self._send(403, "text/plain", b"forbidden")
            return
        path = (WEB / name).resolve()
        try:
            path.relative_to(WEB.resolve())
        except ValueError:
            self._send(403, "text/plain", b"forbidden")
            return
        if not path.is_file():
            self._send(404, "text/plain", b"not found")
            return
        suffix = path.suffix.lower()
        types = {
            ".html": "text/html; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".svg": "image/svg+xml",
            ".ico": "image/x-icon",
        }
        data = path.read_bytes()
        self._send(200, types.get(suffix, "application/octet-stream"), data)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            try:
                status, ctype, payload = _handle_api("GET", parsed, b"")
            except GitError as exc:
                status, ctype, payload = _json_bytes({"error": str(exc)}, 400)
            except Exception:
                log.exception("GET failed")
                status, ctype, payload = _json_bytes({"error": "internal"}, 500)
            self._send(status, ctype, payload)
            return
        self._static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or "0")
        body = self.rfile.read(length) if length else b""
        try:
            status, ctype, payload = _handle_api("POST", parsed, body)
        except GitError as exc:
            status, ctype, payload = _json_bytes({"error": str(exc)}, 400)
        except Exception:
            log.exception("POST failed")
            status, ctype, payload = _json_bytes({"error": "internal"}, 500)
        self._send(status, ctype, payload)


def shutdown_async() -> None:
    global _shutting_down
    with _shutdown_lock:
        if _shutting_down:
            return
        _shutting_down = True
    httpd = _httpd
    if httpd is None:
        return

    def _stop():
        try:
            httpd.shutdown()
        except Exception:
            log.exception("shutdown failed")

    threading.Thread(target=_stop, name="shutdown", daemon=True).start()


def serve_forever() -> ThreadingHTTPServer:
    global _httpd, _shutting_down
    _shutting_down = False
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    httpd.allow_reuse_address = True
    _httpd = httpd
    log.info("listening on http://%s:%s/", HOST, PORT)
    httpd.serve_forever()
    return httpd


def start_background() -> ThreadingHTTPServer:
    global _httpd, _shutting_down
    _shutting_down = False
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    httpd.allow_reuse_address = True
    _httpd = httpd
    t = threading.Thread(target=httpd.serve_forever, name="httpd", daemon=True)
    t.start()
    return httpd
