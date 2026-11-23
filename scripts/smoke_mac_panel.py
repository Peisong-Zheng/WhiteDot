"""Opt-in macOS desktop test. Run with python -m scripts.smoke_mac_panel."""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import AppKit
import Quartz
import objc
from PySide6.QtCore import QByteArray, QBuffer, QIODevice
from PySide6.QtWidgets import QApplication, QPushButton

from whitedot.app import Controller
from whitedot.platforms.macos import MacAdapter
from whitedot.settings import Settings
from whitedot.types import Issue

ORIGINAL = "I saw teh cat."
CORRECTED = "I saw the cat."


def show_fixture():
    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyRegular)
    window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        ((180, 280), (520, 180)), AppKit.NSWindowStyleMaskTitled, AppKit.NSBackingStoreBuffered, False
    )
    window.setTitle_("WhiteDot input fixture")
    field = AppKit.NSTextField.alloc().initWithFrame_(((20, 80), (470, 50)))
    field.setStringValue_(ORIGINAL)
    window.contentView().addSubview_(field)
    window.makeKeyAndOrderFront_(None)
    window.makeFirstResponder_(field)
    app.activateIgnoringOtherApps_(True)
    app.run()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


class FixtureOnly(MacAdapter):
    def __init__(self, pid):
        super().__init__()
        self.fixture_pid = pid

    def _front(self):
        front = super()._front()
        return front if front and front.processIdentifier() == self.fixture_pid else None

    def has_original(self):
        target = self.capture()
        return target is not None and target.text == ORIGINAL


class LocalModel:
    def check(self, text):
        require(text in (ORIGINAL, CORRECTED), "Unexpected input passed to the test model")
        return [Issue(6, 9, "teh", ("the",), "拼写错误")] if text == ORIGINAL else []

    def rewrite(self, text):
        require(text == ORIGINAL, "Unexpected rewrite source")
        return CORRECTED


class SynchronousJobs:
    def run(self, operation, done):
        done(operation(), "")


def pump(seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(.008)


def click(widget, adapter):
    pump(.4)
    require(widget.isVisible() and widget.isEnabled(), "Test control unavailable")
    point = widget.mapToGlobal(widget.rect().center())
    location = (point.x(), point.y())
    cocoa_point = (point.x(), AppKit.NSScreen.screens()[0].frame().size.height - point.y())
    native_view = objc.objc_object(c_void_p=int(widget.window().winId()))
    number = native_view.window().windowNumber()
    def safe_hit():
        hit = AppKit.NSWindow.windowNumberAtPoint_belowWindowWithWindowNumber_(cocoa_point, 0)
        return number > 0 and number == hit and adapter.has_original()

    down = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventLeftMouseDown, location, Quartz.kCGMouseButtonLeft)
    up = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventLeftMouseUp, location, Quartz.kCGMouseButtonLeft)
    require(safe_hit(), "Another field or window has taken the test click point")
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, down)
    try:
        pump(.06)
        require(safe_hit(), "Window or field changed during the test click")
    except BaseException:
        # Finish the interrupted gesture in the test process without clicking a different app.
        Quartz.CGEventPostToPid(os.getpid(), up)
        raise
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)
    pump(.1)


def save_panel(widget, path):
    data = QByteArray()
    stream = QBuffer(data)
    require(stream.open(QIODevice.OpenModeFlag.WriteOnly), "Cannot create PNG buffer")
    require(widget.grab().save(stream, "PNG"), "Cannot render the rewrite panel")
    with path.open("xb") as output:
        output.write(bytes(data))


def exercise(controller, adapter, fixture, screenshot):
    for _ in range(45):
        pump(.12)
        require(fixture.poll() is None, "The fixture closed before the test completed")
        if adapter.has_original():
            break
        helper = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(fixture.pid)
        if helper:
            helper.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps)
    controller.tick()
    require(controller.current and controller.current.text == ORIGINAL, "Could not focus the test field")
    controller.run_check()

    click(controller.dot, adapter)
    pump(.2)
    require(controller.panel is controller.external, "The dot lost the external field")
    require(controller.external.result.toPlainText() == CORRECTED, "Missing rewrite")
    controller.tick()
    require(controller.panel is controller.external and adapter.has_original(), "Rewrite moved input focus")
    print("Dot click opened the rewrite and retained the original text and focus.", flush=True)
    if screenshot:
        save_panel(controller.external, screenshot)

    pump(.65)
    click(controller.dot, adapter)
    require(controller.panel is None, "The second dot click did not close the panel")
    controller.tick()
    controller.run_check()
    marks = [mark for mark in controller.marks if mark.isVisible()]
    require(bool(marks), "No clickable underline appeared below the fixture word")
    click(marks[0], adapter)
    require(controller.bubble and controller.bubble.isVisible(), "Suggestion popup did not appear")
    candidate = next((b for b in controller.bubble.findChildren(QPushButton) if b.text() == "the"), None)
    require(candidate is not None, "The expected replacement was missing")
    click(candidate, adapter)
    pump(.2)
    target = adapter.capture()
    require(target and target.text == CORRECTED, "Correction did not reach the fixture")
    print("Underline click and suggestion acceptance updated the native text field.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--screenshot", type=Path, help="Save the rewrite panel PNG to a new file")
    args = parser.parse_args()
    if args.fixture:
        show_fixture()
        return
    require(MacAdapter().permission(), "Enable Accessibility for this terminal / Python and run again")
    if args.screenshot:
        require(not args.screenshot.exists() and args.screenshot.parent.is_dir(), "Choose a new PNG path in an existing directory")
    workspace = AppKit.NSWorkspace.sharedWorkspace()
    previous = workspace.frontmostApplication()
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    fixture = subprocess.Popen([sys.executable, "-m", "scripts.smoke_mac_panel", "--fixture"])
    try:
        with tempfile.TemporaryDirectory(prefix="WhiteDot-panel-") as folder:
            adapter = FixtureOnly(fixture.pid)
            controller = Controller(app, Settings(Path(folder) / "prefs.json"), adapter,
                                    SynchronousJobs(), LocalModel(), testing=True)
            exercise(controller, adapter, fixture, args.screenshot)
    finally:
        for window in app.topLevelWidgets():
            window.hide()
        current = workspace.frontmostApplication()
        restore = current and current.processIdentifier() in (os.getpid(), fixture.pid)
        fixture.terminate()
        try:
            fixture.wait(timeout=5)
        except subprocess.TimeoutExpired:
            fixture.kill()
            fixture.wait()
        if restore and previous:
            previous.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps)
        app.quit()


if __name__ == "__main__":
    main()
