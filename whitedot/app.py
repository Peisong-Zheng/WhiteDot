"""Manual proofreading, draft revisions and desktop controls."""
import sys
import threading

from PySide6.QtCore import QObject, QPoint, QTimer, Qt, Signal
from PySide6.QtGui import QCursor, QTextCursor
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMenu, QMessageBox, QSystemTrayIcon, QVBoxLayout)

from . import startup
from .privacy import input_status
from .provider import MAX_TEXT, PRESETS, Provider, ProviderConfig, ProviderError
from .settings import StorageError
from .windows_ui import Dot, Panel, STYLE, Suggestion, button, clamped, icon, raise_surface, utf16


class Jobs(QObject):
    """Deliver worker results on the GUI thread. Never print remote text or credentials."""
    done = Signal(int, object, str)

    def __init__(self):
        super().__init__()
        self.next_id = 0
        self.callbacks = {}
        self.done.connect(self.finish, Qt.QueuedConnection)

    def run(self, fn, callback):
        self.next_id += 1
        job = self.next_id
        self.callbacks[job] = callback

        def work():
            try:
                result, error = fn(), ""
            except (ProviderError, StorageError) as exc:
                result, error = None, str(exc)
            except Exception:
                result, error = None, "The request failed. Try again or check your AI settings."
            try:
                self.done.emit(job, result, error)
            except RuntimeError:
                pass  # Application already closed.

        threading.Thread(target=work, daemon=True, name="WhiteDot request").start()

    def finish(self, job, value, error):
        self.callbacks.pop(job)(value, error)


class Configuration(QDialog):
    saved = Signal(object)
    DISCLOSURE = "Drafts are sent to the provider below. Your API key is saved in this device’s credential store."

    def __init__(self, prefs, jobs):
        super().__init__(None, Qt.Dialog | Qt.WindowStaysOnTopHint)
        self.setWindowTitle("AI settings — WhiteDot")
        self.setStyleSheet(STYLE)
        self.setObjectName("serviceDialog")
        self.prefs = prefs
        self.jobs = jobs
        self.generation = 0
        self.validating = False
        box = QVBoxLayout(self)
        box.setContentsMargins(24, 22, 24, 20)
        box.setSpacing(14)
        heading = QLabel("AI settings")
        heading.setObjectName("heading")
        box.addWidget(heading)
        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.provider = QComboBox()
        self.provider.addItems(PRESETS)
        self.url = QLineEdit()
        self.model = QLineEdit()
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("Enter your API key")
        self.url.setPlaceholderText("https://your-provider.com/v1")
        self.model.setPlaceholderText("Model ID from your provider")
        for title, control in [("Provider", self.provider), ("Base URL", self.url),
                               ("Model", self.model), ("API key", self.key)]:
            control.setAccessibleName(title)
            form.addRow(title, control)
        box.addLayout(form)
        self.message = QLabel(self.DISCLOSURE)
        self.message.setObjectName("caption")
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.PlainText)
        box.addWidget(self.message)
        actions = QHBoxLayout()
        actions.addStretch()
        cancel = button("Cancel", self.reject)
        cancel.setAutoDefault(False)
        actions.addWidget(cancel)
        self.save = button("Verify and save", self.submit)
        self.save.setDefault(True)
        self.save.setObjectName("action")
        actions.addWidget(self.save)
        box.addLayout(actions)
        config = prefs.config
        self.provider.setCurrentText(config.provider)
        self.provider.currentTextChanged.connect(lambda name: self.fill(prefs.config_for(name)))
        self.url.textEdited.connect(lambda _: self.key.clear())
        for edit in (self.url, self.model, self.key):
            edit.textChanged.connect(self.update_save)
        self.fill(config)
        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(min(458, screen.width()), self.sizeHint().height())
        (self.url if not self.url.text() else self.key).setFocus(Qt.OtherFocusReason)

    def update_save(self):
        self.save.setEnabled(not self.validating and all(
            edit.text().strip() for edit in (self.url, self.model, self.key)))

    def fill(self, config):
        self.message.setText(self.DISCLOSURE)
        self.url.setText(config.base_url)
        self.model.setText(config.model)
        self.key.clear()
        try:
            self.key.setText(self.prefs.get_key(config))
        except StorageError as exc:
            self.message.setText(str(exc))

    def submit(self):
        if not self.save.isEnabled():
            return
        config = ProviderConfig(self.provider.currentText(), self.url.text().strip(), self.model.text().strip())
        key = self.key.text().strip()
        try:
            client = Provider(config, key)
        except ProviderError as exc:
            self.message.setText(str(exc))
            return
        self.generation += 1
        version = self.generation
        self.validating = True
        for w in (self.provider, self.url, self.model, self.key, self.save):
            w.setEnabled(False)
        self.message.setText("Verifying your key and model with a short sample…")

        def complete(_, error):
            if version != self.generation:
                return
            if not error:
                try:
                    self.prefs.save_provider(config, key)
                except StorageError as exc:
                    error = str(exc)
            if error:
                self.validating = False
                self.message.setText(error)
                for w in (self.provider, self.url, self.model, self.key):
                    w.setEnabled(True)
                self.update_save()
            else:
                self.saved.emit(client)
                self.accept()
        self.jobs.run(client.validate, complete)

    def done(self, result):
        self.generation += 1
        self.key.clear()
        super().done(result)


