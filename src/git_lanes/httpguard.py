from __future__ import annotations

import os
import stat
from pathlib import Path
from urllib.parse import unquote, urlsplit

from git_lanes.gitio import GitError
from git_lanes.store import StoreError

# Messages we raise on purpose. Anything else is collapsed for the UI.
SAFE_CLIENT_ERRORS = frozenset(
    {
        "unknown repo",
        "invalid json",
        "path required",
        "roots must be a list",
        "path not found",
        "not a git repository",
        "no git repository found",
        "invalid paging",
        "hash required",
        "repo required",
        "id required",
        "invalid ref",
        "unknown ref",
        "invalid commit hash",
        "commit not found",
        "invalid offset or limit",
        "git executable not found",
        "git timed out",
        "git failed",
        "not signed in to GitHub",
        "gh timed out",
        "gh failed",
        "gh not found",
        "invalid repo name",
        "folder exists and is not a git repository",
        "clone finished but not a git repository",
        "could not start GitHub login",
        "could not read GitHub login code",
        "gh api user returned invalid json",
        "gh repo list returned invalid json",
        "not found",
        "forbidden",
        "invalid host",
        "invalid origin",
        "invalid body",
        "invalid path",
        "store unreadable",
        "request failed",
        "internal",
    }
)

GH_INSTALL_HINT = "GitHub CLI (gh) not found. Install from https://cli.github.com/"

_LOOPBACK_NAMES = frozenset({"127.0.0.1", "localhost", "::1"})


def has_c0_del(text: str) -> bool:
    return any(ord(ch) < 32 or ord(ch) == 127 for ch in text)


def loopback_host_headers(port: int) -> frozenset[str]:
    return frozenset(
        {
            f"127.0.0.1:{port}",
            f"localhost:{port}",
            f"[::1]:{port}",
        }
    )


def normalize_host_header(raw: str, *, expected_port: int) -> str | None:
    if raw is None or has_c0_del(raw):
        return None
    host = raw.strip().lower()
    if not host or "/" in host or "\\" in host:
        return None
    if host.startswith("["):
        end = host.find("]")
        if end < 1:
            return None
        name = host[1:end]
        rest = host[end + 1 :]
        if not rest.startswith(":"):
            if expected_port in (80, 443):
                return f"[{name}]"
            return None
        try:
            port = int(rest[1:])
        except ValueError:
            return None
        if port != expected_port:
            return None
        return f"[{name}]:{port}"
    if ":" not in host:
        if expected_port in (80, 443):
            return host
        return None
    name, _, port_s = host.rpartition(":")
    if not name or not port_s.isdigit():
        return None
    port = int(port_s)
    if port != expected_port:
        return None
    return f"{name}:{port}"


def host_allowed(raw: str, *, expected_port: int) -> bool:
    norm = normalize_host_header(raw, expected_port=expected_port)
    if norm is None:
        return False
    return norm in loopback_host_headers(expected_port)


def origin_allowed(raw: str, *, expected_port: int) -> bool:
    if raw is None or has_c0_del(raw):
        return False
    origin = raw.strip()
    if not origin or origin.lower() == "null":
        return False
    parsed = urlsplit(origin)
    if parsed.scheme != "http":
        return False
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        return False
    if parsed.path not in ("", "/"):
        return False
    host = (parsed.hostname or "").lower()
    if host not in _LOOPBACK_NAMES:
        return False
    if parsed.port != expected_port:
        return False
    return True


def referer_allowed(raw: str, *, expected_port: int) -> bool:
    if raw is None or has_c0_del(raw):
        return False
    referer = raw.strip()
    if not referer:
        return False
    parsed = urlsplit(referer)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return origin_allowed(origin, expected_port=expected_port)


def check_request(headers, *, method: str, expected_port: int) -> tuple[bool, int, str]:
    """Allow only this app's loopback Host/Origin. Origin==Host is not sufficient."""
    host = headers.get("Host") or ""
    if not host_allowed(host, expected_port=expected_port):
        return False, 403, "invalid host"
    origin = headers.get("Origin")
    if origin:
        if not origin_allowed(origin, expected_port=expected_port):
            return False, 403, "invalid origin"
        return True, 200, ""
    if method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
        referer = headers.get("Referer")
        if referer and not referer_allowed(referer, expected_port=expected_port):
            return False, 403, "invalid origin"
    return True, 200, ""


def client_error_message(exc: BaseException) -> str:
    if isinstance(exc, (GitError, StoreError)):
        msg = str(exc).strip()
        if msg in SAFE_CLIENT_ERRORS:
            return msg
        if msg.startswith("GitHub CLI (gh) not found"):
            return GH_INSTALL_HINT
        return "request failed"
    return "internal"


def nested_unquote(raw: str, *, max_rounds: int = 5) -> str | None:
    if raw is None or has_c0_del(raw):
        return None
    prev = raw
    for _ in range(max_rounds):
        cur = unquote(prev)
        if has_c0_del(cur):
            return None
        if cur == prev:
            return cur
        prev = cur
    nxt = unquote(prev)
    if has_c0_del(nxt):
        return None
    if nxt != prev:
        return None
    return prev


def read_nofollow_file(path: Path) -> bytes | None:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(str(path), flags)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return None
        chunks: list[bytes] = []
        remaining = st.st_size
        while remaining > 0:
            chunk = os.read(fd, min(remaining, 64 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)
    except OSError:
        return None
    finally:
        os.close(fd)


def resolve_web_file(web_root: Path, url_path: str) -> Path | None:
    """Jail static paths. Decode (bounded) before '..' checks; refuse symlinks."""
    decoded = nested_unquote(url_path)
    if decoded is None:
        return None
    decoded = decoded.replace("\\", "/")
    if decoded in ("", "/"):
        decoded = "/index.html"
    parts: list[str] = []
    for part in decoded.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            return None
        if "/" in part or "\\" in part or "\x00" in part:
            return None
        if len(part) >= 2 and part[1] == ":":
            return None
        parts.append(part)
    try:
        root = web_root.resolve()
    except OSError:
        return None
    cur = root
    for part in parts:
        nxt = cur / part
        try:
            if nxt.is_symlink():
                return None
        except OSError:
            return None
        cur = nxt
    try:
        if cur.is_symlink() or not cur.is_file():
            return None
        resolved = cur.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None
    return cur
