"""WhiteDot desktop entry point."""
import hashlib
import sys
import time
import tempfile
from pathlib import Path

from PySide6.QtCore import QIODevice, QLockFile, QStandardPaths
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox

from whitedot import __version__
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
        issue = Issue(2, 5, "teh", ("the",), "Spelling")
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


def activate_existing(name):
    # The lock can be acquired a moment before the first process starts listening.
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        socket = QLocalSocket()
        socket.connectToServer(name, QIODevice.ReadOnly)
        if socket.waitForConnected(150):
            socket.disconnectFromServer()
            return True
        time.sleep(.05)
    return False


def listen_for_launch(name, controller):
    server = QLocalServer(controller)
    server.setSocketOptions(QLocalServer.UserAccessOption)
    QLocalServer.removeServer(name)  # Caller holds the per-user instance lock.
    def show_existing():
        while server.hasPendingConnections():
            peer = server.nextPendingConnection()
            peer.close()
            peer.deleteLater()
        controller.show_editor()
    server.newConnection.connect(show_existing)
    server.listen(name)
    return server


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("WhiteDot")
    app.setOrganizationName("WhiteDot")
    app.setApplicationVersion(__version__)
    app.setQuitOnLastWindowClosed(False)
    if "--self-test" in sys.argv:
        return smoke(app)
    runtime = Path(QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation))
    try:
        runtime.mkdir(parents=True, exist_ok=True)
    except OSError:
        QMessageBox.critical(None, "WhiteDot", "WhiteDot cannot open its settings folder. Check your account permissions.")
        return 1
    name = "WhiteDot-" + hashlib.sha256(str(runtime).encode()).hexdigest()[:16]
    lock = QLockFile(str(runtime / "instance.lock"))
    if not lock.tryLock(0):
        if lock.error() != QLockFile.LockFailedError:
            QMessageBox.critical(None, "WhiteDot", "WhiteDot could not create its startup lock. Check your account permissions.")
            return 1
        if not activate_existing(name):
            QMessageBox.information(None, "WhiteDot is already running",
                                    "Click the white dot or open WhiteDot from the tray. "
                                    "If you just upgraded, quit the previous version and open WhiteDot again.")
        return 0
    try:
        prefs = Settings()
        controller = Controller(app, prefs)
    except (StorageError, RuntimeError) as exc:
        QMessageBox.critical(None, "WhiteDot", str(exc))
        return 1
    server = listen_for_launch(name, controller)
    try:
        return app.exec()
    finally:
        server.close()
        lock.unlock()


if __name__ == "__main__":
    sys.exit(main())
