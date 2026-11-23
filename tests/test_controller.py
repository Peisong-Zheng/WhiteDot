"""Exercise the manual editor and input revisions without accessing any user data."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PySide6.QtCore import QCoreApplication, QEvent, QPoint
from PySide6.QtWidgets import QApplication

from whitedot.app import Controller
from whitedot.settings import Settings
from whitedot.types import Issue


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


class ControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["WhiteDot tests", "-platform", "minimal"])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.prefs = Settings(Path(tmp) / "settings.json")
        self.jobs = DeferredJobs()
        self.model = FixtureModel()
        self.ctrl = Controller(self.app, self.prefs, jobs=self.jobs, initial_client=self.model, testing=True)
        self.panel = self.ctrl.panel

    def tearDown(self):
        c = self.ctrl
        if c.dialog:
            c.dialog.reject()
        c.delay.stop()
        c.close_panel()
        c.hide_bubble()
        for widget in [c.panel, c.dot, c.menu]:
            widget.hide()
            widget.deleteLater()
        c.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def expire_debounce(self):
        timer = self.ctrl.delay
        self.assertTrue(timer.isActive())
        timer.stop()
        timer.timeout.emit()

    def test_suggestions_split_rewrite_and_copy(self):
        c, p = self.ctrl, self.panel
        self.assertFalse(p.isVisible())
        self.assertFalse(c.delay.isActive())
        c.dot.clicked.emit()
        self.assertTrue(p.isVisible())
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

    def test_reopening_checked_draft_reuses_results_without_resending(self):
        c, p = self.ctrl, self.panel
        c.dot.clicked.emit()
        p.editor.setPlainText("A teh draft.")
        self.expire_debounce()
        self.jobs.finish()
        p.rewrite.click()
        self.jobs.finish()
        p.closing.emit()
        self.assertFalse(p.isVisible())
        c.dot.clicked.emit()
        self.assertEqual(p.editor.toPlainText(), "A teh draft.")
        self.assertEqual(p.result.toPlainText(), "A the draft.")
        self.assertTrue(p.result_group.isVisible())
        self.assertFalse(c.delay.isActive())
        self.assertEqual(len(p.editor.extraSelections()), 1)
        self.assertEqual(self.model.checks, ["A teh draft."])

    def test_collapsing_before_debounce_never_submits(self):
        c, p = self.ctrl, self.panel
        c.dot.clicked.emit()
        p.editor.setPlainText("My private draft.")
        c.dot.clicked.emit()
        self.assertFalse(c.delay.isActive())
        c.run_check()
        c.rewrite()
        self.assertEqual(self.jobs.pending, [])
        self.assertEqual(self.model.checks + self.model.rewrites, [])

    def test_collapse_and_reopen_ignores_inflight_returns(self):
        c, p = self.ctrl, self.panel
        c.dot.clicked.emit()
        p.editor.setPlainText("Check teh grammar.")
        self.expire_debounce()
        p.rewrite.click()
        c.dot.clicked.emit()
        self.jobs.finish()
        self.jobs.finish()
        self.assertTrue(p.result_group.isHidden())
        self.assertEqual(p.result.toPlainText(), "")
        self.assertFalse(c.issues)
        c.dot.clicked.emit()
        self.expire_debounce()
        self.jobs.finish()
        self.assertEqual(len(c.issues), 1)
        self.assertTrue(p.rewrite.isEnabled())

    def test_late_responses_cannot_restore_prior_draft(self):
        c, p = self.ctrl, self.panel
        c.dot.clicked.emit()
        p.editor.setPlainText("Check teh grammar.")
        self.expire_debounce()
        p.rewrite.click()
        # Synthetic placeholder, never sent to a model.
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

    def test_config_error_and_cancel_return_to_existing_draft(self):
        c, p = self.ctrl, self.panel
        c.open_dot()
        p.editor.setPlainText("A draft.")
        p.settings_requested.emit()
        self.assertFalse(p.isVisible())
        dlg = c.dialog
        dlg.key.setText("fixture")
        dlg.url.textEdited.emit("https://fixture.example/v1")
        self.assertEqual(dlg.key.text(), "")
        dlg.key.setText("fixture")
        with patch("whitedot.app.Provider"), patch.object(self.prefs, "save_provider") as save:
            dlg.save.click()
            self.assertFalse(dlg.save.isEnabled())
            _, failed = self.jobs.pending.pop()
            failed(None, "密钥无效或已过期")
            self.assertTrue(dlg.save.isEnabled())
            self.assertIn("密钥无效", dlg.message.text())
            save.assert_not_called()
            dlg.save.click()
            dlg.reject()
            self.jobs.finish()
            save.assert_not_called()
        self.assertIs(c.client, self.model)
        self.assertIsNone(c.dialog)
        self.assertTrue(p.isVisible())
        self.assertEqual(p.editor.toPlainText(), "A draft.")

    def test_busy_check_coalesces_revisions(self):
        c, p = self.ctrl, self.panel
        c.open_dot()
        for draft in ["First teh draft.", "Second teh draft.", "Final teh draft."]:
            p.editor.setPlainText(draft)
            self.expire_debounce()
        self.assertEqual(len(self.jobs.pending), 1)
        self.jobs.finish()
        self.assertEqual(c.issues, [])
        self.jobs.finish()
        self.assertEqual(self.model.checks, ["First teh draft.", "Final teh draft."])
        self.assertEqual(len(c.issues), 1)

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
