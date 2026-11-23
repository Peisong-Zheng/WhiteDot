# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

root = Path(SPECPATH)
sys.path.insert(0, str(root))
from whitedot import __version__

macos = sys.platform == "darwin"
icon = str(root / "build" / "artwork" / ("WhiteDot.icns" if macos else "WhiteDot.ico"))
a = Analysis([str(root / "main.py")], pathex=[str(root)],
             datas=[(str(root / "whitedot" / "assets"), "whitedot/assets")],
             excludes=["PyQt5", "PyQt6", "tkinter"])
pyz = PYZ(a.pure)
if macos:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="WhiteDot", console=False,
              strip=False, upx=False, icon=icon)
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="WhiteDot")
    app = BUNDLE(coll, name="WhiteDot.app", icon=icon, bundle_identifier="io.whitedot.writer",
                 info_plist={"LSUIElement": True, "CFBundleDisplayName": "WhiteDot",
                             "CFBundleShortVersionString": __version__, "CFBundleVersion": __version__,
                             "LSMinimumSystemVersion": "15.0", "NSHighResolutionCapable": True})
else:
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo,
    )

    version_parts = tuple(map(int, __version__.split("."))) + (0,)
    version = VSVersionInfo(
        ffi=FixedFileInfo(filevers=version_parts, prodvers=version_parts),
        kids=[
            StringFileInfo([StringTable("040904B0", [
                StringStruct("FileDescription", "WhiteDot English proofreading editor"),
                StringStruct("FileVersion", __version__),
                StringStruct("ProductName", "WhiteDot"),
                StringStruct("ProductVersion", __version__),
                StringStruct("OriginalFilename", "WhiteDot.exe"),
            ])]),
            VarFileInfo([VarStruct("Translation", [1033, 1200])]),
        ],
    )
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="WhiteDot", console=False,
              strip=False, upx=False, icon=icon, version=version)
