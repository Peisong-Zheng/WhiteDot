"""Register the current executable with the user's login session."""
import os
import plistlib
import subprocess
import sys
import tempfile
from pathlib import Path, PureWindowsPath
from xml.parsers.expat import ExpatError

LABEL = "io.whitedot.writer"
PLIST = Path.home() / "Library/LaunchAgents" / (LABEL + ".plist")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
WINDOWS_ENTRY = "Folio Proofreader"
LEGACY_ENTRY = "WhiteDot"


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
                command, kind = winreg.QueryValueEx(key, WINDOWS_ENTRY)
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
                winreg.SetValueEx(key, WINDOWS_ENTRY, 0, winreg.REG_SZ,
                                  subprocess.list2cmdline(launch_command()))
            obsolete = (LEGACY_ENTRY,) if on else (WINDOWS_ENTRY, LEGACY_ENTRY)
            for name in obsolete:
                try:
                    winreg.DeleteValue(key, name)
                except FileNotFoundError:
                    pass
    else:
        raise OSError("Launch at login is unavailable on this system.")


def upgrade_login_item():
    """Carry an enabled login item across the rename when upgrading in place."""
    if not getattr(sys, "frozen", False):
        return
    if sys.platform == "darwin":
        exe = Path(sys.executable)
        if exe.parts[-3:] != ("Contents", "MacOS", "Folio") or exe.parents[2].name != "Folio.app":
            return
        old = exe.parents[2].with_name("WhiteDot.app") / "Contents/MacOS/WhiteDot"
        try:
            item = plistlib.loads(PLIST.read_bytes())
        except (FileNotFoundError, plistlib.InvalidFileException, ExpatError, ValueError):
            return
        if (isinstance(item, dict) and item.get("Label") == LABEL and item.get("RunAtLoad") is True
                and item.get("ProgramArguments") == [str(old)]):
            set_enabled(True)
    elif sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                old, kind = winreg.QueryValueEx(key, LEGACY_ENTRY)
        except FileNotFoundError:
            return
        directory = PureWindowsPath(sys.executable).parent
        legacy_commands = {subprocess.list2cmdline([str(directory / name)]).casefold()
                           for name in ("WhiteDot.exe", "WhiteDot-windows-x64.exe")}
        if kind == winreg.REG_SZ and old.casefold() in legacy_commands:
            set_enabled(True)
