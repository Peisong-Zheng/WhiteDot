import unittest

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from whitedot.types import Issue
from whitedot.windows_ui import Panel, utf16


class EditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["Folio tests", "-platform", "minimal"])

    def setUp(self):
        self.panel = Panel()
        self.panel.resize(self.panel.sizeHint())
        self.panel.show()
        self.app.processEvents()

    def tearDown(self):
        self.panel.hide()
        self.panel.deleteLater()

    def test_rewrite_highlights_words_without_modifying_text_or_line_breaks(self):
        panel = self.panel
        panel.editor.setPlainText("🙂 She go there.\nIt is wet.")
        revised = "🙂 She goes there.\nIt is wet."
        panel.result.setPlainText(revised)
        marks = panel.result.extraSelections()
        self.assertEqual([selection.cursor.selectedText() for selection in marks], ["goes"])
        self.assertEqual(panel.result.toPlainText(), revised)
        panel.result.setPlainText(panel.editor.toPlainText())
        self.assertEqual(panel.result.extraSelections(), [])

    def test_word_count_with_diacritics_contractions_and_hyphens(self):
        self.assertFalse(self.panel.count.isVisible())
        self.panel.editor.setPlainText("naïve")
        self.assertEqual(self.panel.count.text(), "1 word")
        self.assertTrue(self.panel.count.isVisible())
        self.panel.editor.setPlainText("We’re co-authors of 2 résumés.")
        self.assertEqual(self.panel.count.text(), "5 words")
        self.panel.editor.clear()
        self.assertFalse(self.panel.count.isVisible())

    def test_first_draft_has_only_the_writing_controls(self):
        panel = self.panel
        labels = {item.text() for item in panel.findChildren(QLabel) if item.isVisible()}
        self.assertEqual(labels, {"Draft"})
        buttons = {item.accessibleName() or item.text()
                   for item in panel.findChildren(QPushButton) if item.isVisible()}
        self.assertEqual(buttons, {"Hide editor (Esc)", "Copy draft", "Rewrite"})
        self.assertFalse(panel.original_copy.isEnabled())
        self.assertFalse(panel.rewrite.isEnabled())

    def test_last_letter_is_clickable_but_empty_margin_is_not(self):
        editor = self.panel.editor
        text = "A teh sample"
        issue = Issue(2, 5, "teh", ("the",), "Spelling.")
        editor.setPlainText(text)
        editor.mark([issue])
        cur = editor.textCursor()
        cur.setPosition(utf16(text[:5]))
        end = editor.cursorRect(cur)
        cur.movePosition(QTextCursor.PreviousCharacter)
        last = editor.cursorRect(cur)
        point = last.center()
        point.setX(max(point.x(), end.x() - 2))
        self.assertEqual(editor.issue_at(point), issue)
        point.setX(editor.viewport().width() - 2)
        self.assertIsNone(editor.issue_at(point))
