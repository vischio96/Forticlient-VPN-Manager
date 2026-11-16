"""System tray application."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
import winreg
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QStyleFactory, QSystemTrayIcon

from . import __version__, backend, updater
from .connector import Connection
from .dialogs import PromptDialog, SettingsDialog, UpdateDialog
from .backend import STATUS_CONNECTED, STATUS_CONNECTING, Tunnel
from .popup import Popup

APP_ID = "FortiVPNManager"
APP_NAME = "FortiClient VPN Manager"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
CREATE_NEW_CONSOLE = 0x00000010

log = logging.getLogger("fortivpn_manager")


# --------------------------------------------------------------------------- helpers

def data_dir() -> Path:
    d = Path(os.environ.get("LOCALAPPDATA", Path.home())) / APP_ID
    d.mkdir(parents=True, exist_ok=True)
    return d


def setup_logging() -> None:
    h = RotatingFileHandler(data_dir() / "app.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.DEBUG if os.environ.get("FVM_DEBUG") else logging.INFO, handlers=[h])


def asset(name: str) -> str:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return str(base / "assets" / name)


def self_command() -> list[str]:
    """Command line that starts this application (frozen exe or from source)."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    main = Path(__file__).resolve().parent.parent / "main.py"
    return [sys.executable, str(main)]


def autostart_command() -> str:
    cmd = self_command()
    if not getattr(sys, "frozen", False):
        pyw = Path(sys.executable).with_name("pythonw.exe")
        if pyw.exists():
            cmd[0] = str(pyw)
    return subprocess.list2cmdline(cmd)


def autostart_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_ID)
            return True
    except OSError:
        return False


def set_autostart(enabled: bool) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if enabled:
            winreg.SetValueEx(k, APP_ID, 0, winreg.REG_SZ, autostart_command())
        else:
            try:
                winreg.DeleteValue(k, APP_ID)
            except FileNotFoundError:
                pass


# --------------------------------------------------------------------------- background work

class Poller(QObject):
    """Runs registry / CLI reads on worker threads, results come back as signals."""
    tunnelsLoaded = Signal(object)   # backend.Snapshot
    statusLoaded = Signal(object)    # dict[name, status]

    def __init__(self):
        super().__init__()
        self._busy = {"tunnels": False, "status": False}
        self._lock = threading.Lock()

    def _spawn(self, kind: str, fn, signal):
        with self._lock:
            if self._busy[kind]:
                return
            self._busy[kind] = True

        def work():
            try:
                signal.emit(fn())
            except Exception:  # pragma: no cover
                log.exception("%s refresh failed", kind)
            finally:
                with self._lock:
                    self._busy[kind] = False

        threading.Thread(target=work, name=f"poll-{kind}", daemon=True).start()

    def refresh_tunnels(self):
        self._spawn("tunnels", backend.load_tunnels, self.tunnelsLoaded)

    def refresh_status(self):
        self._spawn("status", backend.load_status, self.statusLoaded)


class Worker(QObject):
    done = Signal(str, bool, str)  # tunnel, ok, message

    def disconnect_tunnel(self, t: Tunnel):
        def work():
            ok, msg = backend.disconnect(t.name)
            self.done.emit(t.name, ok, msg)
        threading.Thread(target=work, daemon=True).start()


class UpdateChecker(QObject):
    result = Signal(object, str, bool)   # UpdateInfo | None, error, manual

    def check(self, manual: bool = False):
        def work():
            try:
                self.result.emit(updater.check(), "", manual)
            except Exception as exc:  # network errors, rate limit, no release yet ...
                log.info("update check failed: %s", exc)
                self.result.emit(None, str(exc), manual)
        threading.Thread(target=work, name="update-check", daemon=True).start()


# --------------------------------------------------------------------------- app

