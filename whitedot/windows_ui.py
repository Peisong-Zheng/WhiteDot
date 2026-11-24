"""Floating launcher and writing surfaces shared by both desktop platforms."""
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
import re
import sys

from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFontDatabase, QIcon, QKeySequence, QPainter, QPainterPath,
                           QPalette, QPen, QPixmap, QRadialGradient, QShortcut, QTextCharFormat, QTextCursor)
from PySide6.QtWidgets import (QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                               QTextEdit, QVBoxLayout, QWidget)

TOP = Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
NO_FOCUS = TOP | Qt.WindowDoesNotAcceptFocus
WORDS = re.compile(r"[^\W_]+(?:[’'-][^\W_]+)*")

STYLE = """
QWidget { color:#232a36; font-size:13px; }
QDialog { background:#fafbfc; }
QLabel { background:transparent; }
QLabel#heading { font-size:18px; font-weight:600; }
QLabel#sectionLabel { font-size:12px; color:#4c566d; font-weight:600; }
QLabel#count, QLabel#caption { font-size:12px; color:#5e6878; }
QPushButton#context { color:#344b84; font-weight:600; text-align:left; padding:3px 4px; }
QComboBox QAbstractItemView { background:white; color:#232a36; selection-background-color:#d9e3ff; selection-color:#182444; }
QLabel#word { font-family:Spectral; font-size:20px; color:#222e46; }
QFrame#rule { background:#e0e3e9; border:none; }
QTextEdit { border:0; padding:0; background:transparent; color:#242a38;
  placeholder-text-color:#687283; selection-background-color:#d9e3ff; selection-color:#182444; font-family:Spectral; font-size:21px; }
QLineEdit, QComboBox { background:white; color:#252e40; border:1px solid #c2c9d3;
  border-radius:6px; min-height:24px; padding:4px 8px; placeholder-text-color:#687283; selection-background-color:#d9e3ff; }
QComboBox::drop-down { subcontrol-origin:padding; subcontrol-position:center right; width:24px; border:0; }
QLineEdit:focus, QComboBox:focus { border-color:#435a99; }
QPushButton { background:transparent; color:#46516b; border:1px solid transparent;
  border-radius:6px; min-height:20px; padding:4px 8px; font-weight:500; }
QPushButton:hover { background:#e9ecf3; color:#253652; }
QPushButton:pressed { background:#dde2ed; }
QPushButton:focus { border-color:#6479b1; }
QPushButton:disabled { color:#87909e; }
QPushButton#action { background:#354252; color:white; border:1px solid #354252; padding:4px 12px; }
QPushButton#action:hover { background:#293545; }
QPushButton#action:pressed { background:#202a36; }
QPushButton#action:focus { border:2px solid #849be0; }
QPushButton#action:disabled { color:#737d91; background:#e5e8ee; border-color:#e5e8ee; }
QPushButton#tool { padding:0; min-height:0; }
QPushButton#candidate { background:#edf1fb; color:#293e71; text-align:left; padding:6px 11px; }
QPushButton#candidate:hover { background:#dfe7fb; }
QScrollBar:vertical { background:transparent; width:5px; margin:0; }
QScrollBar::handle:vertical { background:#bac2d0; border-radius:2px; min-height:20px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
QScrollBar::sub-page:vertical, QScrollBar::add-page:vertical { background:transparent; }
"""


@lru_cache(maxsize=1)
def load_typeface():
    return QFontDatabase.addApplicationFont(str(Path(__file__).with_name("assets") / "Spectral-Regular.ttf"))


def native_float(widget):
    widget.setAttribute(Qt.WA_MacAlwaysShowToolWindow, True)
    if widget.windowFlags() & Qt.WindowDoesNotAcceptFocus:
        widget.setAttribute(Qt.WA_ShowWithoutActivating)
    if sys.platform == "darwin" and QApplication.platformName() == "cocoa":
        import objc
        from AppKit import (NSWindowCollectionBehaviorCanJoinAllSpaces,
                            NSWindowCollectionBehaviorFullScreenAuxiliary, NSStatusWindowLevel)
        view = objc.objc_object(c_void_p=int(widget.winId()))
        window = view.window()
        if window:
            window.setHasShadow_(False)  # The launcher and paper both draw their own shadow.
            window.setHidesOnDeactivate_(False)
            window.setLevel_(NSStatusWindowLevel)
            window.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces |
                                          NSWindowCollectionBehaviorFullScreenAuxiliary)


