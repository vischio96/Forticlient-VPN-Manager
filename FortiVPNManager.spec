# PyInstaller spec
#   portable single exe :  pyinstaller --noconfirm FortiVPNManager.spec               -> dist/FortiVPNManager.exe
#   folder (installer)  :  set FVM_BUILD=onedir & pyinstaller --noconfirm FortiVPNManager.spec
#                                                                          -> dist/FortiVPNManager/FortiVPNManager.exe
import os
import re
from pathlib import Path

ROOT = Path(SPECPATH)
VERSION = re.search(r'__version__\s*=\s*"([^"]+)"',
                    (ROOT / "fortivpn_manager" / "__init__.py").read_text()).group(1)
nums = [int(x) for x in re.findall(r"\d+", VERSION)[:3]] + [0]
while len(nums) < 4:
    nums.insert(-1, 0)
vtuple = tuple(nums[:4])

# Windows version resource
version_file = ROOT / "build" / "version_info.txt"
version_file.parent.mkdir(exist_ok=True)
version_file.write_text(f"""
VSVersionInfo(
  ffi=FixedFileInfo(filevers={vtuple}, prodvers={vtuple}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'FortiClient VPN Manager'),
      StringStruct('FileDescription', 'FortiClient VPN Manager - system tray launcher'),
      StringStruct('FileVersion', '{VERSION}'),
      StringStruct('InternalName', 'FortiVPNManager'),
      StringStruct('OriginalFilename', 'FortiVPNManager.exe'),
      StringStruct('ProductName', 'FortiClient VPN Manager'),
      StringStruct('ProductVersion', '{VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""", encoding="utf-8")

EXCLUDES = [
    "tkinter", "unittest", "pydoc", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtPdf",
    "PySide6.QtWebEngineCore", "PySide6.QtMultimedia", "PySide6.QtOpenGL", "PySide6.QtSql",
    "PySide6.QtSvg", "PySide6.QtTest", "PySide6.QtXml", "PySide6.QtDBus", "PySide6.QtConcurrent",
    "PySide6.QtPrintSupport", "PySide6.QtDesigner", "PySide6.QtHelp",
]

a = Analysis(
    ["main.py"],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "assets" / f), "assets") for f in ("icon.ico", "icon.png", "tray_on.png", "tray_off.png")],
    hiddenimports=[],
    excludes=EXCLUDES,
    noarchive=False,
)

# drop heavy Qt plugins/translations we never use
a.datas = [d for d in a.datas if "translations" not in d[0].replace("\\", "/")]
a.binaries = [b for b in a.binaries if not any(x in b[0] for x in (
    "opengl32sw", "Qt6Pdf", "Qt6Qml", "Qt6Quick", "Qt6Svg", "Qt6OpenGL", "Qt6VirtualKeyboard"))]

pyz = PYZ(a.pure)

ONEDIR = os.environ.get("FVM_BUILD", "onefile").lower() == "onedir"

common = dict(
    name="FortiVPNManager",
    icon=str(ROOT / "assets" / "icon.ico"),
    version=str(version_file),
    console=False,
    upx=False,
    debug=False,
    strip=False,
)

if ONEDIR:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **common)
    coll = COLLECT(exe, a.binaries, a.datas, name="FortiVPNManager", upx=False, strip=False)
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], runtime_tmpdir=None, **common)
