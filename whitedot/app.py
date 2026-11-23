"""Focus tracking, revision-bound checks and the two floating editor modes."""
import sys
import threading
import secrets

from PySide6.QtCore import QObject, QPoint, QTimer, Qt, Signal
from PySide6.QtGui import QCursor, QTextCursor
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMenu, QMessageBox, QSystemTrayIcon, QVBoxLayout)

from . import startup
from .focus import foreground_browser
from .privacy import contains_credential, input_status
from .provider import MAX_TEXT, PRESETS, Provider, ProviderConfig, ProviderError
from .settings import StorageError
from .windows_ui import Dot, Mark, Panel, STYLE, Suggestion, button, clamped, icon, raise_surface, utf16


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
        self.prefs = prefs
        self.jobs = jobs
        self.generation = 0
        box = QVBoxLayout(self)
        box.setContentsMargins(20, 18, 20, 18)
        form = QFormLayout()
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
        self.message = QLabel("启用后，当前英文输入框的内容会发送到所选服务校对。密钥保存在系统凭据库。")
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


def timer(owner, ms, fn, once=False):
    t = QTimer(owner)
    t.setInterval(ms)
    t.setSingleShot(once)
    t.timeout.connect(fn)
    return t


class Controller(QObject):
    def __init__(self, app, prefs, adapter, jobs=None, initial_client=None, testing=False):
        super().__init__()
        self.app, self.prefs, self.adapter = app, prefs, adapter
        self.jobs = jobs or Jobs()
        self.client = initial_client
        self.monitor = prefs.get("monitor", True)
        self.current = None
        self.issues = []
        self.marks = []
        self.bubble = None
        self.dialog = None
        self.bridge = None
        self.panel = None
        self.version = 0
        self.rewrite_version = 0
        self.busy_check = False
        self.pending_check = False
        self.rewriting = False
        self.last_status = ""
        self.dot = Dot()
        self.manual = Panel()
        self.external = Panel(external=True)
        self.icon = icon()
        app.setWindowIcon(self.icon)
        self.tray = QSystemTrayIcon(self.icon, self)
        self.menu = QMenu()
        self.menu.addAction("AI 服务与密钥…", self.configure)
        self.menu.addAction("浏览器扩展连接…", self.browser_settings)
        self.watch_action = self.menu.addAction("自动检查当前输入框")
        self.watch_action.setCheckable(True)
        self.watch_action.setChecked(self.monitor)
        self.watch_action.triggered.connect(self.toggle_monitor)
        self.start_action = self.menu.addAction("登录时启动")
        self.start_action.setCheckable(True)
        self.start_action.triggered.connect(self.toggle_startup)
        if sys.platform == "darwin":
            self.menu.addAction("授予辅助功能权限…", self.permissions)
        self.menu.addSeparator()
        self.menu.addAction("退出 WhiteDot", app.quit)
        self.menu.aboutToShow.connect(self.prepare_menu)
        self.menu.aboutToShow.connect(self.clear_marks)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self.tray_click)
        self.dot.menu_at.connect(self.menu.popup)
        self.dot.moved.connect(self.remember_position)
        self.dot.clicked.connect(self.open_dot)
        self.restore_position()
        self.app.screenRemoved.connect(lambda _: self.restore_position())
        self.delay = timer(self, 900, self.run_check, once=True)
        self.poll = timer(self, 450, self.tick)
        self.manual.editor.textChanged.connect(self.manual_edit)
        for panel in (self.manual, self.external):
            panel.closing.connect(self.close_panel)
            panel.rewrite.clicked.connect(self.rewrite)
            panel.editor.issue_click.connect(self.show_issue)
        if not testing and not initial_client:
            try:
                key = self.prefs.get_key()
                if key:
                    self.client = Provider(self.prefs.config, key)
            except (StorageError, ProviderError) as exc:
                self.last_status = str(exc)
        if not testing and self.prefs.get("browser_pair"):
            try:
                self.start_bridge(self.prefs.get("browser_pair"))
            except (OSError, ValueError):
                self.last_status = "浏览器扩展未连接，请检查本机端口或重新启用配对。"
        self.dot.show()
        if not testing:
            self.tray.show()
            self.poll.start()
        self.update_tooltip()

    def prepare_menu(self):
        self.start_action.setChecked(startup.enabled())

    def tray_click(self, reason):
        if reason == QSystemTrayIcon.Trigger and sys.platform != "darwin":
            self.menu.popup(QCursor.pos())

    def permissions(self):
        if self.adapter.permission(prompt=True):
            self.notify("辅助功能权限已开启。")
        else:
            self.notify("请在系统设置 → 隐私与安全性 → 辅助功能中允许 WhiteDot，再回到原输入框。")

    def notify(self, message):
        self.last_status = message
        self.update_tooltip()
        if self.panel:
            self.panel.status.setText(message)
        elif self.tray.isVisible():
            self.tray.showMessage("WhiteDot", message, QSystemTrayIcon.Information, 4500)

    def restore_position(self):
        screen = self.app.primaryScreen()
        r = screen.availableGeometry()
        pos = QPoint(r.right() - 75, r.top() + round(r.height() * .72))
        saved = self.prefs.get("position")
        if isinstance(saved, list) and len(saved) == 2 and all(type(x) is int for x in saved):
            candidate = QPoint(*saved)
            found = self.app.screenAt(candidate + QPoint(28, 28))
            if found:
                screen, pos = found, candidate
        self.dot.move(clamped(pos, self.dot.size(), screen))

    def remember_position(self):
        try:
            self.prefs.set("position", [self.dot.x(), self.dot.y()])
        except StorageError as exc:
            self.notify(str(exc))
        self.place_panel()

    def toggle_startup(self, on):
        try:
            startup.set_enabled(on)
        except OSError:
            self.notify("无法更新登录启动项，请检查账户权限。")
        self.prepare_menu()

    def toggle_monitor(self, on):
        try:
            self.prefs.set("monitor", on)
        except StorageError as exc:
            self.watch_action.setChecked(self.monitor)
            self.notify(str(exc))
            return
        self.monitor = on
        if self.bridge:
            self.bridge.pause(not on)
        self.close_panel()
        self.track(None)
        self.tick()

    def update_tooltip(self):
        status = self.last_status or ("点按查看" if self.client else "右键设置 AI 服务与密钥")
        hint = "WhiteDot · " + status
        self.tray.setToolTip(hint)
        self.dot.setToolTip(hint)

    def start_bridge(self, token):
        from .browser_bridge import BrowserBridge
        bridge = BrowserBridge(token)
        bridge.pause(not self.monitor)
        bridge.start()
        self.bridge = bridge
        self.app.aboutToQuit.connect(bridge.stop)

    def stop_bridge(self):
        if self.bridge:
            self.app.aboutToQuit.disconnect(self.bridge.stop)
            self.bridge.stop()
            self.bridge = None

    def browser_settings(self):
        if self.dialog:
            self.dialog.raise_()
            return
        self.close_panel()
        self.track(None)
        dlg = QDialog(None, Qt.Dialog | Qt.WindowStaysOnTopHint)
        dlg.setWindowTitle("WhiteDot · 浏览器扩展连接")
        dlg.setStyleSheet(STYLE)
        dlg.setMinimumWidth(390)
        box = QVBoxLayout(dlg)
        box.setContentsMargins(18, 16, 18, 16)
        info = QLabel("在 Chrome 或 Edge 加载 WhiteDot 扩展，复制本机配对码并粘贴到扩展设置。两个浏览器可共用此码。")
        info.setWordWrap(True)
        box.addWidget(info)
        status = QLabel()
        status.setWordWrap(True)
        box.addWidget(status)
        row = QHBoxLayout()
        pair = button("启用连接")
        copy = button("复制配对码")
        stop = button("停用连接")
        for b in (pair, copy, stop):
            row.addWidget(b)
        box.addLayout(row)
        box.addWidget(button("完成", dlg.accept))

        def refresh():
            active = self.bridge is not None
            pair.setVisible(not active)
            copy.setVisible(active)
            stop.setVisible(active)
            status.setText("已启用本机连接" if active else "尚未启用本机连接")

        def enable():
            token = secrets.token_urlsafe(32)
            try:
                self.start_bridge(token)
                self.prefs.set("browser_pair", token)
            except (OSError, ValueError, StorageError):
                self.stop_bridge()
                status.setText("启动失败，请检查本机 37831 端口及设置目录权限。")
                return
            refresh()

        def copy_code():
            self.app.clipboard().setText(self.prefs.get("browser_pair"))
            status.setText("配对码已复制，请粘贴到 WhiteDot 浏览器扩展。")

        def disable():
            try:
                self.prefs.set("browser_pair", "")
            except StorageError as exc:
                status.setText(str(exc))
                return
            self.stop_bridge()
            refresh()
        pair.clicked.connect(enable)
        copy.clicked.connect(copy_code)
        stop.clicked.connect(disable)
        refresh()
        self.dialog = dlg
        dlg.finished.connect(self.config_closed)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def configure(self):
        if self.dialog:
            self.dialog.raise_()
            return
        self.close_panel()
        self.track(None)
        dlg = Configuration(self.prefs, self.jobs)
        self.dialog = dlg
        dlg.saved.connect(self.use_client)
        dlg.finished.connect(self.config_closed)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def config_closed(self):
        self.dialog.deleteLater()
        self.dialog = None
        self.tick()

    def use_client(self, client):
        self.client = client
        self.invalidate()
        self.notify("AI 服务验证成功。")

    def capture(self):
        if not self.monitor:
            return None
        try:
            if self.bridge:
                browser = foreground_browser()
                paired = self.bridge.snapshot(browser) if browser else None
                if paired:
                    return paired
            target = self.adapter.capture()
        except (OSError, RuntimeError):
            return None
        return target

    def tick(self):
        if self.dialog or self.menu.isVisible() or self.panel is self.manual:
            return
        if not self.client:
            return  # No automatic reading before model setup.
        target = self.capture()
        new_id = self.identity(target)
        if self.panel is self.external and self.identity(self.current) != new_id:
            self.close_panel()
        if new_id != self.identity(self.current):
            self.track(target)
        else:
            self.current = target
            if target and target.token.startswith("web:"):
                self.publish_issues()
            if self.panel is None:
                self.draw_marks()

    @staticmethod
    def identity(target):
        return (target.token, target.text) if target else None

    def invalidate(self):
        self.version += 1
        self.rewrite_version += 1
        self.rewriting = False
        self.delay.stop()
        self.pending_check = False
        self.issues = []
        self.publish_issues()
        self.manual.editor.mark([])
        self.external.editor.mark([])
        self.clear_marks()
        self.hide_bubble()
        self.last_status = ""
        self.update_tooltip()

    def publish_issues(self):
        if self.bridge:
            self.bridge.publish(self.current if self.monitor and self.client else None, self.issues)

    def track(self, target):
        self.current = target
        self.invalidate()
        if target:
            self.schedule()

    def source(self):
        if self.panel is self.manual:
            return self.manual.editor.toPlainText()
        return self.current.text if self.current else ""

    def status(self, message):
        self.last_status = message
        if self.panel:
            self.panel.status.setText(message)
        self.update_tooltip()

    def schedule(self):
        text = self.source()
        message = input_status(text, MAX_TEXT)
        if not self.client:
            message = "请右键白点或托盘图标，设置 AI 服务与密钥。"
        if self.panel:
            self.panel.rewrite.setEnabled(not message and not self.rewriting)
        self.status(message or "等待校对…")
        if not message:
            self.delay.start()

    def run_check(self):
        text = self.source()
        if not self.client or input_status(text, MAX_TEXT):
            return
        if self.busy_check:
            self.pending_check = True
            return
        if self.panel is not self.manual and not self.still_focused():
            self.tick()
            return
        self.busy_check = True
        self.pending_check = False
        version = self.version
        client = self.client
        if not self.rewriting:
            self.status("正在校对…")

        def complete(issues, error):
            self.busy_check = False
            if version == self.version and self.panel is not self.manual and not self.still_focused():
                self.tick()
            if version == self.version:
                self.issues = issues or []
                self.publish_issues()
                if not self.rewriting:
                    self.status(error or (f"{len(self.issues)} 处建议 · 点击红线查看" if self.issues else "已校对，未发现问题"))
                if self.panel:
                    self.panel.editor.mark(self.issues)
                elif self.still_focused():
                    self.draw_marks()
            if self.pending_check:
                self.pending_check = False
                self.run_check()
        self.jobs.run(lambda: client.check(text), complete)

    def still_focused(self):
        return self.current is not None and self.identity(self.capture()) == self.identity(self.current)

    def clear_marks(self):
        for mark in self.marks:
            mark.hide()

    def draw_marks(self):
        if not self.current or self.current.token.startswith("web:") or not self.issues or self.panel:
            self.clear_marks()
            return
        count = 0
        for issue in self.issues[:32]:
            try:
                rects = self.adapter.rects(self.current, issue.start, issue.end)
            except (OSError, RuntimeError):
                rects = []
            for rect in rects:
                if rect.w <= 0 or rect.h <= 0:
                    continue
                if count == len(self.marks):
                    mark = Mark()
                    mark.clicked.connect(self.show_issue)
                    self.marks.append(mark)
                self.marks[count].display(rect, issue)
                count += 1
                if count >= 48:
                    break
            if count >= 48:
                break
        for mark in self.marks[count:]:
            mark.hide()

    def hide_bubble(self):
        if self.bubble:
            self.bubble.hide()
            self.bubble.deleteLater()
            self.bubble = None

    def show_issue(self, issue, pos):
        self.hide_bubble()
        if issue not in self.issues:
            return
        if self.panel is not self.manual and not self.still_focused():
            self.tick()
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
        text = self.source()
        if version != self.version or text[issue.start:issue.end] != issue.original:
            return
        if self.panel is self.manual:
            cursor = self.manual.editor.textCursor()
            cursor.setPosition(utf16(text[:issue.start]))
            cursor.setPosition(utf16(text[:issue.end]), QTextCursor.KeepAnchor)
            cursor.insertText(word)
            self.manual.editor.setTextCursor(cursor)
            return
        if not self.still_focused():
            self.close_panel()
            self.track(None)
            self.notify("输入框已变化，此建议已过期。")
            return
        try:
            applied = not self.current.token.startswith("web:") and self.adapter.replace(
                self.current, issue.start, issue.end, word)
        except (OSError, RuntimeError):
            applied = False
        if applied:
            self.close_panel()
            self.track(None)
            self.tick()
        else:
            # Exact range writeback is unavailable. Keep the native document intact.
            self.present(self.external)
            self.external.editor.setPlainText(text)
            self.external.editor.mark(self.issues)
            self.external.rewrite.setEnabled(bool(self.client) and not self.rewriting and not input_status(text, MAX_TEXT))
            self.external.result.setPlainText(text[:issue.start] + word + text[issue.end:])
            self.status("此控件未能确认写回。请核对原文，可复制下方修正版。")

    def open_dot(self):
        if self.dialog:
            self.dialog.raise_()
            return
        if self.panel:
            self.close_panel()
            return
        target = self.capture()
        if self.identity(target) != self.identity(self.current):
            self.track(target)
        if target:
            self.present(self.external)
            # Keep skipped private contents out of a secondary window as well.
            preview = target.text if len(target.text) <= MAX_TEXT and not contains_credential(target.text) else ""
            self.external.editor.setPlainText(preview)
            self.external.editor.mark(self.issues)
            self.external.result.clear()
            self.rewrite()
        else:
            self.track(None)
            self.present(self.manual)
            self.manual.activateWindow()
            self.manual.editor.setFocus()
            self.schedule()
            if not self.adapter.permission() and self.client:
                self.status("已打开备用编辑器。授权辅助功能后可检查外部输入框。")

    def present(self, panel):
        self.hide_bubble()
        self.clear_marks()
        self.panel = panel
        self.place_panel()
        panel.show()
        raise_surface(panel)

    def place_panel(self):
        if not self.panel:
            return
        screen = self.dot.screen()
        area = screen.availableGeometry()
        split = not self.panel.result_group.isHidden()
        self.panel.resize(min(394, area.width()), min(382 if split else 212, area.height()))
        x = self.dot.x() - self.panel.width() - 4
        if x < area.left() and self.dot.x() + 60 + self.panel.width() <= area.right():
            x = self.dot.x() + 60
        pos = QPoint(x, self.dot.y() + self.dot.height() - self.panel.height())
        self.panel.move(clamped(pos, self.panel.size(), screen))

    def manual_edit(self):
        if self.panel is not self.manual:
            return
        self.invalidate()
        self.manual.result.clear()
        self.manual.result_group.hide()
        self.place_panel()
        self.schedule()

    def close_panel(self):
        if not self.panel:
            return
        panel = self.panel
        self.panel = None
        panel.hide()
        self.current = None
        self.invalidate()
        panel.result.clear()
        if panel is self.external:
            panel.editor.clear()
        else:
            panel.result_group.hide()

    def rewrite(self):
        if self.rewriting or not self.panel:
            return
        panel = self.panel
        text = self.source()
        message = input_status(text, MAX_TEXT)
        if not self.client:
            message = "请右键白点或托盘图标，设置 AI 服务与密钥。"
        if message:
            self.status(message)
            panel.rewrite.setEnabled(False)
            return
        if panel is self.external and not self.still_focused():
            self.close_panel()
            self.track(None)
            self.notify("外部输入框已变化，请重新点开白点。")
            return
        client = self.client
        self.rewriting = True
        self.rewrite_version += 1
        revision = self.rewrite_version
        panel.result.clear()
        panel.result_group.show()
        self.place_panel()
        panel.rewrite.setEnabled(False)
        self.status("正在重写语法…")

        def complete(result, error):
            if revision != self.rewrite_version or self.panel is not panel:
                return
            self.rewriting = False
            if panel is self.external and not self.still_focused():
                self.close_panel()
                return
            panel.rewrite.setEnabled(True)
            if error:
                self.status(error)
            else:
                panel.result.setPlainText(result)
                self.status("重写完成" if result != text else "语法检查完成，原文可直接使用")
        self.jobs.run(lambda: client.rewrite(text), complete)
