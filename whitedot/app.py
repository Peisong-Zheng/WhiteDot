"""Manual proofreading, draft revisions and desktop controls."""
from bisect import bisect_right
from dataclasses import replace
from os.path import commonprefix
import re
import sys
import threading

from PySide6.QtCore import QObject, QPoint, QTimer, Qt, Signal
from PySide6.QtGui import QCursor, QTextCursor
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMenu, QMessageBox, QSystemTrayIcon, QVBoxLayout, QWidget)

from . import startup
from .local_spelling import check_local
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

        threading.Thread(target=work, daemon=True, name="Folio request").start()

    def finish(self, job, value, error):
        self.callbacks.pop(job)(value, error)


class SavedProvider:
    """Build the provider from its local connection when a draft needs the model."""
    def __init__(self, prefs):
        self.prefs = prefs
        self.config = prefs.config
        self._client = None
        self._lock = threading.Lock()
        self.access_error = ""

    def open(self):
        # Proofreading and rewriting may begin together for the same draft.
        with self._lock:
            if self.access_error:
                raise StorageError(self.access_error)
            if self._client is None:
                try:
                    key = self.prefs.get_key(self.config)
                    if not key:
                        raise StorageError("Open AI settings from the dot’s menu to enter a key for this provider.")
                    self._client = Provider(self.config, key)
                except (StorageError, ProviderError) as exc:
                    self.access_error = str(exc)
                    raise
            return self._client


class Configuration(QDialog):
    saved = Signal(object)
    DISCLOSURE = "AI checks send your draft to this provider. Your key is stored in a plain-text file in your user account."

    def __init__(self, prefs, jobs):
        super().__init__(None, Qt.Dialog | Qt.WindowStaysOnTopHint)
        self.setWindowTitle("AI settings — Folio")
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
        self.saved_key = QLabel("Saved")
        self.change_key = button("Change key", self.toggle_key_entry)
        self.change_key.setAutoDefault(False)
        self.key_row = QWidget()
        key_box = QHBoxLayout(self.key_row)
        key_box.setContentsMargins(0, 0, 0, 0)
        key_box.addWidget(self.saved_key, 1)
        key_box.addWidget(self.key, 1)
        key_box.addWidget(self.change_key)
        self.key.setAccessibleName("API key")
        self.url.setPlaceholderText("https://your-provider.com/v1")
        self.model.setPlaceholderText("Model ID from your provider")
        for title, control in [("Provider", self.provider), ("Base URL", self.url),
                               ("Model", self.model), ("API key", self.key_row)]:
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
        self.url.textChanged.connect(self.reset_key_entry)
        for edit in (self.model, self.key):
            edit.textChanged.connect(self.update_save)
        self.fill(config)
        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(min(458, screen.width()), self.sizeHint().height())
        focus = self.change_key if self.stored_key else (self.url if not self.url.text() else self.key)
        focus.setFocus(Qt.OtherFocusReason)

    def current_config(self):
        return ProviderConfig(self.provider.currentText(), self.url.text().strip(), self.model.text().strip())

    def update_save(self):
        config = self.current_config()
        changed = self.entering_key or config != self.prefs.config
        credential_ready = bool(self.key.text().strip()) if self.entering_key else self.stored_key
        self.save.setEnabled(bool(not self.validating and changed and credential_ready
                                  and config.base_url and config.model))

    def reset_key_entry(self):
        config = self.current_config()
        self.stored_key = self.prefs.has_key(config)
        self.set_key_entry(not self.stored_key)
        if self.prefs.connection_error:
            self.message.setText(self.prefs.connection_error)
        elif self.prefs.needs_key_reentry(config):
            self.message.setText("Re-enter your key once to save it locally. " + self.DISCLOSURE)
        else:
            self.message.setText(self.DISCLOSURE)

    def toggle_key_entry(self):
        self.set_key_entry(not self.entering_key)
        (self.key if self.entering_key else self.change_key).setFocus(Qt.OtherFocusReason)

    def set_key_entry(self, entering):
        self.entering_key = entering
        self.key.clear()
        self.key.setVisible(entering)
        self.saved_key.setVisible(not entering)
        self.change_key.setVisible(self.stored_key)
        self.change_key.setText("Keep saved key" if entering else "Change key")
        self.key.setPlaceholderText("Enter a new API key" if self.stored_key else "Enter your API key")
        self.update_save()

    def fill(self, config):
        self.url.setText(config.base_url)
        self.reset_key_entry()
        self.model.setText(config.model)

    def submit(self):
        if not self.save.isEnabled():
            return
        config = self.current_config()
        new_key = self.key.text().strip() if self.entering_key else None
        self.generation += 1
        version = self.generation
        self.validating = True
        fields = (self.provider, self.url, self.model, self.key_row)
        for field in fields:
            field.setEnabled(False)
        self.update_save()
        self.message.setText("Verifying your key and model with a short sample…")

        def verify():
            # A stored key is used only after the user commits a changed profile.
            key = new_key if new_key is not None else self.prefs.get_key(config)
            if not key:
                raise StorageError("The saved key is missing. Choose Change key to enter a new one.")
            client = Provider(config, key)
            client.validate()
            return client

        def complete(client, error):
            if version != self.generation:
                return
            if not error:
                try:
                    self.prefs.save_provider(config, new_key)
                except StorageError as exc:
                    error = str(exc)
            if error:
                self.validating = False
                self.message.setText(error)
                for field in fields:
                    field.setEnabled(True)
                self.update_save()
            else:
                self.saved.emit(client)
                self.accept()
        self.jobs.run(verify, complete)

    def done(self, result):
        self.generation += 1
        self.key.clear()
        super().done(result)


