"""Choose the paired browser's DOM field, otherwise use the native editor."""
import sys


def foreground_browser():
    if sys.platform == "darwin":
        from AppKit import NSWorkspace
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        bundle = str(app.bundleIdentifier() or "").lower() if app else ""
        if bundle == "com.google.chrome" or bundle.startswith("com.google.chrome."):
            return "chrome"
        if bundle == "com.microsoft.edgemac" or bundle.startswith("com.microsoft.edgemac."):
            return "edge"
    elif sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        from .platforms.windows import _process_name
        user = ctypes.windll.user32
        user.GetForegroundWindow.restype = wintypes.HWND
        user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(user.GetForegroundWindow(), ctypes.byref(pid))
        if pid.value:
            return {"chrome.exe": "chrome", "msedge.exe": "edge"}.get(_process_name(pid.value).lower())
    return None
