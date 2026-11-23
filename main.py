"""Folio desktop entry point."""
import hashlib
import sys
import time
import tempfile
from pathlib import Path

from PySide6.QtCore import QIODevice, QLockFile, QStandardPaths
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox

from whitedot import __version__, startup
from whitedot.app import Controller
from whitedot.settings import Settings, StorageError
from whitedot.types import Issue


def smoke(app):
    """Exercise the packaged manual editor with a fixture and no network requests."""
    from whitedot.provider import PRESETS, Provider
    from whitedot.settings import _account, _vault
    _vault()  # Verify that the bundled system keyring imports without reading a credential.
    Provider(PRESETS["DeepSeek"], "offline-placeholder")

    class OfflineSettings(Settings):
        def get_key(self, config=None):
            raise AssertionError("Browsing settings must not read a saved credential")

    with tempfile.TemporaryDirectory() as tmp:
        prefs = OfflineSettings(Path(tmp) / "prefs.json")
        prefs.set("accounts", [_account(prefs.config)])  # Old-format configured profile.
        ctrl = Controller(app, prefs, testing=True)
        ctrl.dot.clicked.emit()
        panel = ctrl.panel
        assert panel.isVisible() and not panel.original_copy.isEnabled()
        ctrl.configure()
        dialog = ctrl.dialog
        assert dialog.saved_key.isVisible() and dialog.key.isHidden() and not dialog.key.text()
        dialog.change_key.click()
        assert dialog.key.isVisible() and not dialog.key.text()
        dialog.reject()
        assert panel.isVisible()
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
    # Share the old per-user lock so an upgrade cannot leave two floating editors.
    app.setApplicationName("WhiteDot")
    app.setOrganizationName("WhiteDot")
    runtime = Path(QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation))
    app.setApplicationName("Folio")
    app.setOrganizationName("Folio")
    app.setApplicationDisplayName("Folio")
    app.setApplicationVersion(__version__)
    app.setQuitOnLastWindowClosed(False)
    if "--self-test" in sys.argv:
        return smoke(app)
    try:
        runtime.mkdir(parents=True, exist_ok=True)
    except OSError:
        QMessageBox.critical(None, "Folio", "Folio cannot open its settings folder. Check your account permissions.")
        return 1
    name = "Folio-" + hashlib.sha256(str(runtime).encode()).hexdigest()[:16]
    lock = QLockFile(str(runtime / "instance.lock"))
    if not lock.tryLock(0):
        if lock.error() != QLockFile.LockFailedError:
            QMessageBox.critical(None, "Folio", "Folio could not create its startup lock. Check your account permissions.")
            return 1
        if not activate_existing(name):
            QMessageBox.information(None, "An editor is already running",
                                    "If WhiteDot is open, quit it from its menu and open Folio again. "
                                    "If Folio is already open, click its floating dot to resume writing.")
        return 0
    try:
        prefs = Settings()
        controller = Controller(app, prefs)
    except (StorageError, RuntimeError) as exc:
        QMessageBox.critical(None, "Folio", str(exc))
        return 1
    try:
        startup.upgrade_login_item()
    except OSError:
        controller.notify("To update the login item, choose Open at login in the dot’s menu.")
    server = listen_for_launch(name, controller)
    try:
        return app.exec()
    finally:
        server.close()
        lock.unlock()


if __name__ == "__main__":
    sys.exit(main())