class Controller(QObject):
    def __init__(self, app, prefs, jobs=None, initial_client=None, testing=False):
        super().__init__()
        self.app = app
        self.prefs = prefs
        self.jobs = jobs or Jobs()
        self.client = initial_client
        self.load_saved_client = not testing and initial_client is None
        self.version = 0
        self.checked = False
        self.check_inflight = None
        self.check_queued = False
        self.rewriting = False
        self.issues = []
        self.check_error = ""
        self.rewrite_error = ""
        self.review_index = None
        self.context_handler = None
        self.needs_copy = False
        self.quit_prompt = None
        self.bubble = None
        self.dialog = None
        self.return_to_panel = False

        self.dot = Dot()
        self.panel = Panel()
        self.delay = QTimer(self)
        self.delay.setInterval(900)
        self.delay.setSingleShot(True)
        self.delay.timeout.connect(self.run_check)
        self.panel.editor.textChanged.connect(self.edited)
        self.panel.editor.issue_click.connect(self.show_issue)
        self.panel.closing.connect(self.close_panel)
        self.panel.settings_requested.connect(self.configure)
        self.panel.rewrite.clicked.connect(self.rewrite)
        self.panel.action_requested.connect(self.context_action)
        self.panel.review_requested.connect(self.review_issue)
        self.panel.original_copy.clicked.connect(self.copied)
        self.panel.result_copy.clicked.connect(self.copied)

        self.icon = icon()
        app.setWindowIcon(self.icon)
        self.tray = QSystemTrayIcon(self.icon, self)
        self.tray.setToolTip("WhiteDot — English proofreader")
        self.menu = QMenu()
        self.menu.addAction("Open editor", self.show_editor)
        self.menu.addAction("AI settings…", self.configure)
        self.start_action = self.menu.addAction("Open at login")
        self.start_action.setCheckable(True)
        self.start_action.triggered.connect(self.toggle_startup)
        self.menu.addSeparator()
        self.menu.addAction("Quit WhiteDot", self.request_quit)
        self.menu.aboutToShow.connect(self.prepare_menu)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self.tray_click)
        self.dot.clicked.connect(self.open_dot)
        self.dot.menu_at.connect(self.menu.popup)
        self.dot.moved.connect(self.remember_position)
        self.restore_position()
        self.app.screenRemoved.connect(self.restore_position)
        self.dot.show()
        if not testing:
            self.tray.show()

    def prepare_menu(self):
        try:
            self.start_action.setChecked(startup.enabled())
            self.start_action.setEnabled(True)
            self.start_action.setToolTip("")
        except OSError:
            self.start_action.setEnabled(False)
            self.start_action.setToolTip("Couldn’t read your login settings. Reopen this menu to retry.")

    def show_editor(self):
        if self.quit_prompt:
            self.quit_prompt.raise_()
            self.quit_prompt.activateWindow()
        elif self.panel.isVisible():
            raise_surface(self.panel)
            self.panel.activateWindow()
            self.panel.editor.setFocus(Qt.OtherFocusReason)
        else:
            self.open_dot()

    def copied(self):
        self.needs_copy = False

    def request_quit(self):
        if self.quit_prompt:
            self.quit_prompt.raise_()
            return
        draft = self.panel.editor.toPlainText()
        if not self.needs_copy or not draft:
            self.app.quit()
            return
        result = self.panel.result.toPlainText()
        prompt = QMessageBox(self.panel if self.panel.isVisible() else None)
        self.quit_prompt = prompt
        prompt.setWindowFlag(Qt.WindowStaysOnTopHint)
        prompt.setWindowModality(Qt.ApplicationModal)
        prompt.setWindowTitle("Quit WhiteDot")
        prompt.setText("Keep a copy before quitting?")
        prompt.setInformativeText("Your draft and rewrite are cleared when WhiteDot quits.")
        copy = prompt.addButton("Copy rewrite and quit" if result else "Copy draft and quit",
                                QMessageBox.AcceptRole)
        discard = prompt.addButton("Quit without copying", QMessageBox.DestructiveRole)
        keep = prompt.addButton("Keep writing", QMessageBox.RejectRole)
        prompt.setDefaultButton(keep)
        prompt.setEscapeButton(keep)

        def finished():
            chosen = prompt.clickedButton()
            self.quit_prompt = None
            prompt.deleteLater()
            if chosen == copy:
                self.app.clipboard().setText(result or draft)
                self.app.quit()
            elif chosen == discard:
                self.app.quit()
            else:
                self.show_editor()
        prompt.finished.connect(finished)
        prompt.show()
        prompt.raise_()
        prompt.activateWindow()

    def tray_click(self, reason):
        if reason == QSystemTrayIcon.Trigger and sys.platform != "darwin":
            self.menu.popup(QCursor.pos())

    def restore_position(self):
        screen = self.app.primaryScreen()
        area = screen.availableGeometry()
        pos = QPoint(area.right() - 75, area.top() + round(area.height() * .72))
        saved = self.prefs.get("position")
        if isinstance(saved, list) and len(saved) == 2 and all(type(x) is int for x in saved):
            candidate = QPoint(*saved)
            found = self.app.screenAt(candidate + self.dot.rect().center())
            if found:
                screen, pos = found, candidate
        self.dot.move(clamped(pos, self.dot.size(), screen))
        if self.panel.isVisible():
            self.place_panel()

    def remember_position(self):
        try:
            self.prefs.set("position", [self.dot.x(), self.dot.y()])
        except StorageError as exc:
            self.notify(str(exc))
        if self.panel.isVisible():
            self.place_panel()

    def toggle_startup(self, on):
        try:
            startup.set_enabled(on)
        except OSError:
            self.notify("Couldn’t update the login item. Check your account permissions.")
        self.prepare_menu()

    def notify(self, message):
        if self.panel.isVisible():
            self.set_status(message)
        elif self.tray.isVisible():
            self.tray.showMessage("WhiteDot", message, QSystemTrayIcon.Information, 4500)

    def configure(self):
        if self.dialog:
            self.dialog.raise_()
            self.dialog.activateWindow()
            return
        self.return_to_panel = self.panel.isVisible()
        self.close_panel()
        self.dialog = Configuration(self.prefs, self.jobs)
        self.dialog.saved.connect(self.use_client)
        self.dialog.finished.connect(self.config_closed)
        anchor = self.panel if self.return_to_panel else self.dot
        center = anchor.geometry().center()
        self.dialog.move(clamped(center - self.dialog.rect().center(), self.dialog.size(), self.dot.screen()))
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def config_closed(self):
        self.dialog.deleteLater()
        self.dialog = None
        if self.return_to_panel:
            self.return_to_panel = False
            self.open_dot()

    def use_client(self, client):
        self.client = client
        self.load_saved_client = False
        self.edited()
        if not self.return_to_panel:
            self.notify("AI service connected.")

    def open_dot(self):
        if self.dialog:
            self.dialog.raise_()
            self.dialog.activateWindow()
            return
        if self.panel.isVisible():
            self.close_panel()
            return
        self.place_panel()
        self.panel.show()
        raise_surface(self.panel)
        self.panel.activateWindow()
        self.panel.editor.setFocus(Qt.OtherFocusReason)
        if self.load_saved_client:
            self.load_saved_client = False
            try:
                key = self.prefs.get_key()
                if key:
                    self.client = Provider(self.prefs.config, key)
            except (StorageError, ProviderError) as exc:
                self.load_saved_client = True
                self.set_status(str(exc), "AI settings", self.configure)
                return
        self.schedule()

    def close_panel(self):
        if not self.panel.isVisible():
            return
        self.panel.hide()
        self.version += 1
        self.delay.stop()
        self.check_queued = False
        self.hide_bubble()
        if self.rewriting:
            self.rewriting = False
            self.panel.result_group.setVisible(bool(self.panel.result.toPlainText()))
        self.review_index = None
        # Keep the user's draft and finished results in this process.

    def place_panel(self):
        screen = self.dot.screen()
        area = screen.availableGeometry()
        size = self.panel.sizeHint().boundedTo(area.size())
        self.panel.resize(size)
        gap = 4
        x = self.dot.x() - self.panel.width() - gap
        right = self.dot.x() + self.dot.width() + gap
        y = self.dot.y() + self.dot.height() - self.panel.height()
        if x < area.left():
            if right + self.panel.width() <= area.right() + 1:
                x = right
            else:
                # Both sides are narrow. Keep the launcher reachable above or below the panel.
                x = self.dot.geometry().center().x() - self.panel.width() // 2
                above = self.dot.y() - gap - self.panel.height()
                below = self.dot.y() + self.dot.height() + gap
                if above >= area.top():
                    y = above
                elif below + self.panel.height() <= area.bottom() + 1:
                    y = below
        self.panel.move(clamped(QPoint(x, y), self.panel.size(), screen))

    def hide_bubble(self):
        if self.bubble:
            bubble, self.bubble = self.bubble, None
            bubble.hide()
            bubble.deleteLater()

    def edited(self):
        self.needs_copy = bool(self.panel.editor.toPlainText())
        self.version += 1
        self.delay.stop()
        self.check_queued = False
        self.checked = False
        self.rewriting = False
        self.check_error = ""
        self.rewrite_error = ""
        self.review_index = None
        self.issues = []
        self.hide_bubble()
        self.panel.editor.mark([])
        self.panel.result.clear()
        had_result = not self.panel.result_group.isHidden()
        self.panel.result_group.hide()
        if self.panel.isVisible():
            if had_result:
                self.place_panel()
            self.schedule()

    def set_status(self, message, action=None, handler=None):
        self.panel.status.setText(message)
        self.panel.set_context_action(action)
        self.context_handler = handler

    def context_action(self):
        if self.context_handler:
            self.context_handler()

    def schedule(self):
        text = self.panel.editor.toPlainText()
        eligible = bool(self.client and not input_status(text, MAX_TEXT))
        if eligible and not self.checked and not self.check_error:
            self.delay.start()
        self.refresh_status()

    def refresh_status(self):
        text = self.panel.editor.toPlainText()
        problem = input_status(text, MAX_TEXT) if text else ""
        self.panel.rewrite.setEnabled(bool(self.client and text and not problem and not self.rewriting))
        if not self.client:
            self.set_status("", "Connect AI", self.configure)
        elif not text:
            self.set_status("Checks as you type")
        elif problem:
            self.set_status(problem)
        elif self.rewriting:
            self.set_status("Rewriting…")
        elif self.rewrite_error:
            self.set_status(self.rewrite_error, "Retry rewrite", self.rewrite)
        elif self.check_error:
            self.set_status(self.check_error, "Retry check", self.run_check)
        elif self.issues:
            count = len(self.issues)
            self.set_status("", f"{count} suggestion" + ("s" if count != 1 else ""), self.review_issue)
        elif self.panel.result.toPlainText():
            self.set_status("No changes needed" if self.panel.result.toPlainText() == text else "Rewrite ready")
        elif self.checked:
            self.set_status("No issues found")
        elif self.check_inflight == self.version:
            self.set_status("Checking…")
        else:
            self.set_status("Waiting to check…")

    def run_check(self):
        text = self.panel.editor.toPlainText()
        if not self.panel.isVisible() or not self.client or input_status(text, MAX_TEXT):
            return
        if self.check_inflight is not None:
            self.check_queued = self.check_inflight != self.version
            return
        self.check_inflight = self.version
        self.check_queued = False
        self.check_error = ""
        self.refresh_status()
        version, client = self.version, self.client

        def complete(issues, error):
            self.check_inflight = None
            if version == self.version and self.panel.isVisible():
                self.checked = not error
                self.check_error = error
                self.issues = issues or []
                self.panel.editor.mark(self.issues)
                self.refresh_status()
            if self.check_queued:
                self.check_queued = False
                self.run_check()

        self.jobs.run(lambda: client.check(text), complete)

    def review_issue(self):
        if not self.issues or not self.panel.isVisible():
            return
        editor = self.panel.editor
        text = editor.toPlainText()
        cursor = editor.textCursor()
        index = self.review_index
        if index is None:
            caret = cursor.position()
            index = next((i for i, issue in enumerate(self.issues) if utf16(text[:issue.end]) > caret), 0)
        issue = self.issues[index]
        cursor.setPosition(utf16(text[:issue.start]))
        editor.setTextCursor(cursor)
        editor.ensureCursorVisible()
        where = editor.viewport().mapToGlobal(editor.cursorRect(cursor).bottomLeft())
        self.show_issue(issue, where)

    def dismiss_issue(self, bubble):
        if self.bubble is not bubble:
            return
        self.hide_bubble()
        if bubble.return_to_editor:
            # The platform may clear keyboard focus after the popup's hide event.
            QTimer.singleShot(0, self.panel, self.restore_edit_focus)

    def restore_edit_focus(self):
        if self.panel.isVisible() and not (self.bubble or self.dialog or self.quit_prompt):
            self.panel.activateWindow()
            self.panel.editor.setFocus(Qt.OtherFocusReason)

    def show_issue(self, issue, pos):
        self.hide_bubble()
        if not self.panel.isVisible() or issue not in self.issues:
            return
        bubble = Suggestion(issue, parent=self.panel)
        self.bubble = bubble
        version = self.version
        self.review_index = (self.issues.index(issue) + 1) % len(self.issues)
        bubble.chosen.connect(lambda word: self.apply(issue, word, version))
        bubble.dismissed.connect(lambda: self.dismiss_issue(bubble))
        bubble.adjustSize()
        screen = self.app.screenAt(pos) or self.dot.screen()
        bubble.move(clamped(pos + QPoint(2, 8), bubble.size(), screen))
        bubble.show()
        raise_surface(bubble)
        bubble.focus_choices()

    def apply(self, issue, word, version):
        self.hide_bubble()
        text = self.panel.editor.toPlainText()
        if (not self.panel.isVisible() or version != self.version or issue not in self.issues
                or word not in issue.suggestions or text[issue.start:issue.end] != issue.original):
            return
        cursor = self.panel.editor.textCursor()
        cursor.setPosition(utf16(text[:issue.start]))
        cursor.setPosition(utf16(text[:issue.end]), QTextCursor.KeepAnchor)
        cursor.insertText(word)
        self.panel.editor.setTextCursor(cursor)
        self.panel.activateWindow()
        self.panel.editor.setFocus(Qt.OtherFocusReason)

    def rewrite(self):
        text = self.panel.editor.toPlainText()
        if (not self.panel.isVisible() or self.rewriting or not self.client
                or input_status(text, MAX_TEXT)):
            return
        version, client = self.version, self.client
        self.rewriting = True
        self.rewrite_error = ""
        self.panel.result_group.show()
        self.place_panel()
        self.refresh_status()

        def complete(result, error):
            if version != self.version or not self.panel.isVisible():
                return
            self.rewriting = False
            self.rewrite_error = error
            if error:
                self.panel.result_group.setVisible(bool(self.panel.result.toPlainText()))
                self.place_panel()
            else:
                if result != text and result != self.panel.result.toPlainText():
                    self.needs_copy = True
                self.panel.result.setPlainText(result)
            self.refresh_status()

        self.jobs.run(lambda: client.rewrite(text), complete)
