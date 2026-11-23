import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from whitedot import startup


class StartupTests(unittest.TestCase):
    def test_macos_login_item_can_be_enabled_and_removed(self):
        cmd = ["/Applications/My Tools/Folio.app/Contents/MacOS/Folio"]
        with tempfile.TemporaryDirectory() as tmp, patch.object(startup.sys, "platform", "darwin"):
            dest = Path(tmp, "LaunchAgents", startup.LABEL + ".plist")
            with patch.object(startup, "PLIST", dest), patch.object(startup, "launch_command", return_value=cmd):
                self.assertFalse(startup.enabled())
                startup.set_enabled(True)
                self.assertTrue(startup.enabled())
                config = plistlib.loads(dest.read_bytes())
                self.assertEqual(config["ProgramArguments"], cmd)
                self.assertTrue(config["RunAtLoad"])
                moved_cmd = ["/Applications/Folio.app/Contents/MacOS/Folio"]
                with patch.object(startup, "launch_command", return_value=moved_cmd):
                    self.assertFalse(startup.enabled())
                    startup.set_enabled(True)
                    self.assertTrue(startup.enabled())
                startup.set_enabled(False)
                self.assertFalse(startup.enabled())

    def test_windows_move_repairs_quoted_portable_path(self):
        import subprocess
        import sys

        registry = MagicMock()
        cmd = [r"C:\New Folder\Folio-windows-x64.exe"]
        with (patch.dict(sys.modules, {"winreg": registry}), patch.object(startup.sys, "platform", "win32"),
              patch.object(startup, "launch_command", return_value=cmd)):
            registry.QueryValueEx.return_value = (r"C:\Old\WhiteDot.exe", registry.REG_SZ)
            self.assertFalse(startup.enabled())
            startup.set_enabled(True)
            new_value = subprocess.list2cmdline(cmd)
            self.assertEqual(registry.SetValueEx.call_args.args[-1], new_value)
            registry.QueryValueEx.return_value = (new_value, registry.REG_SZ)
            self.assertTrue(startup.enabled())
            startup.set_enabled(False)
            self.assertEqual([call.args[1] for call in registry.DeleteValue.call_args_list],
                             [startup.LEGACY_ENTRY, startup.WINDOWS_ENTRY, startup.LEGACY_ENTRY])

    def test_macos_rename_preserves_only_an_enabled_in_place_login_item(self):
        old = str(Path("/Applications/WhiteDot.app/Contents/MacOS/WhiteDot"))
        new = str(Path("/Applications/Folio.app/Contents/MacOS/Folio"))
        with (tempfile.TemporaryDirectory() as tmp,
              patch.object(startup, "PLIST", Path(tmp, "login.plist")),
              patch.object(startup.sys, "platform", "darwin"),
              patch.object(startup.sys, "frozen", True, create=True),
              patch.object(startup.sys, "executable", new)):
            startup.upgrade_login_item()
            self.assertFalse(startup.PLIST.exists())
            item = {"Label": startup.LABEL, "ProgramArguments": [old], "RunAtLoad": True}
            startup.PLIST.write_bytes(plistlib.dumps(item))
            with patch.object(startup.sys, "executable", "/Downloads/Folio.app/Contents/MacOS/Folio"):
                startup.upgrade_login_item()
            self.assertEqual(plistlib.loads(startup.PLIST.read_bytes()), item)
            startup.upgrade_login_item()
            self.assertTrue(startup.enabled())

    def test_windows_rename_moves_existing_entry_to_folio(self):
        import sys
        from subprocess import list2cmdline
        registry = MagicMock()
        old = r"C:\My Apps\WhiteDot-windows-x64.exe"
        new = r"C:\My Apps\Folio-windows-x64.exe"
        registry.QueryValueEx.return_value = (list2cmdline([old]), registry.REG_SZ)
        with (patch.dict(sys.modules, {"winreg": registry}), patch.object(sys, "platform", "win32"),
              patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", new)):
            with patch.object(sys, "executable", r"C:\Downloads\Folio-windows-x64.exe"):
                startup.upgrade_login_item()
            registry.SetValueEx.assert_not_called()
            startup.upgrade_login_item()
            self.assertEqual(registry.SetValueEx.call_args.args[1:], (
                startup.WINDOWS_ENTRY, 0, registry.REG_SZ, list2cmdline([new])))
            self.assertEqual(registry.DeleteValue.call_args.args[1], startup.LEGACY_ENTRY)
