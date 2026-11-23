"""WhiteDot desktop entry point."""
import os
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QLockFile, QStandardPaths
from PySide6.QtWidgets import QApplication, QMessageBox

from whitedot.app import Controller
from whitedot.settings import Settings, StorageError
from whitedot.types import Issue


def make_adapter():
    if sys.platform == "darwin":
        from whitedot.platforms.macos import MacAdapter
        return MacAdapter()
    if sys.platform == "win32":
        from whitedot.platforms.windows import WinAdapter
        return WinAdapter()
    raise RuntimeError("WhiteDot 需要 macOS 或 Windows。")


def smoke(app):
    """Exercise the installed native imports and both editor states using only fixtures."""
    adapter = make_adapter()
    adapter.permission()
    from whitedot.provider import PRESETS, Provider
    from whitedot.settings import _vault
    _vault()  # Check bundled keyring backend imports without looking up a credential.
    Provider(PRESETS["DeepSeek"], "offline-placeholder")
    class EmptyFocus:
        def capture(self):
            return None
        def permission(self, prompt=False):
            return True

    with tempfile.TemporaryDirectory() as tmp:
        ctrl = Controller(app, Settings(Path(tmp) / "prefs.json"), EmptyFocus(), testing=True)
        ctrl.open_dot()
        assert ctrl.panel is ctrl.manual and not ctrl.manual.original_copy.isEnabled()
        ctrl.manual.editor.setPlainText("😀 teh")
        issue = Issue(2, 5, "teh", ("the",), "拼写错误")
        ctrl.issues = [issue]
        ctrl.manual.editor.mark(ctrl.issues)
        marks = ctrl.manual.editor.extraSelections()
        assert marks[0].cursor.selectedText() == "teh"
        ctrl.apply(issue, "the", ctrl.version)
        assert ctrl.manual.editor.toPlainText() == "😀 the"
        assert ctrl.manual.original_copy.isEnabled()
        ctrl.manual.result.setPlainText("Fixture.")
        assert ctrl.manual.result_copy.isEnabled()
        ctrl.close_panel()
        ctrl.dot.hide()
        app.processEvents()
    return 0


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("WhiteDot")
    app.setOrganizationName("WhiteDot")
    app.setQuitOnLastWindowClosed(False)
    if "--self-test" in sys.argv:
        return smoke(app)
    runtime = Path(QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation))
    runtime.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(runtime / "instance.lock"))
    if not lock.tryLock(0):
        return 0
    try:
        prefs = Settings()
        controller = Controller(app, prefs, make_adapter())
    except (StorageError, RuntimeError) as exc:
        QMessageBox.critical(None, "WhiteDot", str(exc))
        return 1
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
