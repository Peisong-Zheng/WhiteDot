"""Run isolated Chrome's headless DOM test without loading a user's profile."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


chrome = os.environ.get("CHROME_BIN") or shutil.which("google-chrome") or shutil.which("chromium")
if not chrome:
    chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
with tempfile.TemporaryDirectory(prefix="whitedot-dom-") as profile:
    completed = subprocess.run(
        [chrome, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
         "--disable-background-networking", "--disable-sync", "--user-data-dir=" + profile,
         "--allow-file-access-from-files", "--virtual-time-budget=8000", "--dump-dom",
         Path(__file__).with_name("dom.html").resolve().as_uri()],
        capture_output=True, text=True, timeout=40,
    )
result = re.search(r'<pre id="result">([^<]*)</pre>', completed.stdout)
if completed.returncode or not result or result.group(1) != "PASS":
    raise SystemExit("DOM test failed: " + (result.group(1) if result else completed.stderr[-400:]))
print("PASS: input range and write, stale revisions, scrolled textarea, rich text, protected inputs and IME")