def raise_surface(widget):
    if (sys.platform == "darwin" and QApplication.platformName() == "cocoa"
            and widget.windowFlags() & Qt.WindowDoesNotAcceptFocus):
        import objc
        view = objc.objc_object(c_void_p=int(widget.winId()))
        view.window().orderFrontRegardless()
    else:
        widget.raise_()


def dot_art(p, size, tray=False):
    """One center for the face, rim and full radial falloff at any pixel density."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / 56, size / 56)
    center = QPointF(28, 28)
    shadow = QRadialGradient(center, 27)
    shadow.setColorAt(0, QColor(29, 36, 49, 74))
    shadow.setColorAt(.65, QColor(29, 36, 49, 74))
    shadow.setColorAt(.76, QColor(29, 36, 49, 42))
    shadow.setColorAt(.88, QColor(29, 36, 49, 13))
    shadow.setColorAt(1, QColor(29, 36, 49, 0))
    p.setPen(Qt.NoPen)
    p.setBrush(shadow)
    p.drawEllipse(center, 27, 27)
    p.setPen(QPen(QColor("#8a93a3" if tray else "#aeb4bf"), .85))
    p.setBrush(QColor("#edf0f4"))
    p.drawEllipse(center, 18.5, 18.5)
    p.setPen(QPen(QColor("#d4d9e1"), .85))
    p.setBrush(Qt.white)
    p.drawEllipse(center, 15.5, 15.5)
    p.restore()


def icon():
    pix = QPixmap(112, 112)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    dot_art(p, 112, True)
    p.end()
    return QIcon(pix)


def glyph(kind):
    out = QIcon()
    for mode, ink in [(QIcon.Normal, "#535e75"), (QIcon.Disabled, "#8792a3")]:
        pix = QPixmap(48, 48)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.scale(2, 2)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(ink), 1.65, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        if kind == "close":
            p.drawLine(QPointF(7, 7), QPointF(17, 17))
            p.drawLine(QPointF(17, 7), QPointF(7, 17))
        elif kind == "copy":
            p.drawRoundedRect(QRectF(8.5, 8.5, 11, 12), 2.3, 2.3)
            path = QPainterPath(QPointF(15.5, 5.6))
            path.quadTo(15.5, 3.5, 13.4, 3.5)
            path.lineTo(6.2, 3.5)
            path.quadTo(4.3, 3.5, 4.3, 5.5)
            path.lineTo(4.3, 13.4)
            path.quadTo(4.3, 15.5, 6.2, 15.5)
            p.drawPath(path)
        p.end()
        pix.setDevicePixelRatio(2)
        out.addPixmap(pix, mode)
    return out


def clamped(pos, size, screen):
    r = screen.availableGeometry()
    return QPoint(max(r.left(), min(pos.x(), r.right() - size.width() + 1)),
                  max(r.top(), min(pos.y(), r.bottom() - size.height() + 1)))


class Dot(QWidget):
    clicked = Signal()
    moved = Signal()
    menu_at = Signal(QPoint)

    def __init__(self):
        super().__init__(None, NO_FOCUS | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(56, 56)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Click to write in Folio. Drag to move.")
        self.setAccessibleName("Open or hide the Folio editor")
        self.origin = None
        self.dragging = False
        native_float(self)

    def paintEvent(self, event):
        p = QPainter(self)
        dot_art(p, self.width())

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.menu_at.emit(event.globalPosition().toPoint())
        elif event.button() == Qt.LeftButton:
            self.origin = event.globalPosition().toPoint()
            self.offset = self.origin - self.pos()
            self.dragging = False

    def mouseMoveEvent(self, event):
        if self.origin is None:
            return
        pos = event.globalPosition().toPoint()
        if (pos - self.origin).manhattanLength() >= QApplication.startDragDistance():
            self.dragging = True
        if self.dragging:
            self.move(clamped(pos - self.offset, self.size(), QApplication.screenAt(pos) or self.screen()))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.origin is not None:
            self.origin = None
            if self.dragging:
                self.moved.emit()
            else:
                self.clicked.emit()


class Paper(QWidget):
    def __init__(self, flags, parent=None):
        super().__init__(parent, flags | Qt.NoDropShadowWindowHint)
        load_typeface()
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(STYLE)
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(29, 17, 29, 21)
        self.box.setSpacing(0)
        native_float(self)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        shell = QRectF(self.rect()).adjusted(7, 6, -7, -8)
        p.setPen(Qt.NoPen)
        for pad, opacity in [(5.5, 5), (4, 7), (2.5, 10), (1, 14)]:
            p.setBrush(QColor(30, 40, 65, opacity))
            r = shell.adjusted(-pad, -pad, pad, pad).translated(0, 1)
            p.drawRoundedRect(r, 14 + pad, 14 + pad)
        p.setPen(QPen(QColor("#c6ccd6"), 1))
        p.setBrush(QColor("#fdfdfd"))
        p.drawRoundedRect(shell, 14, 14)


def rule():
    line = QFrame()
    line.setObjectName("rule")
    line.setFixedHeight(1)
    return line


def button(text, slot=None):
    item = QPushButton(text)
    item.setCursor(Qt.PointingHandCursor)
    if slot:
        item.clicked.connect(slot)
    return item


def tool_button(name, label, slot):
    b = button("", slot)
    b.setObjectName("tool")
    b.setIcon(glyph(name))
    b.setIconSize(QSize(19, 19))
    b.setFixedSize(28, 28)
    b.setToolTip(label)
    b.setAccessibleName(label)
    return b


def text_label(text, name):
    label = QLabel(text)
    label.setObjectName(name)
    label.setTextFormat(Qt.PlainText)
    return label


def prepare_text(widget):
    widget.setFrameShape(QFrame.NoFrame)
    widget.document().setDocumentMargin(0)
    widget.setAcceptRichText(False)
    widget.setTabChangesFocus(True)
    palette = widget.palette()
    palette.setColor(QPalette.PlaceholderText, QColor("#757f8e"))
    widget.setPalette(palette)


class Editor(QTextEdit):
    issue_click = Signal(object, QPoint)

    def __init__(self):
        super().__init__()
        prepare_text(self)
        self.issues = []
        self.ranges = []
        self.typing_letter = False
        self.setMouseTracking(True)
        self.setPlaceholderText("Write or paste your text…")
        self.setAccessibleName("Original draft")

    def keyPressEvent(self, event):
        self.typing_letter = event.text().isalpha() or event.key() in (Qt.Key_Backspace, Qt.Key_Delete)
        try:
            super().keyPressEvent(event)
        finally:
            self.typing_letter = False

    def mark(self, issues):
        if self.issues == issues:
            # Qt moves selections along with edits. The common case is typing
            # after all the underlines, when the existing marks still fit.
            current = self.extraSelections()
            if len(current) == len(self.ranges) and all(
                    mark.cursor.selectionStart() == start and mark.cursor.selectionEnd() == end
                    for mark, (start, end, _) in zip(current, self.ranges)):
                return
        self.issues = issues
        value = self.toPlainText()
        selections = []
        self.ranges = []
        fmt = QTextCharFormat()
        fmt.setUnderlineColor(QColor("#bd394a"))
        fmt.setUnderlineStyle(QTextCharFormat.WaveUnderline)
        previous = qt_end = 0
        for issue in issues:
            sel = QTextEdit.ExtraSelection()
            cursor = self.textCursor()
            qt_start = qt_end + utf16(value[previous:issue.start])
            qt_end = qt_start + utf16(value[issue.start:issue.end])
            previous = issue.end
            cursor.setPosition(qt_start)
            cursor.setPosition(qt_end, QTextCursor.KeepAnchor)
            sel.cursor = cursor
            self.ranges.append((qt_start, qt_end, issue))
            sel.format = fmt
            selections.append(sel)
        self.setExtraSelections(selections)

    def issue_at(self, pos):
        # A click in the right half of the last letter still belongs to the word.
        # ExactHit also keeps clicks in the blank margin from opening a suggestion.
        point = QPointF(pos.x() + self.horizontalScrollBar().value(),
                        pos.y() + self.verticalScrollBar().value())
        ix = self.document().documentLayout().hitTest(point, Qt.ExactHit)
        for start, end, issue in self.ranges:
            if start <= ix < end:
                return issue
        return None

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        on_issue = self.ranges and self.issue_at(event.position().toPoint())
        self.viewport().setCursor(Qt.PointingHandCursor if on_issue and not event.buttons() else Qt.IBeamCursor)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() == Qt.LeftButton and not self.textCursor().hasSelection():
            issue = self.issue_at(event.position().toPoint())
            if issue:
                self.issue_click.emit(issue, event.globalPosition().toPoint())


def utf16(text):
    return len(text.encode("utf-16-le")) // 2


def copy_button(editor, accessible_name):
    b = button("Copy")
    b.setAccessibleName(accessible_name)
    b.setMinimumWidth(78)  # Keep adjacent actions still while showing “Copied”.
    b.setToolTip(accessible_name)
    b.setIcon(glyph("copy"))
    b.setIconSize(QSize(15, 15))

    def update():
        b.setEnabled(bool(editor.toPlainText()))
        b.setText("Copy")

    def copy():
        QApplication.clipboard().setText(editor.toPlainText())
        b.setText("Copied")
        QTimer.singleShot(1100, b, update)

    b.clicked.connect(copy)
    editor.textChanged.connect(update)
    update()
    return b


class Panel(Paper):
    closing = Signal()
    action_requested = Signal()
    review_requested = Signal()

    def __init__(self):
        super().__init__(TOP)
        self.setWindowTitle("Folio Editor")
        self.box.setContentsMargins(25, 13, 25, 20)

        self.editor = Editor()
        self.editor.setMinimumHeight(52)
        header = QHBoxLayout()
        header.setSpacing(8)
        header.addWidget(text_label("Draft", "sectionLabel"))
        self.count = text_label("0 words", "count")
        self.count.hide()
        header.addWidget(self.count)
        header.addStretch()
        self.dismiss = tool_button("close", "Hide editor (Esc)", self.closing.emit)
        header.addWidget(self.dismiss)
        self.editor.textChanged.connect(self.count_words)
        self.box.addLayout(header)
        self.box.addSpacing(5)
        self.box.addWidget(self.editor, 3)

        self.actions = QGridLayout()
        self.actions.setContentsMargins(0, 0, 0, 0)
        self.actions.setHorizontalSpacing(4)
        self.actions.setVerticalSpacing(0)
        self.actions.setColumnStretch(0, 1)
        self.context_action = button("", self.action_requested.emit)
        self.context_action.setObjectName("context")
        self.context_action.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.actions.addWidget(self.context_action, 1, 0, Qt.AlignLeft)
        self.context_action.hide()
        self.status = text_label("", "caption")
        self.status.setWordWrap(True)
        self.status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.status.setAccessibleName("Proofreading status")
        self.actions.addWidget(self.status, 1, 0)
        self.status.hide()
        self.original_copy = copy_button(self.editor, "Copy draft")
        self.actions.addWidget(self.original_copy, 1, 1)
        self.rewrite = button("Rewrite")
        self.rewrite.setObjectName("action")
        self.rewrite.setEnabled(False)
        self.rewrite.setToolTip("Rewrite (⌘ Return)" if sys.platform == "darwin" else "Rewrite (Ctrl+Enter)")
        for key in ("Ctrl+Return", "Ctrl+Enter"):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(self.rewrite.click)
        self.actions.addWidget(self.rewrite, 1, 2)
        review_key = QShortcut(QKeySequence("F7"), self)
        review_key.activated.connect(self.review_requested.emit)
        self.box.addSpacing(8)
        self.box.addLayout(self.actions)

        self.result_group = QWidget()
        result_box = QVBoxLayout(self.result_group)
        result_box.setContentsMargins(0, 13, 0, 0)
        result_box.setSpacing(0)
        result_box.addWidget(rule())
        result_box.addSpacing(8)
        self.result = QTextEdit()
        prepare_text(self.result)
        self.result.setReadOnly(True)
        self.result.setAccessibleName("Rewritten draft")
        self.result.setPlaceholderText("Rewriting…")
        self.result.setMinimumHeight(56)
        row = QHBoxLayout()
        row.addWidget(text_label("Revision", "sectionLabel"))
        row.addStretch()
        self.result_copy = copy_button(self.result, "Copy revision")
        row.addWidget(self.result_copy)
        result_box.addLayout(row)
        result_box.addSpacing(3)
        result_box.addWidget(self.result, 1)
        # The lower group also contains its label and copy control. Give both
        # text viewports comparable space when the result is visible.
        self.box.addWidget(self.result_group, 4)
        self.result_group.hide()
        self.result.textChanged.connect(self.mark_revision)
        self.result.setToolTip("New and changed words are highlighted.")
        self.setTabOrder(self.editor, self.context_action)
        self.setTabOrder(self.context_action, self.original_copy)
        self.setTabOrder(self.original_copy, self.rewrite)
        self.setTabOrder(self.rewrite, self.result)
        self.setTabOrder(self.result, self.result_copy)
        self.setTabOrder(self.result_copy, self.dismiss)

    def set_context_action(self, text):
        # Put long explanations on their own line; keep the common case compact.
        self.context_action.setText(text or "")
        self.context_action.setToolTip("Review suggestions (F7)" if text and "suggestion" in text else "")
        self.context_action.setVisible(bool(text))
        self.actions.removeWidget(self.status)
        if text:
            self.actions.addWidget(self.status, 0, 0, 1, 3)
        else:
            self.actions.addWidget(self.status, 1, 0)
        self.status.setVisible(bool(self.status.text()))

    def count_words(self):
        total = len(WORDS.findall(self.editor.toPlainText()))
        self.count.setText(f"{total:,} word" if total == 1 else f"{total:,} words")
        self.count.setVisible(total > 0)

    def mark_revision(self):
        text = self.result.toPlainText()
        selections = []
        if text:
            original = self.editor.toPlainText()
            parts = r"\w+(?:[’'-]\w+)*|[^\w\s]"
            before = re.findall(parts, original)
            spans = list(re.finditer(parts, text))
            after = [m.group() for m in spans]
            # The comparison is a reading aid. Bound its cost on long pastes.
            if max(len(before), len(after)) <= 1600:
                changes = SequenceMatcher(None, before, after).get_opcodes()
                for tag, _, _, first, last in changes:
                    if tag not in ("insert", "replace"):
                        continue
                    cursor = self.result.textCursor()
                    cursor.setPosition(utf16(text[:spans[first].start()]))
                    cursor.setPosition(utf16(text[:spans[last - 1].end()]), QTextCursor.KeepAnchor)
                    mark = QTextEdit.ExtraSelection()
                    mark.cursor = cursor
                    mark.format.setBackground(QColor("#e3ecfa"))
                    mark.format.setForeground(QColor("#263e66"))
                    selections.append(mark)
        self.result.setExtraSelections(selections)

    def sizeHint(self):
        return QSize(448, 218 if self.result_group.isHidden() else 382)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.closing.emit()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        event.ignore()
        self.closing.emit()


class Suggestion(Paper):
    chosen = Signal(str)
    dismissed = Signal()

    def __init__(self, issue, parent=None):
        super().__init__(Qt.Popup | Qt.FramelessWindowHint, parent)
        self.setWindowTitle("Spelling and grammar suggestions")
        self.choices = []
        self.return_to_editor = False
        self.box.setContentsMargins(21, 13, 21, 18)
        self.box.setSpacing(5)
        self.setMaximumWidth(340)
        top = QHBoxLayout()
        label = text_label(issue.original, "word")
        label.setWordWrap(True)
        top.addWidget(label, 1)
        top.addWidget(tool_button("close", "Dismiss suggestion", self.dismiss_to_editor))
        self.box.addLayout(top)
        if issue.explanation:
            why = text_label(issue.explanation, "caption")
            why.setWordWrap(True)
            self.box.addWidget(why)
        for word in issue.suggestions:
            b = button(word.replace("&", "&&") or "Delete")
            b.setObjectName("candidate")
            b.clicked.connect(lambda checked=False, value=word: self.chosen.emit(value))
            b.setFocusPolicy(Qt.StrongFocus)
            b.setAccessibleName("Replace with " + word if word else "Delete this text")
            b.setToolTip(word or "Delete this text")
            self.box.addWidget(b)
            self.choices.append(b)
        for key, step in (("Down", 1), ("Up", -1)):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(lambda delta=step: self.move_choice(delta))
        for key in ("Return", "Enter"):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(self.accept_focused)
        escape = QShortcut(QKeySequence("Esc"), self)
        escape.activated.connect(self.dismiss_to_editor)

    def dismiss_to_editor(self):
        self.return_to_editor = True
        self.hide()

    def focus_choices(self):
        if self.choices:
            self.choices[0].setFocus(Qt.OtherFocusReason)

    def move_choice(self, delta):
        current = self.focusWidget()
        index = self.choices.index(current) if current in self.choices else -1
        if self.choices:
            self.choices[(index + delta) % len(self.choices)].setFocus(Qt.OtherFocusReason)

    def accept_focused(self):
        item = self.focusWidget()
        if isinstance(item, QPushButton):
            item.click()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.dismissed.emit()
