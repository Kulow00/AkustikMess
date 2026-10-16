# PyInstaller-Bauplan für Windows (.exe-Ordner) und macOS (.app).
# Bauen auf dem jeweiligen Zielsystem:
#   pip install pyinstaller
#   pyinstaller akustikmess.spec --noconfirm
# Ergebnis: dist/AkustikMess/ (Windows) bzw. dist/AkustikMess.app (macOS)
import re
import sys

APP_VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', open("akustik/__init__.py", encoding="utf-8").read()).group(1)


def windows_version_info():
    """Datei-Eigenschaften der .exe (Produktname/Version; prüft auch die Code-Signatur)."""
    from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable,
                                                     VarFileInfo, VarStruct, VSVersionInfo)
    m = re.match(r"(\d+)\.(\d+)\.(\d+)(?:-[a-z]+\.(\d+))?", APP_VERSION)
    nums = tuple(int(x or 0) for x in m.groups())
    strings = [StringStruct("ProductName", "AkustikMess"), StringStruct("FileDescription", "AkustikMess"),
               StringStruct("ProductVersion", APP_VERSION), StringStruct("FileVersion", APP_VERSION),
               StringStruct("OriginalFilename", "AkustikMess.exe"), StringStruct("InternalName", "AkustikMess"),
               StringStruct("LegalCopyright", "© 2026 Alex Kulow · GPL-3.0-or-later")]
    return VSVersionInfo(ffi=FixedFileInfo(filevers=nums, prodvers=nums),
                         kids=[StringFileInfo([StringTable("040704B0", strings)]),
                               VarFileInfo([VarStruct("Translation", [0x0407, 1200])])])


a = Analysis(
    ["run_akustikmess.py"],
    pathex=["."],
    hiddenimports=["pyqtgraph.exporters"],
    datas=[],
    excludes=["tkinter", "matplotlib", "pytest", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
              "PySide6.QtNetwork", "PySide6.QtTest", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
              "PySide6.QtVirtualKeyboard", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets"],
)

# Nicht benötigte Qt-Teile entfernen (Qt Quick/QML, virtuelle Tastatur, PDF, Netzwerk, Test) und nur deutsche
# und englische Übersetzungen behalten – spart rund 25 MB. opengl32sw.dll bleibt: Software-OpenGL für die
# 3D-Ansicht auf Rechnern ohne passende Grafiktreiber.
_DROP = ("Qt6Qml", "Qt6Quick", "Qt6Pdf", "Qt6VirtualKeyboard", "Qt6Test", "Qt6Network", "QtNetwork.pyd",
         "QtTest.pyd", "platforminputcontexts", "networkinformation", "plugins/tls")


def _keep(entry):
    name = entry[0].replace("\\", "/")
    if any(d.replace("\\", "/") in name for d in _DROP):
        return False
    if "/translations/" in name and name.endswith(".qm"):
        return name.rsplit("/", 1)[-1].split("_")[-1] in ("de.qm", "en.qm")
    return True


a.binaries = [e for e in a.binaries if _keep(e)]
a.datas = [e for e in a.datas if _keep(e)]
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="AkustikMess",
    console=False,
    version=windows_version_info() if sys.platform == "win32" else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="AkustikMess")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="AkustikMess.app",
        bundle_identifier="de.akustikmess.app",
        info_plist={
            # Pflicht unter macOS, sonst liefert das Mikrofon nur Stille
            "NSMicrophoneUsageDescription": "AkustikMess benötigt den Audio-Eingang für Messungen.",
            "NSHighResolutionCapable": True,
        },
    )
