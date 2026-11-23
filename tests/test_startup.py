import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from whitedot import startup


class StartupTests(unittest.TestCase):
    def test_macos_login_item_can_be_enabled_and_removed(self):
        cmd = ["/Applications/My Tools/WhiteDot.app/Contents/MacOS/WhiteDot"]
        with tempfile.TemporaryDirectory() as tmp, patch.object(startup.sys, "platform", "darwin"):
            dest = Path(tmp, "LaunchAgents", startup.LABEL + ".plist")
            with patch.object(startup, "PLIST", dest), patch.object(startup, "launch_command", return_value=cmd):
                self.assertFalse(startup.enabled())
                startup.set_enabled(True)
                self.assertTrue(startup.enabled())
                config = plistlib.loads(dest.read_bytes())
                self.assertEqual(config["ProgramArguments"], cmd)
                self.assertTrue(config["RunAtLoad"])
                moved_cmd = ["/Applications/WhiteDot.app/Contents/MacOS/WhiteDot"]
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
        cmd = [r"C:\New Folder\WhiteDot.exe"]
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
            registry.DeleteValue.assert_called_once()
