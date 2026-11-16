"""Small dialogs: credential prompt, update offer."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QLabel, QLineEdit,
    QProgressBar, QTextBrowser, QVBoxLayout,
)

from .connector import KIND_PASSWORD, KIND_TOKEN

TITLES = {
    KIND_PASSWORD: "Password richiesta",
    KIND_TOKEN: "Codice FortiToken richiesto",
}


class PromptDialog(QDialog):
    """Asks the user what the FortiClient CLI is asking for."""

    def __init__(self, tunnel: str, kind: str, prompt: str, parent=None):
        super().__init__(parent, Qt.Dialog | Qt.WindowStaysOnTopHint)
        self.setWindowTitle(f"VPN – {tunnel}")
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        head = QLabel(TITLES.get(kind, "Informazione richiesta"))
        f = head.font()
        f.setBold(True)
        f.setPointSizeF(f.pointSizeF() * 1.15)
        head.setFont(f)
        lay.addWidget(head)

        sub = QLabel(f"Tunnel: <b>{_esc(tunnel)}</b><br>FortiClient chiede: <i>{_esc(prompt)}</i>")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        self.edit = QLineEdit()
        if kind == KIND_PASSWORD:
            self.edit.setEchoMode(QLineEdit.Password)
            self.edit.setPlaceholderText("Password")
        elif kind == KIND_TOKEN:
            self.edit.setPlaceholderText("Codice (es. 123456)")
            self.edit.setFont(QFont("Consolas", self.edit.font().pointSize() + 2))
        lay.addWidget(self.edit)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Invia")
        bb.button(QDialogButtonBox.Cancel).setText("Annulla connessione")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.edit.setFocus()

    def value(self) -> str:
        return self.edit.text()

    def showEvent(self, ev):  # noqa: N802
        super().showEvent(ev)
        self.raise_()
        self.activateWindow()


class UpdateDialog(QDialog):
    def __init__(self, current: str, info, can_install: bool, parent=None):
        super().__init__(parent, Qt.Dialog | Qt.WindowStaysOnTopHint)
        self.setWindowTitle("Aggiornamento disponibile")
        self.setMinimumSize(460, 320)
        lay = QVBoxLayout(self)
        title = QLabel(f"<b>FortiClient VPN Manager {info.version}</b> è disponibile "
                       f"(installata: {current}).")
        title.setWordWrap(True)
        lay.addWidget(title)
        notes = QTextBrowser()
        notes.setOpenExternalLinks(True)
        notes.setMarkdown(info.notes or "_Nessuna nota di rilascio._")
        lay.addWidget(notes, 1)
        self.progress = QProgressBar()
        self.progress.hide()
        lay.addWidget(self.progress)
        bb = QDialogButtonBox()
        if can_install:
            self.btn_ok = bb.addButton("Scarica e installa", QDialogButtonBox.AcceptRole)
        else:
            self.btn_ok = bb.addButton("Apri pagina download", QDialogButtonBox.AcceptRole)
        bb.addButton("Più tardi", QDialogButtonBox.RejectRole)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


class SettingsDialog(QDialog):
    """Application settings."""

    REFRESH_CHOICES = [(10, "10 secondi"), (30, "30 secondi"), (60, "1 minuto"), (300, "5 minuti")]

    def __init__(self, values: dict, parent=None):
        super().__init__(parent, Qt.Dialog | Qt.WindowStaysOnTopHint)
        self.setWindowTitle("Impostazioni – FortiClient VPN Manager")
        self.setMinimumWidth(440)
        lay = QVBoxLayout(self)

        g1 = QGroupBox("Generale")
        f1 = QFormLayout(g1)
        self.autostart = QCheckBox("Avvia con Windows")
        self.autostart.setChecked(values["autostart"])
        f1.addRow(self.autostart)
        self.notify = QCheckBox("Mostra notifiche pop-up")
        self.notify.setToolTip("Connessione/disconnessione, tunnel aggiunti o rimossi, aggiornamenti disponibili")
        self.notify.setChecked(values["notify"])
        f1.addRow(self.notify)
        self.refresh = QComboBox()
        for secs, label in self.REFRESH_CHOICES:
            self.refresh.addItem(label, secs)
        self.refresh.setCurrentIndex(max(0, self.refresh.findData(values["refresh_secs"])))
        f1.addRow("Aggiorna elenco tunnel ogni:", self.refresh)
        lay.addWidget(g1)

        g2 = QGroupBox("Aggiornamenti")
        f2 = QFormLayout(g2)
        self.update_check = QCheckBox("Controlla automaticamente se ci sono aggiornamenti")
        self.update_check.setChecked(values["update_check"])
        f2.addRow(self.update_check)
        lay.addWidget(g2)

        g3 = QGroupBox("Avanzate")
        f3 = QFormLayout(g3)
        self.console = QCheckBox("Mostra la finestra console durante la connessione (diagnostica)")
        self.console.setChecked(values["show_console"])
        f3.addRow(self.console)
        lay.addWidget(g3)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Salva")
        bb.button(QDialogButtonBox.Cancel).setText("Annulla")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def values(self) -> dict:
        return {
            "autostart": self.autostart.isChecked(),
            "notify": self.notify.isChecked(),
            "refresh_secs": int(self.refresh.currentData()),
            "update_check": self.update_check.isChecked(),
            "show_console": self.console.isChecked(),
        }


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
