from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlsplit

from git_lanes.gitio import GitError

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
        "request failed",
        "internal",
    }
)

GH_INSTALL_HINT = "GitHub CLI (gh) not found. Install from https://cli.github.com/"

_LOOPBACK_NAMES = frozenset({"127.0.0.1", "localhost", "::1"})


def loopback_host_headers(port: int) -> frozenset[str]:
    return frozenset(
        {
            f"127.0.0.1:{port}",
            f"localhost:{port}",
            f"[::1]:{port}",
        }
    )


def normalize_host_header(raw: str, *, expected_port: int) -> str | None:
    host = (raw or "").strip().lower()
    if not host or "/" in host or "\\" in host or "\x00" in host:
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
    origin = (raw or "").strip()
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
    referer = (raw or "").strip()
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
    if isinstance(exc, GitError):
        msg = str(exc).strip()
        if msg in SAFE_CLIENT_ERRORS:
            return msg
        if msg.startswith("GitHub CLI (gh) not found"):
            return GH_INSTALL_HINT
        return "request failed"
    return "internal"


def nested_unquote(raw: str, *, max_rounds: int = 5) -> str | None:
    prev = raw
    for _ in range(max_rounds):
        cur = unquote(prev)
        if cur == prev:
            return cur
        prev = cur
    if unquote(prev) != prev:
        return None
    return prev


def resolve_web_file(web_root: Path, url_path: str) -> Path | None:
    """Jail static paths. Decode (bounded) before '..' checks; refuse symlinks."""
    decoded = nested_unquote(url_path)
    if decoded is None or "\x00" in decoded:
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
    return resolved
