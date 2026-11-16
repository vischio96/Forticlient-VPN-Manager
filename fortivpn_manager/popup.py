"""Tray flyout: search box, filters, grouping and the tunnel list."""
from __future__ import annotations

import ctypes
import logging
import time
from datetime import datetime

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QKeyEvent, QPainter, QPalette
from PySide6.QtWidgets import (
    QApplication, QComboBox, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton, QStyle, QStyledItemDelegate,
    QStyleOptionViewItem, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from . import backend
from .backend import (
    ORIGIN_EMS, ORIGIN_PERSONAL, PROTO_IPSEC, PROTO_SSL, STATUS_CONNECTED, STATUS_CONNECTING, Tunnel,
)

log = logging.getLogger(__name__)

ROLE_TUNNEL = Qt.UserRole
ROLE_STATUS = Qt.UserRole + 1
ROLE_GROUP = Qt.UserRole + 2

GROUP_MODES = [
    ("protocol", "Tipo (IPsec / SSL)"),
    ("origin", "Origine (EMS / Personal)"),
    ("both", "Tipo + Origine"),
    ("none", "Nessun gruppo"),
]
CONNECTED_GROUP = "Connessi"

DOT = {
    STATUS_CONNECTED: QColor("#2ecc71"),
    STATUS_CONNECTING: QColor("#f39c12"),
}


def _is_dark(pal: QPalette) -> bool:
    return pal.color(QPalette.Window).lightness() < 128


class TunnelDelegate(QStyledItemDelegate):
    ROW_H = 40
    GROUP_H = 28

    def sizeHint(self, option, index):  # noqa: N802 (Qt API)
        is_group = index.data(ROLE_GROUP) is not None
        return QSize(option.rect.width(), self.GROUP_H if is_group else self.ROW_H)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        group = index.data(ROLE_GROUP)
        pal = option.palette
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        r = option.rect

        if group is not None:
            # section header
            f = QFont(option.font)
            f.setBold(True)
            f.setPointSizeF(f.pointSizeF() * 0.85)
            painter.setFont(f)
            painter.setPen(pal.color(QPalette.PlaceholderText))
            arrow = "▾" if option.state & QStyle.State_Open else "▸"
            painter.drawText(r.adjusted(4, 0, -8, 0), Qt.AlignVCenter | Qt.AlignLeft,
                             f"{arrow}  {group.upper()}")
            painter.drawText(r.adjusted(0, 0, -10, 0), Qt.AlignVCenter | Qt.AlignRight,
                             str(index.data(Qt.DisplayRole) or ""))
            painter.restore()
            return

        t: Tunnel = index.data(ROLE_TUNNEL)
        status = index.data(ROLE_STATUS)

        # background (hover / selection)
        if option.state & (QStyle.State_Selected | QStyle.State_MouseOver):
            bg = QColor(pal.color(QPalette.Highlight))
            bg.setAlpha(70 if option.state & QStyle.State_Selected else 35)
            painter.setPen(Qt.NoPen)
            painter.setBrush(bg)
            painter.drawRoundedRect(r.adjusted(2, 1, -2, -1), 6, 6)

        # status dot
        cy = r.center().y()
        dot = DOT.get(status)
        if dot is None:
            painter.setPen(QColor(pal.color(QPalette.PlaceholderText)))
            painter.setBrush(Qt.NoBrush)
        else:
            painter.setPen(Qt.NoPen)
            painter.setBrush(dot)
        painter.drawEllipse(QPoint(r.left() + 14, cy), 5, 5)

        text_left = r.left() + 28
        badge_w = self._paint_badges(painter, option, t, r)
        text_rect = QRect(text_left, r.top() + 3, r.right() - text_left - badge_w - 8, r.height() // 2)

        name_font = QFont(option.font)
        if status == STATUS_CONNECTED:
            name_font.setBold(True)
        painter.setFont(name_font)
        painter.setPen(pal.color(QPalette.Text))
        fm = painter.fontMetrics()
        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignBottom, fm.elidedText(t.name, Qt.ElideRight, text_rect.width()))

        sub_font = QFont(option.font)
        sub_font.setPointSizeF(sub_font.pointSizeF() * 0.85)
        painter.setFont(sub_font)
        painter.setPen(pal.color(QPalette.PlaceholderText))
        sub = t.server or "—"
        if status == STATUS_CONNECTED:
            sub = "Connesso · " + sub
        elif status == STATUS_CONNECTING:
            sub = "Connessione in corso… · " + sub
        sub_rect = QRect(text_left, r.top() + r.height() // 2 + 1, text_rect.width(), r.height() // 2 - 3)
        painter.drawText(sub_rect, Qt.AlignLeft | Qt.AlignTop,
                         painter.fontMetrics().elidedText(sub, Qt.ElideRight, sub_rect.width()))
        painter.restore()

    def _paint_badges(self, painter: QPainter, option, t: Tunnel, r: QRect) -> int:
        badges = ["IPsec" if t.protocol == PROTO_IPSEC else "SSL", t.origin]
        if t.saml:
            badges.append("SAML")
        f = QFont(option.font)
        f.setPointSizeF(f.pointSizeF() * 0.75)
        painter.setFont(f)
        fm = painter.fontMetrics()
        dark = _is_dark(option.palette)
        x = r.right() - 8
        total = 0
        for b in reversed(badges):
            w = fm.horizontalAdvance(b) + 10
            rect = QRect(x - w, r.center().y() - 9, w, 18)
            col = _badge_color(b, dark)
            bg = QColor(col)
            bg.setAlpha(45)
            painter.setPen(Qt.NoPen)
            painter.setBrush(bg)
            painter.drawRoundedRect(rect, 4, 4)
            painter.setPen(col)
            painter.drawText(rect, Qt.AlignCenter, b)
            x -= w + 4
            total += w + 4
        return total


def _badge_color(b: str, dark: bool) -> QColor:
    light = {"IPsec": "#1f6feb", "SSL": "#8250df", "EMS": "#1a7f37", "Personal": "#bc4c00", "SAML": "#57606a"}
    darkc = {"IPsec": "#58a6ff", "SSL": "#bc8cff", "EMS": "#3fb950", "Personal": "#ffa657", "SAML": "#8b949e"}
    return QColor((darkc if dark else light).get(b, "#888888"))


class Chip(QToolButton):
    def __init__(self, text: str, tooltip: str, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setToolTip(tooltip)
        self.setCheckable(True)
        self.setChecked(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("chip")


class Popup(QWidget):
    connectRequested = Signal(object)      # Tunnel
    disconnectRequested = Signal(object)   # Tunnel
    refreshRequested = Signal()
    settingsMenuRequested = Signal(QPoint)
    settingChanged = Signal(str, object)
    updateRequested = Signal()

    def __init__(self, settings: dict):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setWindowTitle("FortiClient VPN Manager")
        self.resize(440, 620)
        self._tunnels: list[Tunnel] = []
        self._status: dict[str, str] = {}
        self._collapsed: set[str] = set(settings.get("collapsed", []))
        self._last_update: datetime | None = None
        self._error = ""
        self._visible_count = 0
        self._hidden_at = 0.0
        self._was_active = False

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 8)
        root.setSpacing(8)

        # header
        head = QHBoxLayout()
        title = QLabel("FortiClient VPN")
        tf = title.font()
        tf.setPointSizeF(tf.pointSizeF() * 1.25)
        tf.setBold(True)
        title.setFont(tf)
        head.addWidget(title)
        head.addStretch(1)
        self.summary = QLabel("")
        self.summary.setObjectName("muted")
        head.addWidget(self.summary)
        root.addLayout(head)

        # "update available" banner (hidden until an update is found)
        self.update_btn = QPushButton("")
        self.update_btn.setObjectName("update")
        self.update_btn.setCursor(Qt.PointingHandCursor)
        self.update_btn.clicked.connect(self.updateRequested)
        self.update_btn.hide()
        root.addWidget(self.update_btn)

        # search
        self.search = QLineEdit()
        self.search.setPlaceholderText("Cerca tunnel per nome o server…   (Ctrl+F)")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.rebuild)
        self.search.installEventFilter(self)
        root.addWidget(self.search)

        # filters + grouping
        row = QHBoxLayout()
        row.setSpacing(4)
        self.chips: dict[str, Chip] = {}
        for key, text, tip in (
            (PROTO_IPSEC, "IPsec", "Mostra tunnel IPsec VPN"),
            (PROTO_SSL, "SSL", "Mostra tunnel SSL VPN"),
            (ORIGIN_EMS, "EMS", "Mostra tunnel distribuiti da EMS"),
            (ORIGIN_PERSONAL, "Personal", "Mostra tunnel creati dall'utente"),
        ):
            c = Chip(text, tip)
            c.setChecked(key not in settings.get("hidden_filters", []))
            c.toggled.connect(self._filters_changed)
            self.chips[key] = c
            row.addWidget(c)
        row.addStretch(1)
        self.group_combo = QComboBox()
        for key, label in GROUP_MODES:
            self.group_combo.addItem(label, key)
        idx = max(0, self.group_combo.findData(settings.get("group_mode", "protocol")))
        self.group_combo.setCurrentIndex(idx)
        self.group_combo.currentIndexChanged.connect(self._group_changed)
        self.group_combo.setToolTip("Raggruppa per")
        row.addWidget(self.group_combo)
        root.addLayout(row)

        # list
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(0)
        self.tree.setItemDelegate(TunnelDelegate(self.tree))
        self.tree.setMouseTracking(True)
        self.tree.setUniformRowHeights(False)
        self.tree.setVerticalScrollMode(QTreeWidget.ScrollPerPixel)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        self.tree.itemClicked.connect(self._item_clicked)
        self.tree.itemExpanded.connect(lambda it: self._set_collapsed(it, False))
        self.tree.itemCollapsed.connect(lambda it: self._set_collapsed(it, True))
        self.tree.installEventFilter(self)
        self.tree.setObjectName("tunnels")
        root.addWidget(self.tree, 1)

        self.empty = QLabel("")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setObjectName("muted")
        self.empty.setWordWrap(True)
        self.empty.hide()
        root.addWidget(self.empty, 1)
        self.reset_btn = QPushButton("Reimposta filtri")
        self.reset_btn.clicked.connect(self.reset_filters)
        self.reset_btn.hide()
        root.addWidget(self.reset_btn, 0, Qt.AlignHCenter)

        # footer
        foot = QHBoxLayout()
        self.footer = QLabel("")
        self.footer.setObjectName("muted")
        foot.addWidget(self.footer, 1)
        btn_refresh = QToolButton()
        btn_refresh.setText("⟳")
        btn_refresh.setToolTip("Aggiorna ora (F5)")
        btn_refresh.clicked.connect(self.refreshRequested)
        btn_refresh.setObjectName("flat")
        foot.addWidget(btn_refresh)
        btn_menu = QToolButton()
        btn_menu.setText("⚙")
        btn_menu.setToolTip("Impostazioni")
        btn_menu.setObjectName("flat")
        btn_menu.clicked.connect(lambda: self.settingsMenuRequested.emit(
            btn_menu.mapToGlobal(QPoint(0, btn_menu.height()))))
        foot.addWidget(btn_menu)
        root.addLayout(foot)

        self._apply_style()
        self._deact_timer = QTimer(self, singleShot=True, interval=150, timeout=self._maybe_hide)

    # ------------------------------------------------------------------ style
    def _apply_style(self):
        self.setStyleSheet("""
            QLineEdit { padding: 7px 8px; border-radius: 6px; border: 1px solid palette(mid); }
            QLineEdit:focus { border: 1px solid palette(highlight); }
            QToolButton#chip { padding: 3px 9px; border-radius: 11px; border: 1px solid palette(mid);
                               color: palette(placeholder-text); }
            QToolButton#chip:checked { background: palette(highlight); color: palette(highlighted-text);
                                       border: 1px solid palette(highlight); }
            QToolButton#flat { border: none; font-size: 15px; padding: 2px 6px; border-radius: 4px; }
            QToolButton#flat:hover { background: palette(midlight); }
            QLabel#muted { color: palette(placeholder-text); }
            QTreeWidget#tunnels { border: none; background: transparent; outline: 0; }
            QPushButton#update { text-align: left; padding: 6px 10px; border-radius: 6px;
                                 border: 1px solid #2e8b57; background: rgba(46, 204, 113, 40); }
            QPushButton#update:hover { background: rgba(46, 204, 113, 80); }
        """)

    # ------------------------------------------------------------------ data
    def set_update(self, version: str | None):
        if version:
            self.update_btn.setText(f"⬆  Disponibile la versione {version} – clic per aggiornare")
        self.update_btn.setVisible(bool(version))

    def set_tunnels(self, tunnels: list[Tunnel], error: str = ""):
        self._tunnels = tunnels
        self._error = error
        self._last_update = datetime.now()
        self.rebuild()

    def set_status(self, status: dict[str, str]):
        changed = status != self._status
        self._status = status
        if changed:
            self.rebuild()
        else:
            self._update_labels(self._visible_count)

    def _filtered(self) -> list[Tunnel]:
        terms = self.search.text().casefold().split()
        show = {k for k, c in self.chips.items() if c.isChecked()}
        out = []
        for t in self._tunnels:
            if t.protocol not in show or t.origin not in show:
                continue
            hay = f"{t.name} {t.server} {t.description} {t.protocol} {t.origin} {'saml' if t.saml else ''}".casefold()
            if all(term in hay for term in terms):
                out.append(t)
        return out

    def _group_of(self, t: Tunnel, mode: str) -> str:
        if mode == "protocol":
            return t.protocol
        if mode == "origin":
            return t.origin
        if mode == "both":
            return f"{t.protocol} · {t.origin}"
        return ""

    def rebuild(self, *_):
        selected = self._selected_tunnel()
        mode = self.group_combo.currentData()
        searching = bool(self.search.text().strip())
        tunnels = self._filtered()
        self._visible_count = len(tunnels)

        self.tree.setUpdatesEnabled(False)
        self.tree.clear()
        groups: dict[str, list[Tunnel]] = {}
        connected = [t for t in tunnels if self._status.get(t.name) in (STATUS_CONNECTED, STATUS_CONNECTING)]
        if connected:
            groups[CONNECTED_GROUP] = connected
        if mode == "none":
            groups.setdefault("", []).extend(tunnels)
        else:
            order = {PROTO_IPSEC: 0, PROTO_SSL: 1, ORIGIN_EMS: 0, ORIGIN_PERSONAL: 1}
            keyf = (lambda t: (order[t.protocol], order[t.origin])) if mode == "both" else (
                lambda t: order[getattr(t, "protocol" if mode == "protocol" else "origin")])
            for t in sorted(tunnels, key=keyf):
                groups.setdefault(self._group_of(t, mode), []).append(t)

        reselect = None
        for gname, items in groups.items():
            parent = self.tree.invisibleRootItem()
            if gname:
                g = QTreeWidgetItem([str(len(items))])
                g.setData(0, ROLE_GROUP, gname)
                g.setFlags(Qt.ItemIsEnabled)
                self.tree.addTopLevelItem(g)
                parent = g
            for t in items:
                it = QTreeWidgetItem([t.name])
                it.setData(0, ROLE_TUNNEL, t)
                it.setData(0, ROLE_STATUS, self._status.get(t.name))
                it.setToolTip(0, self._tooltip(t))
                parent.addChild(it)
                if selected and t.key == selected.key and reselect is None:
                    reselect = it
            if gname:
                g.setExpanded(searching or gname not in self._collapsed)
        if reselect is not None:
            self.tree.setCurrentItem(reselect)
        self.tree.setUpdatesEnabled(True)
        self._update_labels(len(tunnels))

    def _tooltip(self, t: Tunnel) -> str:
        lines = [f"<b>{t.name}</b>", f"{t.protocol} · {t.origin}" + (" · SAML" if t.saml else "")]
        if t.server:
            lines.append(f"Server: {t.server}")
        if t.description:
            lines.append(t.description)
        st = self._status.get(t.name)
        lines.append("Stato: " + {"connected": "connesso", "connecting": "in connessione"}.get(st, "disconnesso"))
        lines.append("<i>Clic per connettere · tasto destro per altre azioni</i>")
        return "<br>".join(lines)

    def _update_labels(self, visible: int):
        n_conn = sum(1 for s in self._status.values() if s == STATUS_CONNECTED)
        total = len(self._tunnels)
        self.summary.setText(f"{total} tunnel" + (f" · {n_conn} connesso" if n_conn == 1 else
                                                    f" · {n_conn} connessi" if n_conn else ""))
        ts = self._last_update.strftime("%H:%M:%S") if self._last_update else "—"
        shown = f"{visible} visualizzati · " if visible != total else ""
        self.footer.setText(f"{shown}Aggiornato alle {ts}")
        if self._error:
            self.empty.setText(self._error)
        elif total == 0:
            self.empty.setText("Nessun tunnel configurato in FortiClient.")
        filtered = any(not c.isChecked() for c in self.chips.values())
        if not self._error and total and filtered:
            self.empty.setText("Nessun tunnel corrisponde alla ricerca\ncon i filtri attivi.")
        elif not self._error and total:
            self.empty.setText("Nessun tunnel corrisponde alla ricerca.")
        no_rows = visible == 0
        self.tree.setVisible(not no_rows)
        self.empty.setVisible(no_rows)
        self.reset_btn.setVisible(no_rows and filtered and bool(total))

    def reset_filters(self):
        for c in self.chips.values():
            c.blockSignals(True)
            c.setChecked(True)
            c.blockSignals(False)
        self._filters_changed()

    # ------------------------------------------------------------------ interaction
    def _selected_tunnel(self) -> Tunnel | None:
        it = self.tree.currentItem()
        return it.data(0, ROLE_TUNNEL) if it else None

    def _first_tunnel_item(self) -> QTreeWidgetItem | None:
        it = self.tree.topLevelItem(0)
        while it is not None:
            if it.data(0, ROLE_TUNNEL) is not None:
                return it
            if it.childCount() and it.isExpanded():
                return it.child(0)
            it = self.tree.itemBelow(it)
        return None

    def _item_clicked(self, item: QTreeWidgetItem, _col: int):
        gname = item.data(0, ROLE_GROUP)
        if gname is not None:
            item.setExpanded(not item.isExpanded())
            return
        self._activate(item.data(0, ROLE_TUNNEL))

    def _activate(self, t: Tunnel | None):
        if t is None:
            return
        st = self._status.get(t.name)
        if st in (STATUS_CONNECTED, STATUS_CONNECTING):
            m = QMenu(self)
            m.addAction(f"Disconnetti “{t.name}”", lambda: self.disconnectRequested.emit(t))
            m.addAction("Annulla")
            m.exec(QCursor.pos())
        else:
            self.connectRequested.emit(t)

    def _context_menu(self, pos: QPoint):
        item = self.tree.itemAt(pos)
        t = item.data(0, ROLE_TUNNEL) if item else None
        if t is None:
            return
        st = self._status.get(t.name)
        m = QMenu(self)
        a_conn = m.addAction("Connetti", lambda: self.connectRequested.emit(t))
        a_disc = m.addAction("Disconnetti", lambda: self.disconnectRequested.emit(t))
        a_conn.setEnabled(st not in (STATUS_CONNECTED, STATUS_CONNECTING))
        a_disc.setEnabled(st in (STATUS_CONNECTED, STATUS_CONNECTING))
        m.addSeparator()
        m.addAction("Copia nome", lambda: QGuiApplication.clipboard().setText(t.name))
        if t.server:
            m.addAction("Copia server", lambda: QGuiApplication.clipboard().setText(t.server))
        m.addSeparator()
        m.addAction("Apri FortiClient", backend.open_forticlient_gui)
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def _set_collapsed(self, item: QTreeWidgetItem, collapsed: bool):
        if self.search.text().strip():
            return  # don't persist the auto-expansion used while searching
        g = item.data(0, ROLE_GROUP)
        if g is None:
            return
        (self._collapsed.add if collapsed else self._collapsed.discard)(g)
        self.settingChanged.emit("collapsed", sorted(self._collapsed))

    def _filters_changed(self):
        hidden = [k for k, c in self.chips.items() if not c.isChecked()]
        self.settingChanged.emit("hidden_filters", hidden)
        self.rebuild()

    def _group_changed(self):
        self.settingChanged.emit("group_mode", self.group_combo.currentData())
        self.rebuild()

    def eventFilter(self, obj, ev):  # noqa: N802
        if ev.type() == QEvent.KeyPress:
            ke: QKeyEvent = ev
            key = ke.key()
            if obj is self.search:
                if key == Qt.Key_Down:
                    first = self._first_tunnel_item()
                    if first:
                        self.tree.setFocus()
                        self.tree.setCurrentItem(first)
                    return True
                if key in (Qt.Key_Return, Qt.Key_Enter):
                    it = self.tree.currentItem() or self._first_tunnel_item()
                    if it is not None:
                        self._activate(it.data(0, ROLE_TUNNEL))
                    return True
            elif obj is self.tree:
                if key in (Qt.Key_Return, Qt.Key_Enter):
                    it = self.tree.currentItem()
                    if it is not None:
                        if it.data(0, ROLE_GROUP) is not None:
                            it.setExpanded(not it.isExpanded())
                        else:
                            self._activate(it.data(0, ROLE_TUNNEL))
                    return True
                if ke.text() and ke.text().isprintable() and not ke.modifiers() & (Qt.ControlModifier | Qt.AltModifier):
                    # typing anywhere goes to the search box
                    self.search.setFocus()
                    self.search.insert(ke.text())
                    return True
                if key == Qt.Key_Backspace:
                    self.search.setFocus()
                    self.search.backspace()
                    return True
        return super().eventFilter(obj, ev)

    def keyPressEvent(self, ev: QKeyEvent):  # noqa: N802
        if ev.key() == Qt.Key_Escape:
            if self.search.text():
                self.search.clear()
                self.search.setFocus()
            else:
                self.hide()
            return
        if ev.key() == Qt.Key_F5:
            self.refreshRequested.emit()
            return
        if ev.key() == Qt.Key_F and ev.modifiers() & Qt.ControlModifier:
            self.search.setFocus()
            self.search.selectAll()
            return
        super().keyPressEvent(ev)

    # ------------------------------------------------------------------ show / hide
    def toggle(self, anchor: QPoint | None = None):
        if self.isVisible():
            self.hide()
        elif time.monotonic() - self._hidden_at > 0.35:
            # (clicking the tray icon first deactivates -> auto-hides the popup:
            #  don't immediately reopen it in that case)
            self.show_near_tray(anchor)

    def hideEvent(self, ev):  # noqa: N802
        log.debug("popup hidden (was_active=%s)", self._was_active)
        self._hidden_at = time.monotonic()
        super().hideEvent(ev)

    def show_near_tray(self, anchor: QPoint | None = None):
        """Show next to ``anchor`` (tray icon centre) or, if unknown, the mouse cursor."""
        cur = anchor if anchor is not None else QCursor.pos()
        screen = QGuiApplication.screenAt(cur) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        full = screen.geometry()
        m = 12
        # anchor to the corner where the taskbar is (closest to the tray icon / cursor)
        x = area.right() - self.width() - m if cur.x() > area.center().x() else area.left() + m
        y = area.bottom() - self.height() - m if cur.y() > area.center().y() else area.top() + m
        if area.top() > full.top():  # taskbar on top
            y = area.top() + m
        self.move(x, y)
        self._was_active = False
        log.debug("popup show at %d,%d", x, y)
        self.show()
        self.raise_()
        self.activateWindow()
        self._round_corners()
        self.search.setFocus()
        self.search.selectAll()

    def _round_corners(self):
        try:  # Windows 11: DWMWA_WINDOW_CORNER_PREFERENCE = 33, DWMWCP_ROUND = 2
            pref = ctypes.c_int(2)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(int(self.winId()), 33, ctypes.byref(pref), ctypes.sizeof(pref))
        except Exception:
            pass

    def changeEvent(self, ev):  # noqa: N802
        if ev.type() == QEvent.ActivationChange:
            if self.isActiveWindow():
                self._was_active = True
            elif self._was_active:
                # auto-hide (flyout behaviour) only after the user has actually focused it
                self._deact_timer.start()
        super().changeEvent(ev)

    def _maybe_hide(self):
        # stay open while one of our own menus/dialogs is in front
        if QApplication.activePopupWidget() or QApplication.activeModalWidget():
            return
        if QApplication.activeWindow() is None:
            self.hide()
