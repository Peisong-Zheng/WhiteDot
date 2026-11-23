"""Focused Windows UI Automation controls. Offsets at the adapter boundary are code points."""

from __future__ import annotations

import ctypes
import ntpath
import os
import time
from ctypes import wintypes
from functools import lru_cache

from ..types import Rect, Target


def _lf(value):
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _logical_rect(x, y, w, h):
    from PySide6.QtGui import QGuiApplication

    # Windows maps each monitor origin in physical pixels. Qt retains those
    # origins and scales distances inside each screen to device-independent units.
    best = None
    best_overlap = 0
    for screen in QGuiApplication.screens():
        geometry = screen.geometry()
        ratio = screen.devicePixelRatio()
        dx, dy = x - geometry.x(), y - geometry.y()
        width, height = geometry.width() * ratio, geometry.height() * ratio
        overlap = (max(0, min(dx + w, width) - max(dx, 0)) *
                   max(0, min(dy + h, height) - max(dy, 0)))
        rect = Rect(geometry.x() + dx / ratio, geometry.y() + dy / ratio, w / ratio, h / ratio)
        if 0 <= dx < width and 0 <= dy < height:
            return rect
        if overlap > best_overlap:
            best, best_overlap = rect, overlap
    return best


@lru_cache(maxsize=32)
def _process_name(pid):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
    ]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if handle:
        try:
            size = wintypes.DWORD(32768)
            path = ctypes.create_unicode_buffer(size.value)
            if kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
                return ntpath.basename(path.value)
        finally:
            kernel.CloseHandle(handle)
    return "Windows app"


def _text_range(document, text, start, end):
    """Find the requested occurrence, checking its prefix even for repeated words."""
    if not 0 <= start < end <= len(text):
        return None
    # Most providers count UIA characters like Python. Emoji, combining marks
    # and line endings can change the unit: compare actual provider text.
    candidate = document.Clone()
    candidate.MoveEndpointByRange(1, document, 0)  # collapse end to document start
    if start:
        candidate.MoveEndpointByUnit(1, 0, start)  # TextUnit_Character
    candidate.MoveEndpointByRange(0, candidate, 1)
    candidate.MoveEndpointByUnit(1, 0, end - start)
    prefix_text = _lf(text[:start])
    issue_text = _lf(text[start:end])

    def matches(span):
        prefix = document.Clone()
        prefix.MoveEndpointByRange(1, span, 0)
        return _lf(prefix.GetText(-1)) == prefix_text and _lf(span.GetText(-1)) == issue_text

    if matches(candidate):
        return candidate
    # An unusual Unicode character before this word may have moved one endpoint
    # by too many provider units. FindText supplies real provider boundaries.
    tail = document.Clone()
    for _ in range(24):
        found = tail.FindText(text[start:end], False, False)
        if not found:
            return None
        if matches(found):
            return found
        if found.CompareEndpoints(1, tail, 0) <= 0:
            return None
        tail.MoveEndpointByRange(0, found, 1)
    return None


