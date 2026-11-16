"""Interactive connection helper.

The tray app re-launches itself with ``--connect-console <tunnel>``. This mode
allocates a console window and runs ``FortiVPN.exe --cli --connect`` inside it,
so FortiClient can ask for password / FortiToken code when needed (or open the
browser for SAML). The window closes by itself when the connection succeeds
and stays open on error so the message can be read.
"""
from __future__ import annotations

import ctypes
import subprocess
import sys
import time

from . import backend


def _attach_console(title: str):
    k32 = ctypes.windll.kernel32
    k32.AllocConsole()
    k32.SetConsoleTitleW(title)
    # UTF-8 so tunnel names with accents render correctly
    k32.SetConsoleOutputCP(65001)
    k32.SetConsoleCP(65001)
    conout = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)
    conin = open("CONIN$", "r", encoding="utf-8", errors="replace")
    sys.stdout = sys.stderr = conout
    sys.stdin = conin
    return conin, conout


def run(tunnel: str) -> int:
    conin, conout = _attach_console(f"Connessione VPN - {tunnel}")
    print(f"  FortiClient VPN Manager\n  Connessione al tunnel: {tunnel}\n")
    print("  Se richiesto, inserisci password / codice FortiToken qui sotto.\n")
    print("-" * 60)
    try:
        rc = subprocess.call(backend.connect_command(tunnel), stdin=conin, stdout=conout, stderr=conout)
    except OSError as exc:
        print(f"\nImpossibile avviare FortiVPN.exe: {exc}")
        rc = -1
    print("-" * 60)

    # The CLI exit code is not always meaningful: double-check the real state.
    status = backend.STATUS_UNKNOWN
    for _ in range(10):
        status = backend.load_status().get(tunnel, backend.STATUS_UNKNOWN)
        if status != backend.STATUS_CONNECTING:
            break
        time.sleep(1.5)

    if status == backend.STATUS_CONNECTED:
        print(f"\n  Connesso a \"{tunnel}\". Questa finestra si chiude da sola.")
        time.sleep(2.5)
        return 0

    print(f"\n  Connessione non riuscita (codice {rc}, stato: {status}).")
    print("  Premi INVIO per chiudere...")
    try:
        input()
    except EOFError:
        pass
    return 1
