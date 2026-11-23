# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

root = Path(SPECPATH)
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
                             "CFBundleShortVersionString": "0.2.0", "CFBundleVersion": "0.2.0",
                             "NSHighResolutionCapable": True})
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="WhiteDot", console=False,
              strip=False, upx=False, icon=icon)
