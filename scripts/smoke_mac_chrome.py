"""Run on macOS with Google Chrome: python -m scripts.smoke_mac_chrome."""

from pathlib import Path
import subprocess
import tempfile
import time

import AppKit
import Foundation

from whitedot.platforms.macos import MacAdapter, _attribute, ax


CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
HTML = """<!doctype html><html lang="en"><meta charset="utf-8"><title>WhiteDot test</title>
<style>body{font:20px sans-serif;padding:24px}input,textarea,div{width:440px;font:inherit;margin:10px}</style>
<p>WhiteDot macOS Accessibility test</p>
<input id="single" value="😀 input teh sample" autofocus><br>
<textarea id="multi">😀 textarea teh sample</textarea><br>
<div id="rich" role="textbox" contenteditable>😀 editor <b>teh</b> sample</div>
<input id="password" type="password" value="dummy" autocomplete="off">
<script>
const fields = ['single', 'multi', 'rich', 'password'].map(id => document.getElementById(id));
let current = 0, richSince = 0;
fields[0].focus();
setInterval(() => {
  if (current >= 3) return;
  const el = fields[current];
  const corrected = (el.value || el.innerText).includes('the sample');
  if (current === 2 && corrected && el.querySelector('b')?.textContent !== 'the') return;
  if (corrected || (current === 2 && Date.now() - richSince > 10000)) {
    fields[++current].focus();
    if (current === 2) richSince = Date.now();
  }
}, 180);
</script>"""


def wait_for(read, seconds=12):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        result = read()
        if result:
            return result
        time.sleep(0.1)
    raise AssertionError("Timed out waiting for the Chrome fixture")


class FixtureAdapter(MacAdapter):
    """Limit all focus reads to the isolated browser, even if the desktop changes."""

    def __init__(self, pid):
        super().__init__()
        self.fixture_pid = pid
        self.fixture = ax.AXUIElementCreateApplication(pid)
        ax.AXUIElementSetMessagingTimeout(self.fixture, .15)

    def _front(self):
        run_loop = Foundation.NSRunLoop.currentRunLoop()
        run_loop.runUntilDate_(Foundation.NSDate.dateWithTimeIntervalSinceNow_(.005))
        app = super()._front()
        return app if app and app.processIdentifier() == self.fixture_pid else None

    def acquire(self):
        if not self._front() and _attribute(self.fixture, "AXWindows"):
            ax.AXUIElementSetAttributeValue(self.fixture, "AXFrontmost", True)
        return self._front()


def check(chrome):
    adapter = FixtureAdapter(chrome.pid)
    wait_for(adapter.acquire, seconds=18)
    previous = None
    for label in ("input", "textarea", "editor"):
        expected = f"😀 {label} teh sample"
        def current_field():
            current = adapter.capture()
            return current if current and current.text == expected else None
        target = wait_for(current_field)
        if previous:
            assert not adapter.replace(previous, 0, 1, "stale"), "stale suggestion accepted"
        start = expected.index("teh")
        marks = wait_for(lambda: adapter.rects(target, start, start + 3))
        assert all(0 < row.w < target.bounds.w and row.h > 0 for row in marks), marks
        changed = adapter.replace(target, start, start + 3, "the")
        if not changed:
            assert label == "editor" and current_field(), "unexpected failure applying correction"
        action = "replaced" if changed else "kept original rich text (host lacks range write)"
        print(f"{label}: captured, measured and {action}", flush=True)
        previous = target

    def password_has_focus():
        focus = adapter._focus()
        return focus is not None and _attribute(focus[2], "AXSubrole") == "AXSecureTextField"
    wait_for(password_has_focus)
    assert adapter.capture() is None
    print("password: excluded", flush=True)


def main():
    if not MacAdapter().permission():
        raise SystemExit("Enable Accessibility for this terminal / Python and run again.")
    with tempfile.TemporaryDirectory(prefix="WhiteDot-AX-") as folder:
        page = Path(folder, "fixture.html")
        page.write_text(HTML, encoding="utf-8")
        chrome = subprocess.Popen(
            [CHROME, "--user-data-dir=" + str(Path(folder, "profile")), "--no-first-run",
             "--no-default-browser-check", "--disable-background-networking", "--disable-sync",
             "--disable-extensions", "--use-mock-keychain", "--password-store=basic", "--app=" + page.as_uri()],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            check(chrome)
        finally:
            chrome.terminate()
            try:
                chrome.wait(timeout=8)
            except subprocess.TimeoutExpired:
                chrome.kill()
                chrome.wait()


if __name__ == "__main__":
    main()
