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
    excludes=["tkinter", "matplotlib", "pytest"],
)
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
