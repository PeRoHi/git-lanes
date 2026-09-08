from __future__ import annotations

import ctypes
import logging
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from git_lanes import HOST, PORT
from git_lanes.gitio import GitError, git_exe
from git_lanes.server import shutdown_async, start_background

LOG_DIR = ROOT / "logs"
PROFILE = Path(os.environ.get("LOCALAPPDATA") or ROOT / "user-data") / "git-lanes" / "edge-profile"


def _log_setup() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(LOG_DIR / "launch.log"),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(logging.INFO)
    logging.getLogger().addHandler(console)


def error_box(msg: str) -> None:
    logging.error(msg)
    if os.name == "nt":
        ctypes.windll.user32.MessageBoxW(0, msg, "Git Lanes", 0x10)


def ensure_python() -> None:
    if sys.version_info < (3, 10):
        raise RuntimeError("Python 3.10 or newer is required")


def ensure_git() -> None:
    exe = git_exe()
    git_dir = str(Path(exe).parent)
    path = os.environ.get("PATH", "")
    parts = path.split(os.pathsep)
    if git_dir and git_dir not in parts:
        os.environ["PATH"] = git_dir + os.pathsep + path
    logging.info("git=%s", exe)


def reclaim_port(port: int) -> None:
    if os.name != "nt":
        return
    try:
        out = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            creationflags=0x08000000,
        ).stdout
    except OSError:
        return
    pids = set()
    needle = f":{port}"
    for line in out.splitlines():
        if "LISTENING" not in line or needle not in line:
            continue
        parts = line.split()
        if not parts:
            continue
        pid = parts[-1]
        if pid.isdigit() and int(pid) != os.getpid():
            pids.add(pid)
    for pid in pids:
        subprocess.run(
            ["taskkill", "/PID", pid, "/F"],
            capture_output=True,
            shell=False,
            creationflags=0x08000000,
        )
        logging.info("reclaimed pid %s on port %s", pid, port)
    deadline = time.time() + 8
    while time.time() < deadline and pids:
        time.sleep(0.2)
        try:
            urllib.request.urlopen(
                f"http://{HOST}:{port}/api/health", timeout=0.3
            )
        except OSError:
            return


def wait_health(timeout: float = 20) -> None:
    url = f"http://{HOST}:{PORT}/api/health"
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                if resp.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = str(exc)
        time.sleep(0.15)
    raise RuntimeError(f"health check failed: {last}")


def find_browser() -> Path:
    env_paths = []
    for key in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        val = os.environ.get(key)
        if val:
            env_paths.append(Path(val))
    edge_rel = (
        Path("Microsoft") / "Edge" / "Application" / "msedge.exe",
        Path("Microsoft") / "WindowsApps" / "msedge.exe",
    )
    chrome_rel = (Path("Google") / "Chrome" / "Application" / "chrome.exe",)
    candidates: list[Path] = []
    for base in env_paths:
        for rel in edge_rel:
            candidates.append(base / rel)
    found = shutil.which("msedge")
    if found:
        candidates.append(Path(found))
    for base in env_paths:
        for rel in chrome_rel:
            candidates.append(base / rel)
    found = shutil.which("chrome")
    if found:
        candidates.append(Path(found))
    seen: set[str] = set()
    for path in candidates:
        try:
            key = str(path.resolve()) if path.exists() else str(path)
        except OSError:
            key = str(path)
        if key.casefold() in seen:
            continue
        seen.add(key.casefold())
        if path.is_file():
            return path
    raise RuntimeError("Edge or Chrome not found. Install Microsoft Edge and retry.")


def clear_profile_cache(profile: Path) -> None:
    for name in ("Cache", "Code Cache", "GPUCache"):
        d = profile / name
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
    for name in ("Favicons", "Favicons-journal"):
        p = profile / name
        try:
            if p.is_file():
                p.unlink()
        except OSError:
            pass


PROFILE_MARKER = "git-lanes\\edge-profile"
CREATE_NO_WINDOW = 0x08000000


def _profile_pids() -> list[int]:
    if os.name != "nt":
        return []
    script = (
        "$m='" + PROFILE_MARKER.replace("'", "''") + "'; "
        "Get-CimInstance Win32_Process -Filter \"Name = 'msedge.exe' OR Name = 'chrome.exe'\" | "
        "Where-Object { $_.CommandLine -and $_.CommandLine.Contains($m) } | "
        "ForEach-Object { $_.ProcessId }"
    )
    try:
        out = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            creationflags=CREATE_NO_WINDOW,
            timeout=20,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    pids = []
    for line in out.splitlines():
        line = line.strip()
        if line.isdigit():
            pids.append(int(line))
    return pids


def kill_profile_browsers() -> None:
    for pid in _profile_pids():
        if pid == os.getpid():
            continue
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/F"],
            capture_output=True,
            shell=False,
            creationflags=CREATE_NO_WINDOW,
        )
        logging.info("killed profile browser pid %s", pid)


def wait_app_window(proc: subprocess.Popen) -> None:
    """Wait until the --app= window is gone, not just the launcher process."""
    deadline = time.time() + 12
    saw = False
    while time.time() < deadline:
        if _profile_pids():
            saw = True
            break
        if proc.poll() is not None:
            time.sleep(0.5)
            saw = bool(_profile_pids())
            break
        time.sleep(0.15)
    if not saw:
        raise RuntimeError("browser window closed immediately")
    while True:
        live = _profile_pids()
        launcher_alive = proc.poll() is None
        if not live and not launcher_alive:
            time.sleep(0.5)
            if not _profile_pids() and proc.poll() is not None:
                return
        time.sleep(0.4)


def scan_repos() -> None:
    if os.environ.get("GIT_LANES_NO_SCAN") == "1":
        return
    from git_lanes.discover import scan_and_merge

    result = scan_and_merge()
    logging.info(
        "scan found=%s added=%s visible=%s",
        result.get("found"),
        len(result.get("added") or []),
        len(result.get("repos") or []),
    )


def ensure_desktop_shortcut() -> None:
    if os.name != "nt":
        return
    script = ROOT / "scripts" / "create-shortcut.ps1"
    if not script.is_file():
        return
    subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
        ],
        capture_output=True,
        shell=False,
        creationflags=0x08000000,
        timeout=20,
    )


def main() -> int:
    _log_setup()
    logging.info("launch start cwd=%s python=%s", Path.cwd(), sys.executable)
    try:
        ensure_python()
        ensure_git()
        reclaim_port(PORT)
        start_background()
        wait_health()
        scan_repos()
        try:
            ensure_desktop_shortcut()
        except Exception:
            logging.exception("shortcut skipped")
        browser = find_browser()
        kill_profile_browsers()
        time.sleep(0.4)
        PROFILE.mkdir(parents=True, exist_ok=True)
        clear_profile_cache(PROFILE)
        bust = str(int(time.time()))
        url = f"http://{HOST}:{PORT}/?t={bust}"
        cmd = [
            str(browser),
            f"--app={url}",
            f"--user-data-dir={PROFILE}",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        logging.info("open %s", cmd[:2])
        proc = subprocess.Popen(cmd, shell=False)
        wait_app_window(proc)
        shutdown_async()
        time.sleep(0.4)
        logging.info("browser exited code=%s", proc.returncode)
        return 0
    except GitError as exc:
        error_box(str(exc))
        return 1
    except Exception as exc:
        error_box(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
