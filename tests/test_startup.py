import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
                startup.set_enabled(False)
                self.assertFalse(startup.enabled())