# Only remap model feedback if its entire sentence still exists at the expected
# location. An unchanged word inside an edited sentence may now be grammatical.
_SENTENCE_END = re.compile(r"""[.!?]+[”’"')\]]*(?=\s|$)|\n+""")
_TYPED_SENTENCE_END = re.compile(r"""[.!?][”’"')\]]*$""")


def sentence_spans(text):
    spans = []
    start = 0
    for end in [m.end() for m in _SENTENCE_END.finditer(text)] + [len(text)]:
        while start < end and text[start].isspace():
            start += 1
        last = end
        while last > start and text[last - 1].isspace():
            last -= 1
        if last > start:
            spans.append((start, last))
        start = end
    return spans


def unchanged_grammar(before, after, issues):
    if not issues or not after or before == after:
        return issues if after else []
    shorter = min(len(before), len(after))
    if before.startswith(after) or after.startswith(before):
        prefix, suffix = shorter, 0
    else:
        prefix = len(commonprefix((before, after)))
        suffix = min(shorter - prefix, len(commonprefix((before[::-1], after[::-1]))))
    old = sentence_spans(before)
    starts = [start for start, end in old]
    new = set(sentence_spans(after))
    delta = len(after) - len(before)
    kept = []
    for issue in issues:
        index = bisect_right(starts, issue.start) - 1
        if index < 0:
            continue
        start, end = old[index]
        if issue.end > end:
            continue
        if end <= prefix and (start, end) in new:
            kept.append(issue)
        elif start >= len(before) - suffix and (start + delta, end + delta) in new:
            kept.append(replace(issue, start=issue.start + delta, end=issue.end + delta))
    return kept


