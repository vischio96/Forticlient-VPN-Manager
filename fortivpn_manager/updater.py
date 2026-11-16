"""Update check against GitHub releases."""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
import winreg
from dataclasses import dataclass
from pathlib import Path

from . import __version__

log = logging.getLogger(__name__)

REPO = "vischio96/Forticlient-VPN-Manager"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
INSTALL_KEY = r"Software\FortiVPNManager"   # written by the installer (value: InstallDir)


@dataclass
class UpdateInfo:
    version: str
    page_url: str
    setup_url: str = ""
    setup_name: str = ""
    notes: str = ""


def parse_version(v: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", v.split("-")[0])
    return tuple(int(n) for n in nums[:4]) or (0,)


def is_newer(remote: str, local: str = __version__) -> bool:
    return parse_version(remote) > parse_version(local)


def check(timeout: float = 15) -> UpdateInfo | None:
    """Return UpdateInfo if a newer release exists, None if up to date. Raises on network errors."""
    req = urllib.request.Request(API_LATEST, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"FortiVPNManager/{__version__}",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - fixed https URL
        data = json.load(r)
    tag = data.get("tag_name", "")
    if not tag or data.get("draft") or data.get("prerelease"):
        return None
    if not is_newer(tag):
        log.info("up to date (%s, latest %s)", __version__, tag)
        return None
    info = UpdateInfo(version=tag.lstrip("vV"), page_url=data.get("html_url", RELEASES_PAGE),
                      notes=data.get("body") or "")
    for a in data.get("assets", []):
        name = a.get("name", "")
        if name.lower().endswith(".exe") and "setup" in name.lower():
            info.setup_url = a.get("browser_download_url", "")
            info.setup_name = name
    log.info("update available: %s", info.version)
    return info


def installed_dir() -> Path | None:
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, INSTALL_KEY) as k:
                val, _ = winreg.QueryValueEx(k, "InstallDir")
                return Path(val)
        except OSError:
            continue
    return None


def is_installed_copy() -> bool:
    """True when running the copy deployed by the setup (can self-update)."""
    if not getattr(sys, "frozen", False):
        return False
    d = installed_dir()
    try:
        return d is not None and Path(sys.executable).resolve().parent == d.resolve()
    except OSError:
        return False


def download(url: str, progress=None, timeout: float = 60) -> Path:
    req = urllib.request.Request(url, headers={"User-Agent": f"FortiVPNManager/{__version__}"})
    dest = Path(tempfile.gettempdir()) / "FortiVPNManager-update" / Path(url).name
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, "wb") as f:  # noqa: S310
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while chunk := r.read(256 * 1024):
            f.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    return dest


def run_installer(setup: Path) -> None:
    """Start the setup silently; it waits for this app to quit, updates and relaunches it."""
    subprocess.Popen([str(setup), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
                     close_fds=True, creationflags=0x00000008)  # DETACHED_PROCESS


def open_page(url: str) -> None:
    os.startfile(url)  # noqa: S606
