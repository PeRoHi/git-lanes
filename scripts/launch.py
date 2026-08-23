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
    candidates = [
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "Microsoft"
        / "Edge"
        / "Application"
        / "msedge.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "Microsoft"
        / "Edge"
        / "Application"
        / "msedge.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "Google"
        / "Chrome"
        / "Application"
        / "chrome.exe",
    ]
    for p in candidates:
        if p.is_file():
            return p
    raise RuntimeError("Edge or Chrome not found")


def clear_profile_cache(profile: Path) -> None:
    for name in ("Cache", "Code Cache", "GPUCache"):
        d = profile / name
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)


def main() -> int:
    _log_setup()
    logging.info("launch start cwd=%s", Path.cwd())
    try:
        reclaim_port(PORT)
        start_background()
        wait_health()
        browser = find_browser()
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
        proc = subprocess.Popen(cmd)
        proc.wait()
        shutdown_async()
        time.sleep(0.4)
        logging.info("browser exited code=%s", proc.returncode)
        return 0
    except Exception as exc:
        error_box(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
