"""Window-less tunnel connection.

``FortiVPN.exe --cli --connect`` runs inside a hidden pseudo console. Whenever
the CLI stops on a prompt (``Password:``, ``FortiToken Code:``, username …) the
``prompt`` signal asks the GUI thread for an answer, which is typed back into
the pseudo console. Cancelling a prompt aborts the connection.
"""
from __future__ import annotations

import logging
import threading
import time

from PySide6.QtCore import QObject, Signal

from . import backend
from .conpty import PtyProcess, strip_vt

log = logging.getLogger(__name__)

PROMPT_IDLE = 0.5        # seconds of silence after "...:" before we treat it as a prompt
CONNECT_TIMEOUT = 180    # give up waiting for the CLI after this many seconds

KIND_PASSWORD = "password"
KIND_TOKEN = "token"
KIND_TEXT = "text"


def classify_prompt(text: str) -> str:
    t = text.lower()
    if "password" in t or "passwd" in t:
        return KIND_PASSWORD
    if "token" in t or "code" in t or "otp" in t or "passcode" in t:
        return KIND_TOKEN
    return KIND_TEXT


class Connection(QObject):
    # tunnel, kind, prompt text  -> GUI must call answer()
    prompt = Signal(str, str, str)
    # tunnel, ok, message, full CLI output
    finished = Signal(str, bool, str, str)

    def __init__(self, tunnel: str):
        super().__init__()
        self.tunnel = tunnel
        self._buf = ""
        self._last_out = time.monotonic()
        self._lock = threading.Lock()
        self._answer_evt = threading.Event()
        self._answer: str | None = None
        self.cancelled = False

    # called from the GUI thread
    def answer(self, value: str | None) -> None:
        self._answer = value
        self._answer_evt.set()

    def start(self) -> None:
        threading.Thread(target=self._run, name=f"connect-{self.tunnel}", daemon=True).start()

    # ---------------------------------------------------------------- worker
    def _on_output(self, chunk: str) -> None:
        with self._lock:
            self._buf += strip_vt(chunk)
            self._last_out = time.monotonic()

    def _run(self) -> None:
        log.info("connecting %s (hidden console)", self.tunnel)
        try:
            proc = PtyProcess(backend.connect_command(self.tunnel), on_output=self._on_output)
        except OSError as exc:
            log.exception("cannot start CLI")
            self.finished.emit(self.tunnel, False, f"Impossibile avviare FortiVPN.exe:\n{exc}", "")
            return

        answered_at = 0          # buffer length at the last answered prompt
        start = time.monotonic()
        rc = None
        try:
            while True:
                rc = proc.wait(0.2)
                if rc is not None:
                    break
                if time.monotonic() - start > CONNECT_TIMEOUT:
                    break
                with self._lock:
                    buf, idle = self._buf, time.monotonic() - self._last_out
                if len(buf) <= answered_at or idle < PROMPT_IDLE:
                    continue
                tail = buf[answered_at:].rstrip("\n").split("\n")[-1].strip()
                if not tail.endswith(":"):
                    continue
                kind = classify_prompt(tail)
                log.info("CLI prompt (%s): %s", kind, tail)
                self._answer_evt.clear()
                self.prompt.emit(self.tunnel, kind, tail)
                self._answer_evt.wait()
                answered_at = len(buf)
                if self._answer is None:
                    self.cancelled = True
                    proc.terminate()
                    rc = proc.wait(5)
                    break
                proc.write(self._answer + "\r")
                self._answer = None
        finally:
            output = self._buf.strip()
            still_running = rc is None and not self.cancelled

        if self.cancelled:
            proc.close()
            self.finished.emit(self.tunnel, False, "Connessione annullata.", output)
            return

        # The CLI exit code is not always meaningful: double-check the real state.
        status = backend.STATUS_UNKNOWN
        for _ in range(10):
            status = backend.load_status().get(self.tunnel, backend.STATUS_UNKNOWN)
            if status != backend.STATUS_CONNECTING:
                break
            time.sleep(1.5)
        ok = status == backend.STATUS_CONNECTED
        log.info("connect %s finished rc=%s status=%s", self.tunnel, rc, status)

        if still_running and not ok:
            proc.terminate()
            proc.wait(5)
        if still_running and ok:
            # CLI keeps running while the tunnel is up: leave it alone, clean up when it exits
            self.finished.emit(self.tunnel, True, "", output)
            proc.wait()
            proc.close()
            return
        proc.close()
        if ok:
            self.finished.emit(self.tunnel, True, "", output)
        else:
            msg = _last_error(output) or f"Connessione non riuscita (codice {rc}, stato: {status})."
            self.finished.emit(self.tunnel, False, msg, output)


def _last_error(output: str) -> str:
    lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
    for ln in reversed(lines):
        if any(w in ln.lower() for w in ("error", "fail", "denied", "invalid", "unable", "not ")):
            return ln
    return lines[-1] if lines else ""
