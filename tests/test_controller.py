"""Exercise the actual Qt panels with deterministic focus and async completions."""

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from PySide6.QtCore import QCoreApplication, QEvent, QPoint
from PySide6.QtWidgets import QApplication

from whitedot.app import Controller
from whitedot.settings import Settings
from whitedot.types import Issue, Rect, Target


class FixtureAdapter:
    def __init__(self):
        self.target = None
        self.geometry = [Rect(60, 75, 24, 16)]
        self.writable = True
        self.writes = []

    def capture(self):
        return self.target

    def permission(self, prompt=False):
        return True

    def rects(self, target, start, end):
        return self.geometry if target == self.target else []

    def replace(self, target, start, end, word):
        self.writes.append((target, start, end, word))
        if not self.writable or self.target != target:
            return False
        self.target = replace(target, text=target.text[:start] + word + target.text[end:])
        return True


class DeferredJobs:
    def __init__(self):
        self.pending = []

    def run(self, work, callback):
        self.pending.append((work, callback))

    def finish(self, index=0):
        work, callback = self.pending.pop(index)
        callback(work(), "")


class FixtureModel:
    def __init__(self):
        self.checks = []
        self.rewrites = []

    def check(self, text):
        self.checks.append(text)
        if "teh" not in text:
            return []
        start = text.index("teh")
        return [Issue(start, start + 3, "teh", ("the",), "拼写错误")]

    def rewrite(self, text):
        self.rewrites.append(text)
        return text.replace("teh", "the").replace(" go ", " goes ")


def field(text, token="browser.1"):
    return Target(token, text, "Browser fixture", Rect(32, 45, 240, 100))


class ControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The minimal plugin creates in-process surfaces without window-server,
        # clipboard or accessibility access.
        cls.app = QApplication.instance() or QApplication(["WhiteDot tests", "-platform", "minimal"])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.prefs = Settings(Path(tmp) / "settings.json")
        self.jobs = DeferredJobs()
        self.adapter = FixtureAdapter()
        self.model = FixtureModel()
        self.ctrl = Controller(
            self.app, self.prefs, self.adapter, jobs=self.jobs,
            initial_client=self.model, testing=True,
        )

    def tearDown(self):
        c = self.ctrl
        c.delay.stop()
        c.close_panel()
        c.hide_bubble()
        for widget in [c.manual, c.external, c.dot, c.menu, *c.marks]:
            widget.hide()
            widget.deleteLater()
        c.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def expire_debounce(self):
        timer = self.ctrl.delay
        self.assertTrue(timer.isActive())
        timer.stop()
        timer.timeout.emit()

    def ready_external(self, text="😀 She go to teh library."):
        self.adapter.target = field(text)
        self.ctrl.tick()
        self.expire_debounce()
        self.jobs.finish()
        self.assertEqual(len(self.ctrl.issues), 1)
        return self.ctrl.issues[0]

    def test_external_check_repositions_marks_and_accepts_candidate(self):
        c = self.ctrl
        issue = self.ready_external()
        self.assertIsNone(c.panel)
        mark = c.marks[0]
        self.assertTrue(mark.isVisible())
        self.assertEqual(mark.x(), 60)
        self.adapter.geometry = [Rect(100, 140, 24, 16)]
        c.tick()
        self.assertEqual(mark.x(), 100)
        self.assertEqual(len(self.model.checks), 1)
        mark.clicked.emit(issue, QPoint(110, 150))
        c.bubble.chosen.emit("the")
        self.assertEqual(self.adapter.target.text, "😀 She go to the library.")
        self.assertEqual(len(self.adapter.writes), 1)
        self.assertFalse(mark.isVisible())
        self.assertTrue(c.delay.isActive())

    def test_white_dot_in_external_field_previews_whole_rewrite_without_edit(self):
        c = self.ctrl
        self.ready_external()
        c.dot.clicked.emit()
        self.assertIs(c.panel, c.external)
        self.assertTrue(c.external.editor.isReadOnly())
        self.assertTrue(c.external.result_group.isVisible())
        self.assertFalse(c.external.result_copy.isEnabled())
        self.assertFalse(c.marks[0].isVisible())
        self.jobs.finish()
        self.assertEqual(self.model.rewrites, [self.adapter.target.text])
        self.assertEqual(c.external.result.toPlainText(), "😀 She goes to the library.")
        self.assertEqual(self.adapter.writes, [])
        c.dot.clicked.emit()
        self.assertIsNone(c.panel)
        self.assertEqual(c.external.editor.toPlainText(), "")

    def test_manual_fix_split_preview_and_copy(self):
        c = self.ctrl
        c.dot.clicked.emit()
        p = c.manual
        self.assertIs(c.panel, p)
        self.assertFalse(p.original_copy.isEnabled())
        self.assertFalse(p.result_copy.isEnabled())
        self.assertTrue(p.result_group.isHidden())
        p.editor.setPlainText("😀 She go to teh library.")
        self.expire_debounce()
        self.jobs.finish()
        selections = p.editor.extraSelections()
        self.assertEqual(selections[0].cursor.selectedText(), "teh")
        p.editor.issue_click.emit(c.issues[0], QPoint(80, 100))
        c.bubble.chosen.emit("the")
        self.assertEqual(p.editor.toPlainText(), "😀 She go to the library.")
        p.rewrite.click()
        self.jobs.finish()
        self.assertTrue(p.result_group.isVisible())
        self.assertTrue(p.result_copy.isEnabled())
        self.assertEqual(p.result.toPlainText(), "😀 She goes to the library.")
        clipboard = Mock()
        with patch.object(QApplication, "clipboard", return_value=clipboard):
            p.result_copy.click()
        clipboard.setText.assert_called_once_with("😀 She goes to the library.")
        self.assertNotEqual(p.editor.toPlainText(), p.result.toPlainText())

    def test_late_manual_check_and_rewrite_cannot_restore_sensitive_text(self):
        c = self.ctrl
        c.dot.clicked.emit()
        p = c.manual
        p.editor.setPlainText("Check teh grammar.")
        self.expire_debounce()
        p.rewrite.click()
        self.assertEqual(len(self.jobs.pending), 2)
        # A deliberately nonfunctional credential-shaped fixture.
        p.editor.setPlainText("api_key=test_fixture_only_12345")
        self.assertFalse(c.delay.isActive())
        self.assertFalse(p.rewrite.isEnabled())
        self.assertIn("密钥", p.status.text())
        self.jobs.finish()
        self.jobs.finish()
        self.assertEqual(c.issues, [])
        self.assertEqual(p.result.toPlainText(), "")
        self.assertTrue(p.result_group.isHidden())
        self.assertIn("密钥", p.status.text())
        self.assertEqual(self.model.checks + self.model.rewrites, ["Check teh grammar."] * 2)

    def test_stale_candidate_cannot_write_to_different_field_with_identical_text(self):
        c = self.ctrl
        issue = self.ready_external()
        c.show_issue(issue, QPoint(50, 80))
        self.adapter.target = replace(self.adapter.target, token="browser.2")
        c.bubble.chosen.emit("the")
        self.assertEqual(self.adapter.writes, [])
        self.assertIsNone(c.current)
        self.assertFalse(c.marks[0].isVisible())
        self.assertIn("过期", c.last_status)

    def test_unsupported_range_write_offers_copyable_correction(self):
        c = self.ctrl
        issue = self.ready_external()
        self.adapter.writable = False
        original = self.adapter.target.text
        c.show_issue(issue, QPoint(50, 80))
        c.bubble.chosen.emit("the")
        self.assertIs(c.panel, c.external)
        self.assertEqual(self.adapter.target.text, original)
        self.assertEqual(c.external.result.toPlainText(), original.replace("teh", "the"))
        self.assertTrue(c.external.result_copy.isEnabled())
        self.assertTrue(c.external.rewrite.isEnabled())

    def test_focus_change_between_poll_and_external_check_completion(self):
        c = self.ctrl
        self.adapter.target = field("Check teh spelling.")
        c.tick()
        self.expire_debounce()
        c.dot.clicked.emit()  # opens external preview and queues its own rewrite
        self.adapter.target = field("New field.", "browser.2")
        self.jobs.finish()  # old check returns before the next focus poll
        self.assertIsNone(c.panel)
        self.assertEqual(c.external.editor.toPlainText(), "")
        self.assertEqual(c.issues, [])
        self.jobs.finish()  # old rewrite also arrives
        self.assertEqual(c.external.result.toPlainText(), "")

    def test_sensitive_external_field_never_appears_in_preview_or_model_jobs(self):
        c = self.ctrl
        self.adapter.target = field("api_key=test_fixture_only_12345")
        c.tick()
        self.assertFalse(c.delay.isActive())
        c.dot.clicked.emit()
        self.assertEqual(self.jobs.pending, [])
        self.assertEqual(c.external.editor.toPlainText(), "")
        self.assertEqual(c.external.result.toPlainText(), "")
        self.assertFalse(c.external.original_copy.isEnabled())
        self.assertFalse(c.external.rewrite.isEnabled())
        self.assertIn("密钥", c.last_status)

    def test_config_error_cancel_and_endpoint_change_do_not_save_unverified_key(self):
        c = self.ctrl
        c.configure()
        dlg = c.dialog
        dlg.key.setText("fixture")
        dlg.url.textEdited.emit("https://fixture.example/v1")
        self.assertEqual(dlg.key.text(), "")
        dlg.key.setText("fixture")
        with patch("whitedot.app.Provider") as provider, patch.object(self.prefs, "save_provider") as save:
            dlg.save.click()
            self.assertFalse(dlg.save.isEnabled())
            _, failed = self.jobs.pending.pop()
            failed(None, "密钥无效或已过期")
            self.assertTrue(dlg.save.isEnabled())
            self.assertIn("密钥无效", dlg.message.text())
            save.assert_not_called()

            dlg.save.click()
            dlg.reject()  # the worker can still finish after the dialog closes
            self.jobs.finish()
            save.assert_not_called()
            self.assertIs(c.client, self.model)
            self.assertIsNone(c.dialog)
            self.assertTrue(provider.called)

    def test_busy_check_coalesces_revisions_and_skips_intermediate_input(self):
        c = self.ctrl
        self.adapter.target = field("First teh draft.")
        c.tick()
        self.expire_debounce()
        self.adapter.target = field("Second teh draft.")
        c.tick()
        self.expire_debounce()
        self.adapter.target = field("Final teh draft.")
        c.tick()
        self.expire_debounce()
        self.assertEqual(len(self.jobs.pending), 1)
        self.jobs.finish()
        self.assertEqual(c.issues, [])
        self.assertEqual(len(self.jobs.pending), 1)
        self.jobs.finish()
        self.assertEqual(self.model.checks, ["First teh draft.", "Final teh draft."])
        self.assertEqual(c.issues[0].start, len("Final "))

    def test_paired_browser_supplies_source_and_receives_exact_issues(self):
        from whitedot.browser_bridge import BrowserBridge
        c = self.ctrl
        c.bridge = BrowserBridge("test-pair-" * 4)
        payload = {"browser": "chrome", "field": "page-field", "text": "Fix teh word."}
        c.bridge._sync(payload)
        with patch("whitedot.app.foreground_browser", return_value="chrome"):
            c.tick()
            self.expire_debounce()
            self.jobs.finish()
            response = c.bridge._sync(payload)
            self.assertTrue(response["active"])
            self.assertEqual(response["issues"][0]["original"], "teh")
            self.assertFalse(c.marks)
            c.open_dot()
            self.jobs.finish()
            self.assertEqual(c.external.result.toPlainText(), "Fix the word.")
        with patch("whitedot.app.foreground_browser", return_value=None):
            c.tick()
            self.assertIsNone(c.panel)
            self.assertFalse(c.bridge._sync(payload)["active"])

    def test_pause_clears_paired_browser_snapshot(self):
        from whitedot.browser_bridge import BrowserBridge
        c = self.ctrl
        c.bridge = BrowserBridge("test-pair-" * 4)
        payload = {"browser": "edge", "field": "draft", "text": "Private field."}
        c.bridge._sync(payload)
        c.toggle_monitor(False)
        self.assertIsNone(c.bridge.snapshot("edge"))
        self.assertTrue(c.bridge._sync(payload)["paused"])
        c.open_dot()
        self.assertIs(c.panel, c.manual)
        self.assertFalse(self.jobs.pending)

    def test_dot_position_roundtrip_and_disconnected_screen(self):
        c = self.ctrl
        area = self.app.primaryScreen().availableGeometry()
        wanted = area.topLeft() + QPoint(28, 38)
        c.dot.move(wanted)
        c.remember_position()
        c.dot.move(area.topLeft())
        c.restore_position()
        self.assertEqual(c.dot.pos(), wanted)
        self.prefs.set("position", [-100000, -100000])
        c.restore_position()
        self.assertTrue(area.contains(c.dot.geometry()))
