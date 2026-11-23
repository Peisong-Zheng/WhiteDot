"""Create Qt tool panels with AppKit's nonactivating style from initialization."""
from contextlib import contextmanager
from threading import local

import AppKit
import objc

_state = local()
_installed = False


def _install():
    global _installed
    if _installed:
        return
    # AppKit applies the WindowServer activation behavior at construction.
    # Qt creates its NSPanel inside QWidget.winId() and exposes the NSView
    # afterwards. Supplying the documented style in that short creation scope
    # prevents a click on an underline from changing the source application's focus.
    panel = AppKit.NSPanel
    method = panel.initWithContentRect_styleMask_backing_defer_screen_
    original = panel.instanceMethodForSelector_(method.selector)

    def initialize(obj, rect, style, backing, defer, screen):
        if getattr(_state, "nonactivating", False):
            style |= AppKit.NSWindowStyleMaskNonactivatingPanel
        return original(obj, rect, style, backing, defer, screen)

    objc.classAddMethods(panel, [objc.selector(initialize, selector=method.selector, signature=method.signature)])
    _installed = True


@contextmanager
def panel_creation(nonactivating):
    _install()
    previous = getattr(_state, "nonactivating", False)
    _state.nonactivating = nonactivating
    try:
        yield
    finally:
        _state.nonactivating = previous