class TrayApp(QObject):
    _download_progress = Signal(int, int)
    _download_done = Signal(object, str)   # Path | None, error

    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        self.qs = QSettings(APP_ID, APP_ID)
        self.settings = {
            "group_mode": self.qs.value("group_mode", "protocol"),
            "hidden_filters": self._json("hidden_filters", []),
            "collapsed": self._json("collapsed", []),
        }
        self.refresh_secs = int(self.qs.value("refresh_secs", 30))
        self.notify = self._bool("notify", False)            # pop-up notifications: off by default
        self.update_check = self._bool("update_check", True)
        self.show_console = self._bool("show_console", False)

        self.tunnels: list[Tunnel] = []
        self.status: dict[str, str] = {}
        self._first_load = True
        self._fast_until = 0.0
        self._connections: dict[str, Connection] = {}
        self.update_info: updater.UpdateInfo | None = None
        self._update_dialog: UpdateDialog | None = None

        self.icon_on = QIcon(asset("tray_on.png"))
        self.icon_off = QIcon(asset("tray_off.png"))
        app.setWindowIcon(QIcon(asset("icon.ico")))

        self.popup = Popup(self.settings)
        self.popup.connectRequested.connect(self.connect_tunnel)
        self.popup.disconnectRequested.connect(self.disconnect_tunnel)
        self.popup.refreshRequested.connect(self.refresh_all)
        self.popup.settingsMenuRequested.connect(lambda pos: self._build_menu(compact=True).exec(pos))
        self.popup.settingChanged.connect(self._save_setting)
        self.popup.updateRequested.connect(self.offer_update)

        self.tray = QSystemTrayIcon(self.icon_off)
        self.tray.setToolTip(APP_NAME)
        self.tray.activated.connect(self._tray_activated)
        self.tray.setContextMenu(self._build_menu())
        self.tray.show()

        self.poller = Poller()
        self.poller.tunnelsLoaded.connect(self._on_tunnels)
        self.poller.statusLoaded.connect(self._on_status)
        self.worker = Worker()
        self.worker.done.connect(self._on_disconnect_done)
        self.checker = UpdateChecker()
        self.checker.result.connect(self._on_update_result)
        self._download_progress.connect(self._on_download_progress)
        self._download_done.connect(self._on_download_done)

        self.t_tunnels = QTimer(self, timeout=self.poller.refresh_tunnels)
        self.t_tunnels.start(self.refresh_secs * 1000)
        self.t_status = QTimer(self, timeout=self._status_tick)
        self.t_status.start(3000)
        self._last_status = 0.0
        # update check: shortly after start, then every 6 hours
        self.t_update = QTimer(self, timeout=self._auto_update_check)
        self.t_update.start(6 * 3600 * 1000)
        QTimer.singleShot(15_000, self._auto_update_check)

        self.refresh_all()

    # ------------------------------------------------------------------ settings
    def _json(self, key, default):
        try:
            return json.loads(self.qs.value(key, json.dumps(default)))
        except (TypeError, ValueError):
            return default

    def _bool(self, key: str, default: bool) -> bool:
        return str(self.qs.value(key, "true" if default else "false")).lower() == "true"

    def _save_setting(self, key: str, value):
        if isinstance(value, bool):
            value = "true" if value else "false"
        self.qs.setValue(key, json.dumps(value) if isinstance(value, (list, dict)) else value)

    def open_settings(self):
        self.popup.hide()
        dlg = SettingsDialog({
            "autostart": autostart_enabled(), "notify": self.notify, "refresh_secs": self.refresh_secs,
            "update_check": self.update_check, "show_console": self.show_console,
        })
        if dlg.exec() != SettingsDialog.Accepted:
            return
        v = dlg.values()
        if v["autostart"] != autostart_enabled():
            try:
                set_autostart(v["autostart"])
            except OSError as exc:
                QMessageBox.warning(None, APP_NAME, f"Impossibile modificare l'avvio automatico:\n{exc}")
        self.notify = v["notify"]
        self.update_check = v["update_check"]
        self.show_console = v["show_console"]
        if v["refresh_secs"] != self.refresh_secs:
            self.refresh_secs = v["refresh_secs"]
            self.t_tunnels.start(self.refresh_secs * 1000)
        for k in ("notify", "update_check", "show_console", "refresh_secs"):
            self._save_setting(k, v[k])
        log.info("settings saved: %s", v)

    # ------------------------------------------------------------------ menus
    def _build_menu(self, compact: bool = False) -> QMenu:
        m = QMenu()
        self._populate_menu(m, compact)
        if not compact:
            # rebuilt on every open so dynamic entries reflect the current state
            m.aboutToShow.connect(lambda: (m.clear(), self._populate_menu(m, False)))
        return m

    def _populate_menu(self, m: QMenu, compact: bool) -> None:
        if self.update_info:
            m.addAction(f"⬆  Aggiorna alla versione {self.update_info.version}…", self.offer_update)
            m.addSeparator()
        if not compact:
            m.addAction("Apri elenco tunnel", lambda: self.popup.show_near_tray(self._tray_anchor()))
            m.addAction("Aggiorna ora", self.refresh_all)
            m.addSeparator()
            connected = [n for n, s in self.status.items() if s in (STATUS_CONNECTED, STATUS_CONNECTING)]
            for n in connected:
                t = next((x for x in self.tunnels if x.name == n), Tunnel(n, "", ""))
                m.addAction(f"Disconnetti “{n}”", lambda t=t: self.disconnect_tunnel(t))
            if connected:
                m.addSeparator()
        m.addAction("Impostazioni…", self.open_settings)
        m.addAction("Controlla aggiornamenti", lambda: self.checker.check(manual=True))
        m.addSeparator()
        m.addAction("Apri FortiClient", backend.open_forticlient_gui)
        m.addAction("Apri cartella log", lambda: os.startfile(str(data_dir())))
        m.addAction(f"Informazioni (v{__version__})", self._about)
        m.addSeparator()
        m.addAction("Esci", self.quit)

    def _about(self):
        QMessageBox.about(
            None, APP_NAME,
            f"<b>{APP_NAME}</b> v{__version__}<br><br>"
            "Elenco e avvio rapido dei tunnel IPsec / SSL VPN di FortiClient.<br><br>"
            f'<a href="https://github.com/{updater.REPO}">github.com/{updater.REPO}</a><br><br>'
            f"FortiClient: {backend.forticlient_dir()}<br>"
            f"Log: {data_dir()}")

    # ------------------------------------------------------------------ tray
    def _tray_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.popup.toggle(self._tray_anchor())

    def _tray_anchor(self):
        g = self.tray.geometry()
        return g.center() if g.isValid() and not g.isEmpty() else None

    def message(self, title: str, text: str, icon=QSystemTrayIcon.Information):
        if self.notify:
            self.tray.showMessage(title, text, icon, 5000)

    def _update_tooltip(self):
        connected = [n for n, s in self.status.items() if s == STATUS_CONNECTED]
        tip = APP_NAME + ("\nConnesso: " + ", ".join(connected) if connected else "\nNessun tunnel connesso")
        if self.update_info:
            tip += f"\nAggiornamento disponibile: {self.update_info.version}"
        self.tray.setToolTip(tip[:127])

    # ------------------------------------------------------------------ refresh
    def refresh_all(self):
        self.poller.refresh_tunnels()
        self._last_status = time.monotonic()
        self.poller.refresh_status()

    def _status_tick(self):
        now = time.monotonic()
        if now < self._fast_until:
            interval = 3
        elif self.popup.isVisible():
            interval = 8
        else:
            interval = 30
        if now - self._last_status >= interval:
            self._last_status = now
            self.poller.refresh_status()

    def _on_tunnels(self, snap: backend.Snapshot):
        if snap.error:
            log.warning(snap.error)
        old = {t.key for t in self.tunnels}
        new = {t.key for t in snap.tunnels}
        if not self._first_load and old != new and not snap.error:
            added = sorted(n for _, n in new - old)
            removed = sorted(n for _, n in old - new)
            log.info("tunnel list changed: +%s -%s", added, removed)
            parts = []
            if added:
                parts.append(f"Aggiunti ({len(added)}): " + ", ".join(added[:4]) + ("…" if len(added) > 4 else ""))
            if removed:
                parts.append(f"Rimossi ({len(removed)}): " + ", ".join(removed[:4]) + ("…" if len(removed) > 4 else ""))
            self.message("Elenco VPN aggiornato", "\n".join(parts))
        if self._first_load:
            log.info("loaded %d tunnels", len(snap.tunnels))
        self._first_load = False
        self.tunnels = snap.tunnels
        self.popup.set_tunnels(snap.tunnels, snap.error)

    def _on_status(self, status: dict[str, str]):
        if not status and self.status:
            return  # transient CLI failure: keep last known state
        before = self.status
        for name, st in status.items():
            was = before.get(name)
            if before and st == STATUS_CONNECTED and was != STATUS_CONNECTED:
                self.message("VPN connessa", f"Connesso a “{name}”")
            elif was == STATUS_CONNECTED and st != STATUS_CONNECTED:
                self.message("VPN disconnessa", f"“{name}” disconnesso")
        # keep "connecting" marks while a connection attempt is still running
        for name in self._connections:
            if status.get(name) != STATUS_CONNECTED:
                status[name] = STATUS_CONNECTING
        if self.show_console and time.monotonic() < self._fast_until:
            for name, st in before.items():
                if st == STATUS_CONNECTING and status.get(name) != STATUS_CONNECTED:
                    status[name] = STATUS_CONNECTING
        self.status = status
        connected = [n for n, s in status.items() if s == STATUS_CONNECTED]
        self.tray.setIcon(self.icon_on if connected else self.icon_off)
        self._update_tooltip()
        self.popup.set_status(status)

    def _mark(self, name: str, st: str | None):
        s = dict(self.status)
        if st is None:
            s.pop(name, None)
        else:
            s[name] = st
        self.status = s
        self.popup.set_status(s)

    # ------------------------------------------------------------------ connect / disconnect
    def connect_tunnel(self, t: Tunnel):
        if t.name in self._connections:
            return
        log.info("connect %s (%s)", t.name, t.protocol)
        self.popup.hide()
        self._fast_until = time.monotonic() + 120
        if self.show_console:
            cmd = self_command() + ["--connect-console", t.name]
            try:
                subprocess.Popen(cmd, creationflags=CREATE_NEW_CONSOLE, close_fds=True)
            except OSError as exc:
                QMessageBox.critical(None, APP_NAME, f"Impossibile avviare la connessione:\n{exc}")
                return
            self._mark(t.name, STATUS_CONNECTING)
            return

        conn = Connection(t.name)
        conn.prompt.connect(self._on_prompt)
        conn.finished.connect(self._on_connect_finished)
        self._connections[t.name] = conn
        self._mark(t.name, STATUS_CONNECTING)
        conn.start()

    def _on_prompt(self, tunnel: str, kind: str, text: str):
        conn = self._connections.get(tunnel)
        if conn is None:
            return
        dlg = PromptDialog(tunnel, kind, text)
        ok = dlg.exec() == PromptDialog.Accepted
        conn.answer(dlg.value() if ok else None)

    def _on_connect_finished(self, tunnel: str, ok: bool, message: str, output: str):
        conn = self._connections.pop(tunnel, None)
        self._last_status = 0
        self.poller.refresh_status()
        if ok:
            self._mark(tunnel, STATUS_CONNECTED)
            return
        self._mark(tunnel, None)
        if conn is not None and conn.cancelled:
            return
        box = QMessageBox(QMessageBox.Warning, APP_NAME, f"Connessione a “{tunnel}” non riuscita.")
        box.setInformativeText(message)
        if output:
            box.setDetailedText(output)
        box.setWindowFlag(Qt.WindowStaysOnTopHint)
        box.exec()

    def disconnect_tunnel(self, t: Tunnel):
        log.info("disconnect %s", t.name)
        self.worker.disconnect_tunnel(t)
        self._fast_until = time.monotonic() + 30

    def _on_disconnect_done(self, name: str, ok: bool, msg: str):
        if not ok:
            log.warning("disconnect %s failed: %s", name, msg)
            QMessageBox.warning(None, APP_NAME, f"Disconnessione di “{name}” non riuscita.\n\n{msg}")
        self._last_status = 0
        self.poller.refresh_status()

    # ------------------------------------------------------------------ updates
    def _auto_update_check(self):
        if self.update_check:
            self.checker.check(manual=False)

    def _on_update_result(self, info, error: str, manual: bool):
        if info is not None:
            first = self.update_info is None or self.update_info.version != info.version
            self.update_info = info
            self.popup.set_update(info.version)
            self._update_tooltip()
            if first:
                self.message("Aggiornamento disponibile",
                             f"È disponibile la versione {info.version}. Apri il menu per aggiornare.")
            if manual:
                self.offer_update()
            return
        if manual:
            if error:
                QMessageBox.warning(None, APP_NAME, f"Impossibile verificare gli aggiornamenti:\n{error}")
            else:
                QMessageBox.information(None, APP_NAME, f"Stai usando l'ultima versione ({__version__}).")

    def offer_update(self):
        info = self.update_info
        if info is None or self._update_dialog is not None:
            return
        self.popup.hide()
        can_install = updater.is_installed_copy() and bool(info.setup_url)
        dlg = UpdateDialog(__version__, info, can_install)
        self._update_dialog = dlg
        if dlg.exec() != UpdateDialog.Accepted:
            self._update_dialog = None
            return
        if not can_install:
            updater.open_page(info.page_url)
            self._update_dialog = None
            return
        # download in background while the dialog shows progress
        dlg.progress.show()
        dlg.btn_ok.setEnabled(False)
        dlg.setModal(False)
        dlg.show()

        def work():
            try:
                path = updater.download(info.setup_url, lambda d, t: self._download_progress.emit(d, t))
                self._download_done.emit(path, "")
            except Exception as exc:
                self._download_done.emit(None, str(exc))
        threading.Thread(target=work, name="update-download", daemon=True).start()

    def _on_download_progress(self, done: int, total: int):
        if self._update_dialog is not None:
            p = self._update_dialog.progress
            p.setMaximum(max(total, 1))
            p.setValue(done if total else 0)

    def _on_download_done(self, path, error: str):
        if self._update_dialog is not None:
            self._update_dialog.close()
            self._update_dialog = None
        if path is None:
            QMessageBox.warning(None, APP_NAME, f"Download dell'aggiornamento non riuscito:\n{error}")
            return
        log.info("starting installer %s", path)
        try:
            updater.run_installer(path)
        except OSError as exc:
            QMessageBox.warning(None, APP_NAME, f"Impossibile avviare l'installazione:\n{exc}")
            return
        self.quit()

    def quit(self):
        for conn in list(self._connections.values()):
            conn.answer(None)
        self.tray.hide()
        self.app.quit()


