"""WhiteDot desktop entry point."""
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QLockFile, QStandardPaths
from PySide6.QtWidgets import QApplication, QMessageBox

from whitedot.app import Controller
from whitedot.settings import Settings, StorageError
from whitedot.types import Issue


def smoke(app):
    """Exercise the packaged manual editor with a fixture and no network requests."""
    from whitedot.provider import PRESETS, Provider
    from whitedot.settings import _vault
    _vault()  # Verify that the bundled system keyring imports without reading a credential.
    Provider(PRESETS["DeepSeek"], "offline-placeholder")

    with tempfile.TemporaryDirectory() as tmp:
        ctrl = Controller(app, Settings(Path(tmp) / "prefs.json"), testing=True)
        ctrl.dot.clicked.emit()
        panel = ctrl.panel
        assert panel.isVisible() and not panel.original_copy.isEnabled()
        panel.editor.setPlainText("😀 teh")
        issue = Issue(2, 5, "teh", ("the",), "拼写错误")
        ctrl.issues = [issue]
        panel.editor.mark(ctrl.issues)
        selections = panel.editor.extraSelections()
        assert selections[0].cursor.selectedText() == issue.original
        ctrl.apply(issue, "the", ctrl.version)
        assert panel.editor.toPlainText() == "😀 the"
        assert panel.original_copy.isEnabled()
        ctrl.dot.clicked.emit()
        assert not panel.isVisible()
        ctrl.dot.clicked.emit()
        assert panel.editor.toPlainText() == "😀 the"
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
        controller = Controller(app, prefs)
    except (StorageError, RuntimeError) as exc:
        QMessageBox.critical(None, "WhiteDot", str(exc))
        return 1
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
