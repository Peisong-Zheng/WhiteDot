"""Register the current executable with the user's login session."""
import os
import plistlib
import subprocess
import sys
import tempfile
from pathlib import Path

LABEL = "io.whitedot.writer"
PLIST = Path.home() / "Library/LaunchAgents" / (LABEL + ".plist")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def launch_command():
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, str(Path(__file__).resolve().parents[1] / "main.py")]


def enabled():
    if sys.platform == "darwin":
        return PLIST.is_file()
    if sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                winreg.QueryValueEx(key, "WhiteDot")
                return True
        except FileNotFoundError:
            return False
    return False


def set_enabled(on):
    if sys.platform == "darwin":
        if not on:
            PLIST.unlink(missing_ok=True)
            return
        PLIST.parent.mkdir(parents=True, exist_ok=True)
        data = {"Label": LABEL, "ProgramArguments": launch_command(), "RunAtLoad": True}
        with tempfile.NamedTemporaryFile(dir=PLIST.parent, delete=False) as f:
            plistlib.dump(data, f)
        os.replace(f.name, PLIST)
    elif sys.platform == "win32":
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            if on:
                winreg.SetValueEx(key, "WhiteDot", 0, winreg.REG_SZ,
                                  subprocess.list2cmdline(launch_command()))
            elif enabled():
                winreg.DeleteValue(key, "WhiteDot")
    else:
        raise OSError("不支持当前系统的登录启动。")