class WinAdapter:
    """Call on the same thread as construction; UIA objects are apartment-affine."""

    def __init__(self):
        from comtypes import COMError
        from comtypes.client import CreateObject, GetModule

        self._errors = (COMError, OSError, ValueError, TypeError)
        try:
            # The release contains bindings generated against UIAutomationCore.
            from comtypes.gen import UIAutomationClient as api
        except ImportError:
            api = GetModule("UIAutomationCore.dll")
        self.api = api
        self._last_read = None
        self._read_at = 0.0
        self.automation = CreateObject(api.CUIAutomation8, interface=api.IUIAutomation2)
        self.automation.AutoSetFocus = False
        self.automation.ConnectionTimeout = 400
        self.automation.TransactionTimeout = 500
        self._user = ctypes.WinDLL("user32", use_last_error=True)
        self._user.GetForegroundWindow.restype = wintypes.HWND
        self._user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]

    def permission(self, prompt=False):
        # UIA is available to regular users within their interactive session.
        return True

    def _pattern(self, field, pattern_id, interface):
        try:
            pointer = field.GetCurrentPattern(pattern_id)
            return pointer.QueryInterface(interface) if pointer else None
        except self._errors:
            return None

    def _focused(self):
        api = self.api
        hwnd = self._user.GetForegroundWindow()
        pid = wintypes.DWORD()
        self._user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value or pid.value == os.getpid():
            return None
        field = self.automation.GetFocusedElement()
        if not field or not field.CurrentHasKeyboardFocus or not field.CurrentIsEnabled:
            return None
        if field.CurrentProcessId == os.getpid() or field.CurrentIsPassword or field.CurrentIsOffscreen:
            return None
        kind = field.CurrentControlType
        if kind not in (api.UIA_EditControlTypeId, api.UIA_DocumentControlTypeId, api.UIA_ComboBoxControlTypeId):
            return None
        value = self._pattern(field, api.UIA_ValuePatternId, api.IUIAutomationValuePattern)
        if value and value.CurrentIsReadOnly:
            return None
        pattern = self._pattern(field, api.UIA_TextPatternId, api.IUIAutomationTextPattern)
        document = pattern.DocumentRange if pattern else None
        if not value:
            # A focused browser document can expose the entire page. Only an
            # edit control or an explicit text box may enter the text-only path.
            role = (field.CurrentAriaRole or "").lower()
            if not document or (kind != api.UIA_EditControlTypeId and role not in ("textbox", "searchbox")):
                return None
            editable = document.GetAttributeValue(api.UIA_IsReadOnlyAttributeId)
            if editable is not False:
                return None
        coords = field.CurrentBoundingRectangle
        if coords.right <= coords.left or coords.bottom <= coords.top:
            return None
        bounds = _logical_rect(coords.left, coords.top, coords.right - coords.left, coords.bottom - coords.top)
        identity = field.GetRuntimeId()
        if not bounds or not identity:
            return None
        text = value.CurrentValue if value else document.GetText(-1)
        if not isinstance(text, str):
            return None
        token = f"{hwnd}/{field.CurrentProcessId}/" + ",".join(map(str, identity))
        target = Target(token, text, _process_name(pid.value), bounds)
        return target, field, value, document

    def capture(self) -> Target | None:
        try:
            self._last_read = self._focused()
            self._read_at = time.monotonic()
            return self._last_read[0] if self._last_read else None
        except self._errors:
            self._last_read = None
            return None  # control was destroyed, elevated, or its UIA provider timed out

    def rects(self, target: Target, start: int, end: int) -> list[Rect]:
        try:
            # The controller draws many issues immediately after a focus probe.
            # Reuse its COM handles only for positioning within this paint batch.
            # Replacement always acquires a fresh snapshot.
            if time.monotonic() - self._read_at > 0.25:
                self.capture()
            snapshot = self._last_read
            if not snapshot or snapshot[0].token != target.token or snapshot[0].text != target.text:
                return []
            if not snapshot[3]:
                return []
            span = _text_range(snapshot[3], target.text, start, end)
            if not span:
                return []
            coords = span.GetBoundingRectangles() or ()
            rects = []
            for x, y, w, h in zip(*[iter(coords)] * 4):
                if w > 0 and h > 0:
                    rect = _logical_rect(x, y, w, h)
                    if rect:
                        rects.append(rect)
            return rects
        except self._errors:
            return []

    def replace(self, target: Target, start: int, end: int, replacement: str) -> bool:
        if not 0 <= start < end <= len(target.text):
            return False
        try:
            snapshot = self._focused()
            if not snapshot or snapshot[0].token != target.token or snapshot[0].text != target.text:
                return False
            _, field, value, _ = snapshot
            if field.CurrentControlType != self.api.UIA_EditControlTypeId or not value:
                return False
            # Protect formatted editors: UIA Value.SetValue replaces an entire
            # plain-text value. An exposed child can carry formatting or embeds.
            if self.automation.ControlViewWalker.GetFirstChildElement(field):
                return False
            updated = target.text[:start] + replacement + target.text[end:]
            if not field.CurrentHasKeyboardFocus or value.CurrentValue != target.text:
                return False
            value.SetValue(updated)
            return value.CurrentValue == updated
        except self._errors:
            return False
