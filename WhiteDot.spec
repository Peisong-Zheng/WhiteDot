# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

root = Path(SPECPATH)
macos = sys.platform == "darwin"
icon = str(root / "build" / "artwork" / ("WhiteDot.icns" if macos else "WhiteDot.ico"))
hidden = []
if not macos:
    # Include the generated friendly wrapper; its import includes the GUID wrapper.
    hidden.append("comtypes.gen.UIAutomationClient")
a = Analysis([str(root / "main.py")], pathex=[str(root)], hiddenimports=hidden,
             excludes=["PyQt5", "PyQt6", "tkinter"])
pyz = PYZ(a.pure)
if macos:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="WhiteDot", console=False,
              strip=False, upx=False, icon=icon)
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="WhiteDot")
    app = BUNDLE(coll, name="WhiteDot.app", icon=icon, bundle_identifier="io.whitedot.writer",
                 info_plist={"LSUIElement": True, "CFBundleDisplayName": "WhiteDot",
                             "NSHighResolutionCapable": True,
                             "NSAccessibilityUsageDescription": "WhiteDot uses accessibility to check the focused English text field."})
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="WhiteDot", console=False,
              strip=False, upx=False, icon=icon)
