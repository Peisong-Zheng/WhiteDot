"""Manual proofreading, draft revisions and desktop controls."""
import sys
import threading

from PySide6.QtCore import QObject, QPoint, QTimer, Qt, Signal
from PySide6.QtGui import QCursor, QTextCursor
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMenu, QSystemTrayIcon, QVBoxLayout)

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
                result, error = None, "操作失败，请重试或检查服务设置。"
            try:
                self.done.emit(job, result, error)
            except RuntimeError:
                pass  # Application already closed.

        threading.Thread(target=work, daemon=True, name="WhiteDot request").start()

    def finish(self, job, value, error):
        self.callbacks.pop(job)(value, error)


class Configuration(QDialog):
    saved = Signal(object)
    def __init__(self, prefs, jobs):
        super().__init__(None, Qt.Dialog | Qt.WindowStaysOnTopHint)
        self.setWindowTitle("WhiteDot · AI 服务")
        self.setStyleSheet(STYLE)
        self.setMinimumWidth(420)
        self.setObjectName("serviceDialog")
        self.prefs = prefs
        self.jobs = jobs
        self.generation = 0
        box = QVBoxLayout(self)
        box.setContentsMargins(24, 22, 24, 20)
        box.setSpacing(14)
        heading = QLabel("AI 服务")
        heading.setObjectName("heading")
        box.addWidget(heading)
        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        self.provider = QComboBox()
        self.provider.addItems(PRESETS)
        self.url = QLineEdit()
        self.model = QLineEdit()
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("输入 API Key")
        for title, control in [("服务商", self.provider), ("API 基础地址", self.url),
                               ("模型", self.model), ("API Key", self.key)]:
            form.addRow(title, control)
        box.addLayout(form)
        self.message = QLabel("在 WhiteDot 中输入的英文会发送到所选服务。密钥保存在系统凭据库。")
        self.message.setObjectName("caption")
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.PlainText)
        box.addWidget(self.message)
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(button("取消", self.reject))
        self.save = button("验证并保存", self.submit)
        self.save.setObjectName("action")
        actions.addWidget(self.save)
        box.addLayout(actions)
        self.provider.currentTextChanged.connect(lambda name: self.fill(PRESETS[name]))
        self.url.textEdited.connect(lambda _: self.key.clear())
        config = prefs.config
        self.provider.setCurrentText(config.provider)
        self.fill(config)

    def fill(self, config):
        self.url.setText(config.base_url)
        self.model.setText(config.model)
        self.key.clear()
        try:
            self.key.setText(self.prefs.get_key(config))
        except StorageError as exc:
            self.message.setText(str(exc))

    def submit(self):
        config = ProviderConfig(self.provider.currentText(), self.url.text().strip(), self.model.text().strip())
        key = self.key.text().strip()
        try:
            client = Provider(config, key)
        except ProviderError as exc:
            self.message.setText(str(exc))
            return
        self.generation += 1
        version = self.generation
        for w in (self.provider, self.url, self.model, self.key, self.save):
            w.setEnabled(False)
        self.message.setText("正在验证密钥、模型和校对格式…")

        def complete(_, error):
            if version != self.generation:
                return
            if not error:
                try:
                    self.prefs.save_provider(config, key)
                except StorageError as exc:
                    error = str(exc)
            if error:
                self.message.setText(error)
                for w in (self.provider, self.url, self.model, self.key, self.save):
                    w.setEnabled(True)
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
        self.check_inflight = False
        self.check_queued = False
        self.rewriting = False
        self.issues = []
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

        self.icon = icon()
        app.setWindowIcon(self.icon)
        self.tray = QSystemTrayIcon(self.icon, self)
        self.tray.setToolTip("WhiteDot · 英文校对")
        self.menu = QMenu()
        self.menu.addAction("AI 服务与密钥…", self.configure)
        self.start_action = self.menu.addAction("登录时启动")
        self.start_action.setCheckable(True)
        self.start_action.triggered.connect(self.toggle_startup)
        self.menu.addSeparator()
        self.menu.addAction("退出 WhiteDot", app.quit)
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
        self.start_action.setChecked(startup.enabled())

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
            self.notify("无法更新登录启动项，请检查账户权限。")
        self.prepare_menu()

    def notify(self, message):
        if self.panel.isVisible():
            self.panel.status.setText(message)
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
        self.notify("AI 服务验证成功。")

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
                self.panel.status.setText(str(exc))
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
            self.panel.result_group.hide()
        # Keep the user's draft and finished results in this process.

    def place_panel(self):
        screen = self.dot.screen()
        area = screen.availableGeometry()
        size = self.panel.sizeHint().boundedTo(area.size())
        self.panel.resize(size)
        gap = 4
        x = self.dot.x() - self.panel.width() - gap
        right = self.dot.x() + self.dot.width() + gap
        if x < area.left() and right + self.panel.width() <= area.right() + 1:
            x = right
        y = self.dot.y() + self.dot.height() - self.panel.height()
        self.panel.move(clamped(QPoint(x, y), self.panel.size(), screen))

    def hide_bubble(self):
        if self.bubble:
            self.bubble.hide()
            self.bubble.deleteLater()
            self.bubble = None

    def edited(self):
        self.version += 1
        self.delay.stop()
        self.check_queued = False
        self.checked = False
        self.rewriting = False
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

    def schedule(self):
        text = self.panel.editor.toPlainText()
        message = input_status(text, MAX_TEXT) if text else "输入后自动校对"
        if not self.client:
            message = "点右上角设置 AI 服务"
        self.panel.rewrite.setEnabled(not message and not self.rewriting)
        if message:
            self.panel.status.setText(message)
        elif not self.checked:
            self.panel.status.setText("等待校对…")
            self.delay.start()
        elif self.panel.result_group.isHidden():
            self.show_check_status()

    def show_check_status(self):
        self.panel.status.setText(f"{len(self.issues)} 处建议" if self.issues else "已校对")

    def run_check(self):
        text = self.panel.editor.toPlainText()
        if not self.panel.isVisible() or not self.client or input_status(text, MAX_TEXT):
            return
        if self.check_inflight:
            self.check_queued = True
            return
        self.check_inflight = True
        self.check_queued = False
        version, client = self.version, self.client
        if self.panel.result_group.isHidden():
            self.panel.status.setText("校对中…")

        def complete(issues, error):
            self.check_inflight = False
            if version == self.version and self.panel.isVisible():
                self.checked = not error
                self.issues = issues or []
                self.panel.editor.mark(self.issues)
                if self.panel.result_group.isHidden():
                    if error:
                        self.panel.status.setText(error)
                    else:
                        self.show_check_status()
            if self.check_queued:
                self.check_queued = False
                self.run_check()

        self.jobs.run(lambda: client.check(text), complete)

    def show_issue(self, issue, pos):
        self.hide_bubble()
        if not self.panel.isVisible() or issue not in self.issues:
            return
        bubble = Suggestion(issue)
        self.bubble = bubble
        version = self.version
        bubble.chosen.connect(lambda word: self.apply(issue, word, version))
        bubble.adjustSize()
        screen = self.app.screenAt(pos) or self.dot.screen()
        bubble.move(clamped(pos + QPoint(2, 8), bubble.size(), screen))
        bubble.show()
        raise_surface(bubble)

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

    def rewrite(self):
        text = self.panel.editor.toPlainText()
        if (not self.panel.isVisible() or self.rewriting or not self.client
                or input_status(text, MAX_TEXT)):
            return
        version, client = self.version, self.client
        self.rewriting = True
        self.panel.result.clear()
        self.panel.result_group.show()
        self.place_panel()
        self.panel.rewrite.setEnabled(False)
        self.panel.status.setText("正在重写语法…")

        def complete(result, error):
            if version != self.version or not self.panel.isVisible():
                return
            self.rewriting = False
            self.panel.rewrite.setEnabled(True)
            if error:
                self.panel.result_group.hide()
                self.place_panel()
                self.panel.status.setText(error)
            else:
                self.panel.result.setPlainText(result)
                self.panel.status.setText("重写完成" if result != text else "原文语法正确")

        self.jobs.run(lambda: client.rewrite(text), complete)