# --------------------------------------------------------------------------- entry

def _single_instance(app: QApplication) -> QLocalServer | None:
    name = f"{APP_ID}-{os.environ.get('USERNAME', 'user')}"
    sock = QLocalSocket()
    sock.connectToServer(name)
    if sock.waitForConnected(300):
        try:  # let the running instance bring its window to the foreground
            import ctypes
            ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY
        except Exception:
            pass
        sock.write(b"show")
        sock.flush()
        sock.waitForBytesWritten(300)
        return None
    QLocalServer.removeServer(name)
    server = QLocalServer(app)
    server.listen(name)
    return server


def run() -> int:
    setup_logging()
    log.info("starting %s v%s", APP_NAME, __version__)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    if "windows11" in [k.lower() for k in QStyleFactory.keys()]:
        app.setStyle("windows11")

    server = _single_instance(app)
    if server is None:
        return 0
    # named mutex: lets the installer detect that the app is running
    import ctypes
    _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "FortiVPNManagerMutex")  # noqa: F841

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, APP_NAME, "System tray non disponibile.")
        return 1

    tray = TrayApp(app)

    def on_new_connection():
        c = server.nextPendingConnection()
        log.debug("second instance signalled (conn=%s)", c is not None)
        if c is not None:
            c.waitForReadyRead(200)
            tray.popup.show_near_tray()
    server.newConnection.connect(on_new_connection)

    if not backend.is_installed():
        tray.message("FortiClient non trovato", f"FortiVPN.exe non presente in {backend.forticlient_dir()}",
                     QSystemTrayIcon.Warning)
    return app.exec()
