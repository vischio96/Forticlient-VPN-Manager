"""Render the documentation screenshots in docs/images using DEMO data only.

    python tools/screenshots.py

No real tunnel names or gateways ever end up in the images.
"""
import os
import sys
from pathlib import Path

os.environ["FVM_DEMO"] = "1"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "docs" / "images"
OUT.mkdir(parents=True, exist_ok=True)

from PIL import Image, ImageFilter  # noqa: E402
from PySide6.QtCore import QPoint, Qt, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

from fortivpn_manager import backend, connector, updater  # noqa: E402
from fortivpn_manager.dialogs import PromptDialog, SettingsDialog, UpdateDialog  # noqa: E402
from fortivpn_manager.popup import Popup  # noqa: E402


def shadowed(src: Path, radius: int = 10) -> None:
    """Rounded corners + soft drop shadow, like the real Windows 11 window."""
    im = Image.open(src).convert("RGBA")
    w, h = im.size
    mask = Image.new("L", (w, h), 0)
    from PIL import ImageDraw
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius, fill=255)
    im.putalpha(mask)
    pad = 28
    canvas = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    sh.paste((0, 0, 0, 110), (pad, pad + 6, pad + w, pad + h + 6), mask)
    sh = sh.filter(ImageFilter.GaussianBlur(12))
    canvas.alpha_composite(sh)
    canvas.alpha_composite(im, (pad, pad))
    canvas.save(src)


def save(widget, name: str, shadow: bool = True) -> None:
    QApplication.processEvents()
    path = OUT / f"{name}.png"
    widget.grab().save(str(path))
    if shadow:
        shadowed(path)
    print("saved", path.relative_to(ROOT))


def make_popup(**settings) -> Popup:
    p = Popup(settings)
    p.set_tunnels(backend.load_tunnels().tunnels)
    p.set_status(backend.load_status())
    p.show()
    QApplication.processEvents()
    return p


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle("windows11")
    hints = app.styleHints()

    for scheme, suffix in ((Qt.ColorScheme.Dark, "dark"), (Qt.ColorScheme.Light, "light")):
        hints.setColorScheme(scheme)
        QApplication.processEvents()
        p = make_popup(group_mode="protocol")
        save(p, f"popup-{suffix}")
        p.close()

    hints.setColorScheme(Qt.ColorScheme.Dark)

    p = make_popup(group_mode="both")
    p.search.setText("cliente")
    save(p, "search")
    p.close()

    p = make_popup(group_mode="origin", hidden_filters=[backend.ORIGIN_EMS])
    save(p, "filter-personal")
    p.close()

    p = make_popup(group_mode="protocol")
    p.set_update("1.1.0")
    save(p, "update-banner")
    p.close()

    # tray menu (same entries as the real one)
    m = QMenu()
    m.addAction("⬆  Aggiorna alla versione 1.1.0…")
    m.addSeparator()
    m.addAction("Apri elenco tunnel")
    m.addAction("Aggiorna ora")
    m.addSeparator()
    m.addAction("Disconnetti “Sede Centrale - Full Tunnel”")
    m.addSeparator()
    m.addAction("Impostazioni…")
    m.addAction("Controlla aggiornamenti")
    m.addSeparator()
    m.addAction("Apri FortiClient")
    m.addAction("Apri cartella log")
    m.addAction("Informazioni (v1.0.0)")
    m.addSeparator()
    m.addAction("Esci")
    m.popup(QPoint(200, 200))
    save(m, "tray-menu")
    m.close()

    d = SettingsDialog({"autostart": True, "notify": False, "refresh_secs": 30,
                        "update_check": True, "show_console": False})
    d.show()
    save(d, "settings")
    d.close()

    d = PromptDialog("Accesso Remoto - Backup", connector.KIND_PASSWORD, "Password:")
    d.edit.setText("password")
    d.show()
    save(d, "prompt-password")
    d.close()

    d = PromptDialog("Cliente Alfa - IPSEC-MFA", connector.KIND_TOKEN, "FortiToken Code:")
    d.edit.setText("482913")
    d.show()
    save(d, "prompt-token")
    d.close()

    info = updater.UpdateInfo(version="1.1.0", page_url=updater.RELEASES_PAGE, setup_url="x",
                              notes="### Aggiunto\n- Esempio di nota di rilascio\n\n### Corretto\n- Esempio di correzione")
    d = UpdateDialog("1.0.0", info, can_install=True)
    d.show()
    save(d, "update-dialog")
    d.close()

    QTimer.singleShot(0, app.quit)
    app.exec()


if __name__ == "__main__":
    main()