class Controller(QObject):
    def __init__(self, app, prefs, jobs=None, initial_client=None, testing=False):
        super().__init__()
        self.app = app
        self.prefs = prefs
        self.jobs = jobs or Jobs()
        self.client = initial_client
        if self.client is None and prefs.has_key():
            self.client = SavedProvider(prefs)
        self.version = 0
        self.checked = False
        self.check_inflight = None
        self.check_queued = False
        self.rewriting = False
        self.issues = []
        self.local_issues = []
        self.grammar_issues = []
        self.draft = ""
        self.input_problem = ""
        self.open_generation = 0
        self.sentence_anchor = ""
        self.held_word = None
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
        self.delay.setInterval(450)
        self.delay.setSingleShot(True)
        self.delay.timeout.connect(self.run_check)
        self.word_delay = QTimer(self)
        self.word_delay.setSingleShot(True)
        self.word_delay.setInterval(160)
        self.word_delay.timeout.connect(self.finish_word)
        self.sentence_delay = QTimer(self)
        self.sentence_delay.setSingleShot(True)
        self.sentence_delay.setInterval(200)
        self.sentence_delay.timeout.connect(self.check_completed_sentence)
        self.panel.editor.textChanged.connect(self.edited)
        self.panel.editor.issue_click.connect(self.show_issue)
        self.panel.closing.connect(self.close_panel)
        self.panel.rewrite.clicked.connect(self.rewrite)
        self.panel.action_requested.connect(self.context_action)
        self.panel.review_requested.connect(self.review_issue)
        self.panel.original_copy.clicked.connect(self.copied)
        self.panel.result_copy.clicked.connect(self.copied)

        self.icon = icon()
        app.setWindowIcon(self.icon)
        self.tray = QSystemTrayIcon(self.icon, self)
        self.tray.setToolTip("Folio — English proofreader")
        self.menu = QMenu()
        self.menu.addAction("Open editor", self.show_editor)
        self.menu.addAction("AI settings…", self.configure)
        self.start_action = self.menu.addAction("Open at login")
        self.start_action.setCheckable(True)
        self.start_action.triggered.connect(self.toggle_startup)
        self.menu.addSeparator()
        self.menu.addAction("Quit Folio", self.request_quit)
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
        prompt.setWindowTitle("Quit Folio")
        prompt.setText("Keep a copy before quitting?")
        prompt.setInformativeText("Your draft and rewrite are cleared when Folio quits.")
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
            self.tray.showMessage("Folio", message, QSystemTrayIcon.Information, 4500)

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
        self.grammar_issues = []
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
        self.schedule()

    def close_panel(self):
        if not self.panel.isVisible():
            return
        self.panel.hide()
        self.version += 1
        self.open_generation += 1
        self.delay.stop()
        self.sentence_delay.stop()
        self.word_delay.stop()
        self.finish_word()
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
        previous = self.draft
        self.draft = self.panel.editor.toPlainText()
        self.input_problem = input_status(self.draft, MAX_TEXT) if self.draft else ""
        self.needs_copy = bool(self.draft)
        self.version += 1
        self.delay.stop()
        self.check_queued = False
        self.checked = False
        self.rewriting = False
        self.check_error = ""
        self.rewrite_error = ""
        self.review_index = None
        self.hide_bubble()
        self.local_issues = check_local(self.draft) if self.draft and not self.input_problem else []
        self.grammar_issues = unchanged_grammar(previous, self.draft, self.grammar_issues) if not self.input_problem else []
        self.word_delay.stop()
        self.held_word = None
        if self.panel.editor.typing_letter and self.local_issues:
            qt_position = self.panel.editor.textCursor().position()
            caret = qt_position
            if not self.draft.isascii():
                caret = len(self.draft.encode("utf-16-le")[:2 * qt_position].decode("utf-16-le"))
            for issue in self.local_issues:
                if issue.start < caret <= issue.end:
                    self.held_word = issue
                    self.word_delay.start()
                    break
        self.display_issues()
        if self.panel.result.toPlainText():
            self.panel.result.clear()
        had_result = not self.panel.result_group.isHidden()
        self.panel.result_group.hide()
        if self.panel.isVisible():
            if had_result:
                self.place_panel()
            self.schedule()
            # Let a completed sentence start a check even if the next sentence
            # is already being typed and the ordinary idle timer keeps moving.
            if self.delay.isActive() and (self.draft.endswith("\n") or _TYPED_SENTENCE_END.search(self.draft)):
                self.sentence_anchor = self.draft
                self.sentence_delay.start()

    def finish_word(self):
        if self.held_word is not None:
            self.held_word = None
            self.display_issues()
            self.refresh_status()

    def check_completed_sentence(self):
        if self.draft.startswith(self.sentence_anchor) and not self.checked:
            self.run_check()

    def display_issues(self):
        # Model feedback takes precedence for overlapping spans. Keep immediate
        # local suggestions everywhere else, even when the network check fails.
        grammar = self.grammar_issues
        combined = list(grammar)
        index = 0
        for issue in self.local_issues:
            if issue == self.held_word:
                continue
            while index < len(grammar) and grammar[index].end <= issue.start:
                index += 1
            if index == len(grammar) or grammar[index].start >= issue.end:
                combined.append(issue)
        self.issues = sorted(combined, key=lambda item: item.start)
        self.panel.editor.mark(self.issues)
        if self.review_index is not None and self.review_index >= len(self.issues):
            self.review_index = None

    def set_status(self, message, action=None, handler=None):
        if self.panel.status.text() != message or self.panel.context_action.text() != (action or ""):
            self.panel.status.setText(message)
            self.panel.set_context_action(action)
        self.context_handler = handler

    def context_action(self):
        if self.context_handler:
            self.context_handler()

    def access_error(self):
        return self.client.access_error if isinstance(self.client, SavedProvider) else ""

    def retry_access(self):
        if not self.access_error():
            return
        # Retry a missing or invalid local profile only on a deliberate click.
        retry_rewrite = bool(self.rewrite_error)
        self.version += 1
        self.client = SavedProvider(self.prefs)
        self.check_error = self.rewrite_error = ""
        self.rewriting = False
        self.run_check()
        if retry_rewrite:
            self.rewrite()

    def schedule(self):
        eligible = bool(self.client and self.draft and not self.input_problem)
        if eligible and not self.checked and not self.check_error and not self.access_error():
            self.delay.start()
        self.refresh_status()

    def refresh_status(self):
        text, problem = self.draft, self.input_problem
        can_rewrite = self.client and text and not problem and not self.rewriting and not self.access_error()
        self.panel.rewrite.setEnabled(bool(can_rewrite))
        if not self.client:
            count = len(self.issues)
            offline = f"{count} suggestion" + ("s" if count != 1 else "") if count else ""
            legacy = self.prefs.needs_key_reentry()
            if legacy and not offline:
                offline = "Re-enter your key once for AI grammar and rewrites."
            self.set_status(problem or offline, "Re-enter API key" if legacy else "Connect AI", self.configure)
        elif not text:
            self.set_status("Checks as you type")
        elif problem:
            self.set_status(problem)
        elif self.access_error():
            self.set_status(self.access_error(), "Retry access", self.retry_access)
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
            self.set_status("Checking grammar…")
        else:
            self.set_status("Waiting to check grammar…")

    def run_model(self, operation, text, complete):
        version, client = self.version, self.client

        def work():
            if version != self.version:
                return None
            provider = client.open() if isinstance(client, SavedProvider) else client
            # The user may have edited or hidden the draft before the worker was ready.
            if version != self.version:
                return None
            return getattr(provider, operation)(text)

        self.jobs.run(work, complete)

    def run_check(self):
        text = self.draft
        if not self.panel.isVisible() or not self.client or not text or self.access_error() or self.input_problem:
            return
        self.delay.stop()
        self.sentence_delay.stop()
        if self.check_inflight is not None:
            self.check_queued = self.check_inflight != self.version
            return
        self.check_inflight = self.version
        self.check_queued = False
        self.check_error = ""
        self.refresh_status()
        version, generation, client = self.version, self.open_generation, self.client

        def complete(issues, error):
            self.check_inflight = None
            if version == self.version and self.panel.isVisible():
                self.checked = not error
                self.check_error = error
                if not error:
                    self.grammar_issues = issues or []
                    self.display_issues()
            elif (issues and generation == self.open_generation and client is self.client
                  and self.panel.isVisible() and not self.input_problem):
                self.grammar_issues = unchanged_grammar(text, self.draft, issues)
                self.display_issues()
            if self.panel.isVisible():
                self.refresh_status()
            if self.check_queued:
                self.check_queued = False
                self.run_check()

        self.run_model("check", text, complete)

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
        current_span = any((i.start, i.end) == (issue.start, issue.end) for i in self.issues)
        if (not self.panel.isVisible() or version != self.version or not current_span
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
        if (not self.panel.isVisible() or self.rewriting or not self.client or self.access_error()
                or input_status(text, MAX_TEXT)):
            return
        version = self.version
        self.rewriting = True
        self.rewrite_error = ""
        self.panel.result_group.show()
        self.place_panel()
        self.refresh_status()

        def complete(result, error):
            if version != self.version or not self.panel.isVisible():
                if self.access_error() and self.panel.isVisible():
                    self.refresh_status()
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

        self.run_model("rewrite", text, complete)
