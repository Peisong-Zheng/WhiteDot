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


def smoke(app):
    """Exercise the packaged manual editor with a fixture and no network requests."""
    from whitedot.settings import _account

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "settings.json"
        prefs = Settings(path)
        prefs.set("accounts", [_account(prefs.config)])
        assert prefs.needs_key_reentry() and not prefs.has_key()
        ctrl = Controller(app, prefs, testing=True)
        ctrl.open_dot()
        panel = ctrl.panel
        assert panel.isVisible() and not panel.original_copy.isEnabled()
        assert panel.context_action.isHidden() and panel.status.isHidden()

        # Use the editor's real local checker before any provider exists.
        panel.editor.setPlainText("😀 teh ")
        deadline = time.monotonic() + 2
        while not ctrl.issues and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.005)
        issue = next(i for i in ctrl.issues if i.original == "teh" and "the" in i.suggestions)
        assert any(s.cursor.selectedText() == "teh" for s in panel.editor.extraSelections())
        ctrl.apply(issue, "the", ctrl.version)
        assert panel.editor.toPlainText() == "😀 the " and panel.original_copy.isEnabled()

        next(a for a in ctrl.menu.actions() if a.text() == "AI settings…").trigger()
        assert ctrl.dialog.key.isVisible() and not ctrl.dialog.key.text()
        ctrl.dialog.reject()
        ctrl.close_panel()
        ctrl.open_dot()
        assert panel.editor.toPlainText() == "😀 the "
        ctrl.close_panel()
        ctrl.dot.hide()

        prefs.save_provider(prefs.config, "offline-fixture")
        restored = Settings(path)
        assert restored.has_key() and restored.get_key() == "offline-fixture"
        assert not restored.needs_key_reentry()
        ctrl = Controller(app, restored, testing=True)
        ctrl.configure()
        dialog = ctrl.dialog
        assert dialog.saved_key.isVisible() and dialog.key.isHidden() and not dialog.key.text()
        dialog.change_key.click()
        assert dialog.key.isVisible() and not dialog.key.text()
        dialog.reject()
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
    # An older running version holds the same lock but must not open its editor
    # in response to someone double-clicking the newly downloaded application.
    name = f"Folio-{__version__}-" + hashlib.sha256(str(runtime).encode()).hexdigest()[:16]
    lock = QLockFile(str(runtime / "instance.lock"))
    if not lock.tryLock(0):
        if lock.error() != QLockFile.LockFailedError:
            QMessageBox.critical(None, "Folio", "Folio could not create its startup lock. Check your account permissions.")
            return 1
        if not activate_existing(name):
            QMessageBox.information(None, "An editor is already running",
                                    f"To start Folio {__version__}, copy any draft you want to keep, "
                                    "quit the running editor from the dot’s menu, then open Folio again.")
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
