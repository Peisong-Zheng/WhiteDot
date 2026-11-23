"""Register the current executable with the user's login session."""
import os
import plistlib
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.parsers.expat import ExpatError

LABEL = "io.whitedot.writer"
PLIST = Path.home() / "Library/LaunchAgents" / (LABEL + ".plist")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def launch_command():
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, str(Path(__file__).resolve().parents[1] / "main.py")]


def enabled():
    if sys.platform == "darwin":
        try:
            registration = plistlib.loads(PLIST.read_bytes())
        except (FileNotFoundError, plistlib.InvalidFileException, ExpatError, ValueError):
            return False
        return (isinstance(registration, dict) and registration.get("RunAtLoad") is True
                and registration.get("ProgramArguments") == launch_command())
    if sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                command, kind = winreg.QueryValueEx(key, "WhiteDot")
                return kind == winreg.REG_SZ and command == subprocess.list2cmdline(launch_command())
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
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(dir=PLIST.parent, delete=False) as f:
                tmp = Path(f.name)
                plistlib.dump(data, f)
            os.replace(tmp, PLIST)
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)
    elif sys.platform == "win32":
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            if on:
                winreg.SetValueEx(key, "WhiteDot", 0, winreg.REG_SZ,
                                  subprocess.list2cmdline(launch_command()))
            else:
                try:
                    winreg.DeleteValue(key, "WhiteDot")
                except FileNotFoundError:
                    pass
    else:
        raise OSError("Launch at login is unavailable on this system.")
