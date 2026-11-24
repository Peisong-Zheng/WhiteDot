"""Exercise the manual editor and input revisions without accessing any user data."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from whitedot.app import Controller, SavedProvider
from whitedot.settings import Settings, StorageError
from whitedot.types import Issue


class DeferredJobs:
    def __init__(self):
        self.pending = []

    def run(self, work, callback):
        self.pending.append((work, callback))

    def finish(self, index=0):
        work, callback = self.pending.pop(index)
        callback(work(), "")

    def fail(self, message):
        _, callback = self.pending.pop(0)
        callback(None, message)


class FixtureModel:
    def __init__(self):
        self.checks = []
        self.rewrites = []

    def check(self, text):
        self.checks.append(text)
        if "teh" not in text:
            return []
        start = text.index("teh")
        return [Issue(start, start + 3, "teh", ("the",), "Spelling")]

    def rewrite(self, text):
        self.rewrites.append(text)
        return text.replace("teh", "the").replace(" go ", " goes ")


class ControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["Folio tests", "-platform", "minimal"])
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
        self.assertIn("teh", [s.cursor.selectedText() for s in selections])
        typo = next(issue for issue in c.issues if issue.original == "teh")
        p.editor.issue_click.emit(typo, QPoint(80, 100))
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
        self.assertEqual([i.original for i in c.issues], ["teh"])
        self.assertEqual(c.grammar_issues, [])
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
        self.assertIn("secret", p.status.text().lower())
        self.jobs.finish()
        self.jobs.finish()
        self.assertEqual(c.issues, [])
        self.assertEqual(p.result.toPlainText(), "")
        self.assertTrue(p.result_group.isHidden())
        self.assertIn("secret", p.status.text().lower())
        self.assertEqual(self.model.checks + self.model.rewrites, [])

    def test_config_error_and_cancel_return_to_existing_draft(self):
        c, p = self.ctrl, self.panel
        c.open_dot()
        p.editor.setPlainText("A draft.")
        next(a for a in c.menu.actions() if a.text() == "AI settings…").trigger()
        self.assertFalse(p.isVisible())
        dlg = c.dialog
        dlg.key.setText("fixture")
        dlg.url.setText("https://fixture.example/v1")
        self.assertEqual(dlg.key.text(), "")
        dlg.key.setText("fixture")
        with patch("whitedot.app.Provider"), patch.object(self.prefs, "save_provider") as save:
            dlg.save.click()
            self.assertFalse(dlg.save.isEnabled())
            _, failed = self.jobs.pending.pop()
            failed(None, "Invalid or expired API key.")
            self.assertTrue(dlg.save.isEnabled())
            self.assertIn("Invalid or expired API key", dlg.message.text())
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
        self.assertEqual([i.original for i in c.issues], ["teh"])
        self.assertEqual(c.grammar_issues, [])
        self.jobs.finish()
        self.assertEqual(self.model.checks, ["Final teh draft."])
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

    def test_first_run_setup_preserves_draft_and_restores_focus(self):
        c, p = self.ctrl, self.panel
        c.client = None
        c.show_editor()
        self.assertTrue(p.context_action.isHidden())
        self.assertTrue(p.status.isHidden())
        p.editor.setPlainText("A teh draft.")
        self.assertFalse(c.delay.isActive())
        self.assertFalse(p.rewrite.isEnabled())
        self.assertEqual(p.context_action.text(), "1 suggestion")
        p.context_action.click()
        self.assertTrue(c.bubble.isVisible())
        self.assertIsNone(c.dialog)
        c.hide_bubble()
        next(a for a in c.menu.actions() if a.text() == "AI settings…").trigger()
        self.assertTrue(c.dialog.isVisible())
        self.assertFalse(c.dialog.save.isEnabled())
        self.assertTrue(c.dialog.save.isDefault())
        c.dialog.reject()
        self.assertTrue(p.isVisible())
        self.assertEqual(p.editor.toPlainText(), "A teh draft.")
        c.show_editor()
        self.assertTrue(p.isVisible())

    def test_retry_failed_check_without_editing_or_duplicate_submission(self):
        c, p = self.ctrl, self.panel
        c.show_editor()
        p.editor.setPlainText("Fix teh word.")
        self.expire_debounce()
        self.jobs.fail("The service took too long to respond.")
        self.assertIn("too long", p.status.text())
        self.assertEqual(p.context_action.text(), "Retry check")
        self.assertFalse(c.delay.isActive())
        p.context_action.click()
        c.run_check()
        self.jobs.finish()
        self.assertFalse(self.jobs.pending)
        self.assertEqual(p.context_action.text(), "1 suggestion")
        self.assertEqual(len(p.editor.extraSelections()), 1)

    def test_review_cycles_and_returns_to_draft(self):
        c, p = self.ctrl, self.panel
        c.show_editor()
        QCoreApplication.processEvents()
        p.editor.setPlainText("teh first and teh last.")
        self.expire_debounce()
        _, complete = self.jobs.pending.pop()
        complete([Issue(0, 3, "teh", ("the",), "Spelling"),
                  Issue(14, 17, "teh", ("the", "that"), "Spelling")], "")
        self.assertEqual(p.context_action.text(), "2 suggestions")
        QTest.keyClick(p.editor, Qt.Key_F7)
        first = c.bubble
        self.assertTrue(first.isVisible())
        self.assertEqual(p.editor.textCursor().position(), 0)
        QTest.keyClick(first.focusWidget(), Qt.Key_Escape)
        QTest.qWait(20)
        self.assertIsNone(c.bubble)
        QTest.keyClick(p.editor, Qt.Key_F7)
        self.assertEqual(p.editor.textCursor().position(), 14)
        QTest.keyClick(c.bubble.focusWidget(), Qt.Key_Down)
        QTest.keyClick(c.bubble.focusWidget(), Qt.Key_Return)
        self.assertEqual(p.editor.toPlainText(), "teh first and that last.")
        self.assertIsNone(c.bubble)

    def test_retry_regeneration_keeps_existing_rewrite(self):
        c, p = self.ctrl, self.panel
        c.show_editor()
        p.editor.setPlainText("Fix teh word.")
        self.expire_debounce()
        self.jobs.finish()
        p.rewrite.click()
        self.jobs.finish()
        p.rewrite.click()
        self.assertEqual(p.result.toPlainText(), "Fix the word.")
        self.jobs.fail("The service is busy.")
        self.assertTrue(p.result_group.isVisible())
        self.assertTrue(p.result_copy.isEnabled())
        self.assertEqual(p.context_action.text(), "Retry rewrite")
        p.context_action.click()
        self.jobs.finish()
        self.assertEqual(p.result.toPlainText(), "Fix the word.")
        self.assertEqual(p.context_action.text(), "1 suggestion")

    def test_quit_protects_uncopied_work_and_respects_explicit_copy(self):
        c, p = self.ctrl, self.panel
        c.show_editor()
        p.editor.setPlainText("A draft to keep.")
        c.close_panel()
        with patch.object(self.app, "quit") as quit_app:
            c.request_quit()
            prompt = c.quit_prompt
            self.assertTrue(prompt.isVisible())
            self.assertEqual(prompt.defaultButton().text(), "Keep writing")
            prompt.defaultButton().click()
            quit_app.assert_not_called()
            self.assertTrue(p.isVisible())
            self.assertEqual(p.editor.toPlainText(), "A draft to keep.")
            clipboard = Mock()
            with patch.object(QApplication, "clipboard", return_value=clipboard):
                p.original_copy.click()
            c.request_quit()
            quit_app.assert_called_once_with()
            self.assertIsNone(c.quit_prompt)

    def test_copy_rewrite_and_quit_uses_finished_result(self):
        c, p = self.ctrl, self.panel
        c.show_editor()
        p.editor.setPlainText("Fix teh word.")
        p.rewrite.click()
        self.jobs.finish()
        with patch.object(self.app, "quit") as quit_app, patch.object(self.app, "clipboard") as clipboard:
            c.request_quit()
            prompt = c.quit_prompt
            btn = next(b for b in prompt.buttons() if b.text() == "Copy rewrite and quit")
            btn.click()
            clipboard.return_value.setText.assert_called_once_with("Fix the word.")
            quit_app.assert_called_once_with()


    def test_login_item_recovers_after_unreadable_registry(self):
        c = self.ctrl
        with patch("whitedot.app.startup.enabled", side_effect=[PermissionError(), True]):
            c.prepare_menu()
            self.assertFalse(c.start_action.isEnabled())
            c.prepare_menu()
            self.assertTrue(c.start_action.isEnabled())
            self.assertTrue(c.start_action.isChecked())

    def test_saved_custom_profile_reappears_when_switching_providers(self):
        from whitedot.provider import ProviderConfig
        custom = ProviderConfig("Custom", "https://custom.example/v1", "writing-model")
        self.prefs.save_provider(custom, "fixture-key")
        with patch.object(self.prefs, "get_key", side_effect=AssertionError("unexpected key read")):
            self.ctrl.configure()
            dialog = self.ctrl.dialog
            self.assertEqual(dialog.key.text(), "")
            self.assertTrue(dialog.key.isHidden())
            self.assertTrue(dialog.saved_key.isVisible())
            self.assertFalse(dialog.save.isEnabled())
            dialog.provider.setCurrentText("OpenAI")
            self.assertTrue(dialog.key.isVisible())
            dialog.provider.setCurrentText("Custom")
            self.assertEqual((dialog.url.text(), dialog.model.text()), (custom.base_url, custom.model))
            dialog.change_key.click()
            self.assertTrue(dialog.key.isVisible())
            self.assertEqual(dialog.key.text(), "")
            dialog.key.setText("replacement")
            dialog.change_key.click()
            self.assertEqual(dialog.key.text(), "")
            self.assertFalse(dialog.save.isEnabled())
            dialog.reject()

    def test_edit_model_reuses_key_only_on_deliberate_save(self):
        from whitedot.provider import PRESETS
        self.prefs.save_provider(PRESETS["DeepSeek"], "fixture-key")
        with patch.object(self.prefs, "get_key", return_value="fixture-key") as read, \
                patch("whitedot.app.Provider") as provider:
            self.ctrl.configure()
            dialog = self.ctrl.dialog
            dialog.model.setText("other-model")
            self.assertTrue(dialog.save.isEnabled())
            read.assert_not_called()
            dialog.save.click()
            self.jobs.finish()
            read.assert_called_once()
            provider.return_value.validate.assert_called_once()
            self.assertEqual(self.prefs.config.model, "other-model")

    def test_only_real_request_uses_local_key_and_failure_needs_explicit_retry(self):
        from whitedot.provider import PRESETS
        self.prefs.save_provider(PRESETS["DeepSeek"], "fixture-key")
        c, p = self.ctrl, self.panel
        # Simulate a new process with a saved local connection.
        c.prefs = Settings(self.prefs._path)
        c.client = SavedProvider(c.prefs)
        with patch.object(c.prefs, "get_key", side_effect=[StorageError("Access denied."), "fixture-key"]) as read, \
                patch("whitedot.app.Provider", return_value=self.model):
            c.show_editor()
            c.configure()
            c.dialog.reject()
            self.assertFalse(c.delay.isActive())
            read.assert_not_called()
            p.editor.setPlainText("Please check teh word.")
            self.expire_debounce()
            work, done = self.jobs.pending.pop()
            with self.assertRaises(StorageError) as failed:
                work()
            done(None, str(failed.exception))
            self.assertEqual(p.context_action.text(), "Retry access")
            p.editor.setPlainText("Retry teh draft.")
            self.assertFalse(c.delay.isActive())
            self.assertFalse(p.rewrite.isEnabled())
            c.close_panel()
            c.show_editor()
            self.assertFalse(c.delay.isActive())
            self.assertEqual(read.call_count, 1)
            p.context_action.click()
            self.jobs.finish()
            self.assertEqual(read.call_count, 2)
            p.rewrite.click()
            self.jobs.finish()
            self.assertEqual(read.call_count, 2)
            self.assertEqual(p.result.toPlainText(), "Retry the draft.")

    def test_draft_hidden_while_loading_a_profile_is_never_sent(self):
        c, p = self.ctrl, self.panel
        c.client = SavedProvider(self.prefs)
        c.show_editor()
        p.editor.setPlainText("A private draft.")
        self.expire_debounce()

        def allow_after_closing(_config):
            c.close_panel()
            return "fixture-key"

        with patch.object(self.prefs, "get_key", side_effect=allow_after_closing), \
                patch("whitedot.app.Provider", return_value=self.model):
            self.jobs.finish()
        self.assertFalse(p.isVisible())
        self.assertEqual(self.model.checks, [])


    def test_offline_typing_marks_finished_words_and_paste_immediately(self):
        c, p = self.ctrl, self.panel
        c.client = None
        c.show_editor()
        QTest.keyClicks(p.editor, "teh")
        self.assertTrue(c.word_delay.isActive())
        self.assertFalse(c.issues)
        QTest.keyClicks(p.editor, " ")
        self.assertEqual([s.cursor.selectedText() for s in p.editor.extraSelections()], ["teh"])
        self.assertIsNone(c.check_inflight)
        QTest.keyClicks(p.editor, "cat")
        self.assertEqual([s.cursor.selectedText() for s in p.editor.extraSelections()], ["teh"])
        self.assertFalse(c.delay.isActive())
        p.editor.setPlainText("I can recieve teh letter")
        self.assertEqual([i.original for i in c.issues], ["recieve", "teh"])
        self.assertEqual(self.jobs.pending, [])

    def test_legacy_profile_keeps_key_setup_in_the_menu(self):
        from whitedot.settings import _account
        c, p = self.ctrl, self.panel
        self.prefs.set("accounts", [_account(self.prefs.config)])
        c.client = None
        c.show_editor()
        self.assertTrue(p.context_action.isHidden())
        self.assertTrue(p.status.isHidden())
        p.editor.setPlainText("Fix teh draft.")
        self.assertEqual([i.original for i in c.issues], ["teh"])
        self.assertFalse(c.delay.isActive())
        self.assertFalse(p.rewrite.isEnabled())
        self.assertEqual(p.context_action.text(), "1 suggestion")
        self.assertTrue(p.status.isHidden())
        p.editor.setPlainText("Fix the draft.")
        self.assertTrue(p.context_action.isHidden())
        self.assertTrue(p.status.isHidden())
        next(a for a in c.menu.actions() if a.text() == "AI settings…").trigger()
        self.assertTrue(c.dialog.key.isVisible())
        self.assertFalse(c.dialog.key.text())

    def test_inflight_grammar_is_reused_only_for_whole_unchanged_sentences(self):
        c, p = self.ctrl, self.panel
        c.show_editor()
        first = "The agency plan ahead."
        p.editor.setPlainText(first)
        self.assertTrue(c.sentence_delay.isActive())
        p.editor.moveCursor(p.editor.textCursor().MoveOperation.End)
        p.editor.insertPlainText(" More")
        self.assertTrue(c.sentence_delay.isActive())
        c.sentence_delay.timeout.emit()
        work, complete = self.jobs.pending.pop()
        work()
        p.editor.insertPlainText(" sentences with teh typo.")
        correct = Issue(11, 15, "plan", ("plans",), "Use a singular verb.")
        complete([correct], "")
        self.assertEqual([i.original for i in c.issues], ["plan", "teh"])
        p.editor.moveCursor(p.editor.textCursor().MoveOperation.Start)
        p.editor.insertPlainText("Intro. ")
        self.assertEqual(c.issues[0].start, 18)
        p.editor.setPlainText("The agencies plan ahead. More sentences with teh typo.")
        self.assertEqual([i.original for i in c.issues], ["teh"])

    def test_late_remote_result_cannot_undo_offline_fix_or_duplicate_marks(self):
        c, p = self.ctrl, self.panel
        c.show_editor()
        p.editor.setPlainText("Check teh draft.")
        self.expire_debounce()
        _, complete = self.jobs.pending.pop()
        typo = c.issues[0]
        c.apply(typo, "the", c.version)
        complete([typo], "")
        self.assertEqual(p.editor.toPlainText(), "Check the draft.")
        self.assertEqual(c.issues, [])
        p.editor.setPlainText("Check teh draft.")
        self.expire_debounce()
        self.jobs.finish()
        self.assertEqual(len(c.issues), 1)
        self.assertEqual(len(p.editor.extraSelections()), 1)
