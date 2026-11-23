"""Focused macOS text controls via Accessibility. All screen coordinates are in points."""

from __future__ import annotations

import math
import os
import time

import AppKit
import CoreFoundation as cf
import HIServices as ax

from whitedot.types import Rect, Target


def _attribute(element, name):
    error, value = ax.AXUIElementCopyAttributeValue(element, name, None)
    return value if error == ax.kAXErrorSuccess else None


def _parameter(element, name, parameter):
    error, value = ax.AXUIElementCopyParameterizedAttributeValue(element, name, parameter, None)
    return value if error == ax.kAXErrorSuccess else None


def _unpack(value, kind):
    if value is None or cf.CFGetTypeID(value) != ax.AXValueGetTypeID():
        return None
    ok, result = ax.AXValueGetValue(value, kind, None)
    return result if ok else None


def _range(start, length):
    return ax.AXValueCreate(ax.kAXValueTypeCFRange, (start, length))


def _utf16_range(text, start, end):
    if not 0 <= start < end <= len(text):
        return None
    return (len(text[:start].encode("utf-16-le")) // 2,
            len(text[start:end].encode("utf-16-le")) // 2)


def _selection_after_edit(selection, interval, added):
    location, removed = interval
    def adjust(point):
        if point <= location:
            return point
        if point >= location + removed:
            return point + added - removed
        return location + added

    start, length = selection
    after = adjust(start)
    return _range(after, adjust(start + length) - after)


def _settable(element, name):
    error, yes = ax.AXUIElementIsAttributeSettable(element, name, None)
    return error == ax.kAXErrorSuccess and yes


def _is_editor(element):
    role = _attribute(element, "AXRole")
    if role not in ("AXTextField", "AXTextArea", "AXComboBox", "AXGroup"):
        return False
    subrole = str(_attribute(element, "AXSubrole") or "").lower()
    if "secure" in subrole or "password" in subrole or _attribute(element, "AXProtectedContent"):
        return False
    enabled = _attribute(element, "AXEnabled")
    if enabled is not None and not enabled:
        return False
    editable = _attribute(element, "AXEditable")
    if editable is None:
        editable = _attribute(element, "AXIsEditable")
    if editable is not None:
        return bool(editable)
    # Generic groups can contain an entire web page. Require an explicit editor flag.
    return role != "AXGroup" and (
        _settable(element, "AXSelectedText") or _settable(element, "AXValue")
    )


def _text(element):
    value = _attribute(element, "AXValue")
    if isinstance(value, str):
        return str(value)
    # Some WebKit contenteditable elements only expose parameterized text.
    n = _attribute(element, "AXNumberOfCharacters")
    if not isinstance(n, int) or n < 0:
        return None
    if n == 0:
        return ""
    value = _parameter(element, "AXStringForRange", _range(0, n))
    return str(value) if isinstance(value, str) else None


def _rect(x, y, w, h):
    if all(math.isfinite(a) for a in (x, y, w, h)) and w > 0 and h > 0:
        return Rect(float(x), float(y), float(w), float(h))
    return None


def _frame(element):
    pos = _unpack(_attribute(element, "AXPosition"), ax.kAXValueTypeCGPoint)
    if pos is None:
        return None
    size = _unpack(_attribute(element, "AXSize"), ax.kAXValueTypeCGSize)
    return _rect(*pos, *size) if size is not None else None


def _intersection(a, b):
    x, y = max(a.x, b.x), max(a.y, b.y)
    return _rect(x, y, min(a.x + a.w, b.x + b.w) - x, min(a.y + a.h, b.y + b.h) - y)


def _bounds_for_range(element, location, length):
    value = _parameter(element, "AXBoundsForRange", _range(location, length))
    frame = _unpack(value, ax.kAXValueTypeCGRect)
    if frame is None:
        return None
    origin, size = frame
    return _rect(*origin, *size)


def _row_rects(element, location, length, first_length):
    # Single-line errors take just one or two geometry queries. A wrapped phrase
    # needs separate screen fragments or its bounding box covers unrelated text.
    block = _bounds_for_range(element, location, length)
    if block is None:
        return []
    if length == first_length:
        return [block]
    first = _bounds_for_range(element, location, first_length)
    if first is not None and block.h <= first.h * 1.4:
        return [block]
    first_line = _parameter(element, "AXLineForIndex", location)
    last_line = _parameter(element, "AXLineForIndex", location + length - 1)
    if not isinstance(first_line, int) or not isinstance(last_line, int):
        return []
    rows = []
    for line in range(first_line, last_line + 1):
        val = _parameter(element, "AXRangeForLine", line)
        interval = _unpack(val, ax.kAXValueTypeCFRange)
        if interval is None:
            return []
        line_start, line_length = interval
        start = max(location, line_start)
        end = min(location + length, line_start + line_length)
        if end > start:
            row = _bounds_for_range(element, start, end - start)
            if row is not None:
                rows.append(row)
    return rows


def _rich_rows(element, text, start, end):
    # Chromium exposes formatted contenteditable text as AXStaticText runs.
    # Align the runs to the exact field snapshot before using relative offsets.
    pending = list(reversed(_attribute(element, "AXChildren") or ()))
    pos, visited = 0, 0
    rows = []
    while pending and pos < end and visited < 160:
        node = pending.pop()
        visited += 1
        role = _attribute(node, "AXRole")
        if role in ("AXGroup", "AXLink", "AXParagraph", "AXHeading", "AXList", "AXListItem"):
            pending.extend(reversed(_attribute(node, "AXChildren") or ()))
            continue
        if role != "AXStaticText":
            return []
        value = _attribute(node, "AXValue")
        if not isinstance(value, str) or not value:
            continue
        offset = text.find(value, pos)
        if offset < 0 or text[pos:offset].strip():
            return []
        pos = offset + len(value)
        left, right = max(start, offset), min(end, pos)
        if left < right:
            loc, n = _utf16_range(value, left - offset, right - offset)
            part = _row_rects(node, loc, n, 2 if ord(text[left]) > 0xffff else 1)
            if not part:
                return []
            rows.extend(part)
    return rows if pos >= end else []


class MacAdapter:
    def __init__(self):
        self._pid = None
        self._app_element = None
        self._element = None
        self._generation = 0

    def permission(self, prompt=False):
        if prompt:
            return bool(ax.AXIsProcessTrustedWithOptions({ax.kAXTrustedCheckOptionPrompt: True}))
        return bool(ax.AXIsProcessTrusted())

    def _front(self):
        return AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()

    def _focus(self):
        front = self._front()
        if front is None:
            return None
        pid = front.processIdentifier()
        if pid == os.getpid():
            return None
        if self._pid != pid:
            self._pid = pid
            self._app_element = ax.AXUIElementCreateApplication(pid)
            ax.AXUIElementSetMessagingTimeout(self._app_element, 0.20)
            # Electron and Chromium render their full editor accessibility trees on demand.
            bundle = str(front.bundleIdentifier() or "").lower()
            if any(name in bundle for name in ("codex", "chrome", "chromium", "edgemac", "brave",
                                                "opera", "vscodium", "vscode", "atlas", "vivaldi")):
                ax.AXUIElementSetAttributeValue(self._app_element, "AXManualAccessibility", True)
                ax.AXUIElementSetAttributeValue(self._app_element, "AXEnhancedUserInterface", True)
        element = _attribute(self._app_element, "AXFocusedUIElement")
        if element is None:
            return None
        ax.AXUIElementSetMessagingTimeout(element, 0.20)
        return pid, str(front.localizedName() or front.bundleIdentifier() or "Application"), element

    def capture(self):
        current = self._focus() if self.permission() else None
        if current is None:
            self._element = None
            return None
        pid, name, element = current
        if not _is_editor(element):
            self._element = None
            return None
        bounds = _frame(element)
        if bounds is None:
            self._element = None
            return None
        text = _text(element)
        if text is None:
            self._element = None
            return None
        if self._element is None or not cf.CFEqual(self._element, element):
            self._generation += 1
        self._element = element
        return Target(f"mac:{pid}:{self._generation}", text, name, bounds)

    def _current(self, target):
        if self._element is None or self._pid is None:
            return None
        if target.token != f"mac:{self._pid}:{self._generation}":
            return None
        current = self._focus() if self.permission() else None
        if current is None or not cf.CFEqual(current[2], self._element):
            return None
        element = current[2]
        if not _is_editor(element) or _text(element) != target.text:
            return None
        return element

    def rects(self, target, start, end):
        interval = _utf16_range(target.text, start, end)
        if interval is None:
            return []
        element = self._current(target)
        if element is None:
            return []
        bounds = _frame(element)
        if bounds is None:
            return []
        window = _attribute(element, "AXWindow")
        window_frame = _frame(window) if window is not None else None
        if window_frame is not None:
            bounds = _intersection(bounds, window_frame)
            if bounds is None:
                return []
        first_length = 2 if ord(target.text[start]) > 0xffff else 1
        visible = []
        rows = _row_rects(element, *interval, first_length)
        if not rows:
            rows = _rich_rows(element, target.text, start, end)
        for row in rows:
            clipped = _intersection(row, bounds)
            # A partly hidden line must not acquire an underline on the viewport edge.
            if clipped is not None and row.y + row.h <= bounds.y + bounds.h + 1:
                visible.append(clipped)
        return visible

    def replace(self, target, start, end, replacement):
        interval = _utf16_range(target.text, start, end)
        if interval is None:
            return False
        element = self._current(target)
        if element is None:
            return False
        expected = target.text[:start] + replacement + target.text[end:]
        role = _attribute(element, "AXRole")
        children = _attribute(element, "AXChildren")
        is_atomic_web_field = (
            _attribute(element, "ChromeAXNodeId") is not None
            and role in ("AXTextField", "AXTextArea")
            and children is not None and len(children) == 0
            and _settable(element, "AXValue")
        )
        previous_selection = None
        if is_atomic_web_field:
            # Chromium can acknowledge AXSelectedText writes without applying them.
            # Its atomic input/textarea controls expose a plain value and no text runs.
            if self._current(target) is None:
                return False
            previous_selection = _unpack(_attribute(element, "AXSelectedTextRange"), ax.kAXValueTypeCFRange)
            error = ax.AXUIElementSetAttributeValue(element, "AXValue", expected)
        else:
            if not _settable(element, "AXSelectedTextRange"):
                return False
            error = ax.AXUIElementSetAttributeValue(element, "AXSelectedTextRange", _range(*interval))
            if error != ax.kAXErrorSuccess or self._current(target) is None:
                return False
            selected = _unpack(_attribute(element, "AXSelectedTextRange"), ax.kAXValueTypeCFRange)
            if selected is None or tuple(selected) != interval:
                return False
            if _attribute(element, "AXSelectedText") != target.text[start:end]:
                return False
            error, names = ax.AXUIElementCopyParameterizedAttributeNames(element, None)
            marker = _attribute(element, "AXSelectedTextMarkerRange")
            if (error == ax.kAXErrorSuccess and "AXTextOperation" in names and marker is not None
                    and _parameter(element, "AXStringForTextMarkerRange", marker) == target.text[start:end]):
                error, _ = ax.AXUIElementCopyParameterizedAttributeValue(
                    element, "AXTextOperation", {
                        "AXTextOperationMarkerRanges": [marker],
                        "AXTextOperationType": "TextOperationReplacePreserveCase",
                        "AXTextOperationReplacementString": replacement,
                    }, None)
            elif _settable(element, "AXSelectedText"):
                error = ax.AXUIElementSetAttributeValue(element, "AXSelectedText", replacement)
            else:
                return False
        if error != ax.kAXErrorSuccess:
            return False
        # Chromium applies accessibility actions asynchronously. Confirm the value
        # on the addressed control. Never post a keystroke or replace rich markup.
        for attempt in range(6):
            if attempt:
                time.sleep(0.02)
            if not _is_editor(element):
                return False
            value = _text(element)
            if value == expected:
                if previous_selection is not None and _settable(element, "AXSelectedTextRange"):
                    current = self._focus()
                    if current and cf.CFEqual(current[2], element):
                        added = len(replacement.encode("utf-16-le")) // 2
                        restored = _selection_after_edit(previous_selection, interval, added)
                        ax.AXUIElementSetAttributeValue(element, "AXSelectedTextRange", restored)
                return True
            if value != target.text:
                return False
        return False
