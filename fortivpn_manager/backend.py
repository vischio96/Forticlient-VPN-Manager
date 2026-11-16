"""Access to FortiClient 7.4 VPN tunnels.

* Tunnel list  -> registry  HKLM\\SOFTWARE\\Fortinet\\FortiClient\\{Sslvpn,IPSec}\\Tunnels
* Status       -> FortiVPN.exe --cli --status
* Connect      -> FortiVPN.exe --cli --connect --tunnel <name>   (run in a console, see connect_console)
* Disconnect   -> FortiVPN.exe --cli --disconnect --tunnel <name>

EMS vs Personal: tunnels pushed by EMS/FortiGate are flagged with ``fgt=1``
(SSL: on the tunnel key, IPsec: on its ``P1`` subkey). Tunnels created by the
user in the FortiClient GUI ("Personal VPNs") don't have it.
"""
from __future__ import annotations

import logging
import os
import subprocess
import winreg
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

FC_KEY = r"SOFTWARE\Fortinet\FortiClient"
DEFAULT_DIR = r"C:\Program Files\Fortinet\FortiClient"
CREATE_NO_WINDOW = 0x08000000

PROTO_IPSEC = "IPsec VPN"
PROTO_SSL = "SSL VPN"
ORIGIN_EMS = "EMS"
ORIGIN_PERSONAL = "Personal"

# Placeholder keys FortiClient keeps around that are not real tunnels.
IGNORED_NAMES = {"00000000"}

STATUS_CONNECTED = "connected"
STATUS_CONNECTING = "connecting"
STATUS_DISCONNECTED = "disconnected"
STATUS_UNKNOWN = "unknown"


@dataclass(frozen=True)
class Tunnel:
    name: str
    protocol: str            # PROTO_IPSEC | PROTO_SSL
    origin: str              # ORIGIN_EMS | ORIGIN_PERSONAL
    server: str = ""
    saml: bool = False
    description: str = ""

    @property
    def key(self) -> tuple[str, str]:
        return (self.protocol, self.name)


@dataclass
class Snapshot:
    tunnels: list[Tunnel] = field(default_factory=list)
    error: str = ""


# --------------------------------------------------------------------------- paths

def forticlient_dir() -> Path:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, FC_KEY, 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            val, _ = winreg.QueryValueEx(k, "INSTALLDIR")
            if val and Path(val).is_dir():
                return Path(val)
    except OSError:
        pass
    return Path(DEFAULT_DIR)


def fortivpn_exe() -> Path:
    return forticlient_dir() / "FortiVPN.exe"


def forticlient_gui_exe() -> Path:
    return forticlient_dir() / "FortiClient.exe"


def demo_mode() -> bool:
    return os.environ.get("FVM_DEMO", "") not in ("", "0")


def is_installed() -> bool:
    return demo_mode() or fortivpn_exe().is_file()


# --------------------------------------------------------------------------- registry

def _values(key) -> dict[str, object]:
    out: dict[str, object] = {}
    i = 0
    while True:
        try:
            name, data, _typ = winreg.EnumValue(key, i)
        except OSError:
            break
        out[name] = data
        i += 1
    return out


def _subkeys(key) -> list[str]:
    out, i = [], 0
    while True:
        try:
            out.append(winreg.EnumKey(key, i))
        except OSError:
            break
        i += 1
    return out


def _truthy(v) -> bool:
    return str(v).strip() not in ("", "0", "None")


def _read_branch(branch: str, protocol: str) -> list[Tunnel]:
    path = rf"{FC_KEY}\{branch}\Tunnels"
    tunnels: list[Tunnel] = []
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0,
                              winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
    except OSError:
        return tunnels
    with root:
        for name in _subkeys(root):
            if name in IGNORED_NAMES:
                continue
            try:
                with winreg.OpenKey(root, name) as tk:
                    vals = _values(tk)
                    p1: dict[str, object] = {}
                    if protocol == PROTO_IPSEC:
                        try:
                            with winreg.OpenKey(tk, "P1") as p1k:
                                p1 = _values(p1k)
                        except OSError:
                            pass
            except OSError as exc:
                log.warning("cannot read tunnel %s\\%s: %s", branch, name, exc)
                continue

            managed = (vals if protocol == PROTO_SSL else p1).get("fgt", "")
            ems = _truthy(managed)
            if protocol == PROTO_SSL:
                server = str(vals.get("Server") or "")
                saml = _truthy(vals.get("sso_enabled", ""))
            else:
                server = str(p1.get("RemoteGW") or "")
                saml = _truthy(p1.get("sso_enabled", ""))
            tunnels.append(Tunnel(
                name=name,
                protocol=protocol,
                origin=ORIGIN_EMS if ems else ORIGIN_PERSONAL,
                server=server,
                saml=saml,
                description=str(vals.get("Description") or ""),
            ))
    return tunnels


def load_tunnels() -> Snapshot:
    if demo_mode():
        from . import demo
        return Snapshot(tunnels=demo.tunnels())
    if not is_installed():
        return Snapshot(error="FortiClient non trovato (FortiVPN.exe mancante).")
    try:
        tunnels = _read_branch("IPSec", PROTO_IPSEC) + _read_branch("Sslvpn", PROTO_SSL)
    except Exception as exc:  # pragma: no cover - defensive
        log.exception("registry read failed")
        return Snapshot(error=f"Errore lettura registro: {exc}")
    tunnels.sort(key=lambda t: t.name.casefold())
    return Snapshot(tunnels=tunnels)


# --------------------------------------------------------------------------- CLI

def _run_cli(*args: str, timeout: float = 30) -> subprocess.CompletedProcess:
    cmd = [str(fortivpn_exe()), "--cli", *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          creationflags=CREATE_NO_WINDOW, encoding="utf-8", errors="replace")


def _norm_status(raw: str) -> str:
    s = raw.strip().lower()
    if s.startswith("connected"):
        return STATUS_CONNECTED
    if s.startswith("connecting") or "progress" in s:
        return STATUS_CONNECTING
    if s.startswith("disconnect"):  # Disconnected / Disconnecting
        return STATUS_DISCONNECTED
    return STATUS_UNKNOWN


def load_status() -> dict[str, str]:
    """Return {tunnel name: status}. Empty dict on failure."""
    if demo_mode():
        from . import demo
        return demo.status()
    try:
        res = _run_cli("--status")
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("status failed: %s", exc)
        return {}
    out: dict[str, str] = {}
    for line in res.stdout.splitlines():
        if " :: " not in line:
            continue
        name, st = line.rsplit(" :: ", 1)
        out[name.strip()] = _norm_status(st)
    return out


def disconnect(name: str) -> tuple[bool, str]:
    try:
        res = _run_cli("--disconnect", "--tunnel", name, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    msg = (res.stdout + res.stderr).strip()
    return res.returncode == 0, msg


def connect_command(name: str) -> list[str]:
    return [str(fortivpn_exe()), "--cli", "--connect", "--tunnel", name]


def open_forticlient_gui() -> None:
    exe = forticlient_gui_exe()
    if exe.is_file():
        os.startfile(str(exe))  # noqa: S606 - launching the installed FortiClient GUI
