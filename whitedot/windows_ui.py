"""Small native floating surfaces shared by macOS and Windows."""
import math
import sys

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel,
                               QPushButton, QTextEdit, QVBoxLayout, QWidget)


TOP = Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
NO_FOCUS = TOP | Qt.WindowDoesNotAcceptFocus
STYLE = """
QWidget {color:#26332f; font-size:13px;}
QFrame#paper, QDialog {background:#f8faf9; border:1px solid #cbd3ce; border-radius:12px;}
QLabel#heading {font-size:16px; font-weight:650;}
QLabel#caption {color:#455e54; font-size:12px;}
QTextEdit, QLineEdit, QComboBox {background:white; color:#18261f; border:1px solid #bccbc2;
 border-radius:6px; padding:6px; selection-background-color:#bddbd0;}
QPushButton {background:white; border:1px solid #bdc9c1; border-radius:6px; padding:5px 10px;}
QPushButton:hover {background:#e6eee9;}
QPushButton:disabled {color:#8a948e; background:#edf0ee; border-color:#d7ded9;}
QPushButton#action {background:#245d4d; color:white; border-color:#245d4d;}
QPushButton#action:disabled {background:#e4eae6; color:#89978f; border-color:#d7ded9;}
"""


def native_float(widget):
    """Show Qt tool windows in full-screen Spaces and without hiding on deactivation."""
    widget.setAttribute(Qt.WA_MacAlwaysShowToolWindow, True)
    if widget.windowFlags() & Qt.WindowDoesNotAcceptFocus:
        widget.setAttribute(Qt.WA_ShowWithoutActivating)
    if sys.platform == "darwin" and QApplication.platformName() == "cocoa":
        import objc
        from AppKit import (NSWindowCollectionBehaviorCanJoinAllSpaces,
                            NSWindowCollectionBehaviorFullScreenAuxiliary, NSStatusWindowLevel,
                            NSWindowStyleMaskNonactivatingPanel)
        from .platforms.cocoa_panel import panel_creation
        with panel_creation(bool(widget.windowFlags() & Qt.WindowDoesNotAcceptFocus)):
            view = objc.objc_object(c_void_p=int(widget.winId()))
        window = view.window()
        if window:
            if widget.windowFlags() & Qt.WindowDoesNotAcceptFocus:
                window.setStyleMask_(window.styleMask() | NSWindowStyleMaskNonactivatingPanel)
                window.setBecomesKeyOnlyIfNeeded_(True)
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
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / 56, size / 56)
    shadow = QRadialGradient(QPointF(28, 30), 26)
    shadow.setColorAt(.52, QColor(26, 36, 32, 94))
    shadow.setColorAt(.78, QColor(26, 36, 32, 44))
    shadow.setColorAt(1, QColor(26, 36, 32, 0))
    p.setPen(Qt.NoPen)
    p.setBrush(shadow)
    p.drawEllipse(QRectF(2, 4, 52, 52))
    p.setPen(QPen(QColor("#82918a" if tray else "#b7c1bb"), 1))
    p.setBrush(QColor("#f5f7f5"))
    p.drawEllipse(QRectF(8, 7, 40, 40))
    p.setPen(QPen(QColor("#ccd3cf"), 1.15))
    p.setBrush(Qt.white)
    p.drawEllipse(QRectF(14, 13, 28, 28))


def icon():
    pix = QPixmap(112, 112)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    dot_art(painter, 112, True)
    painter.end()
    return QIcon(pix)


def clamped(pos, size, screen):
    r = screen.availableGeometry()
    return QPoint(max(r.left(), min(pos.x(), r.right() - size.width() + 1)),
                  max(r.top(), min(pos.y(), r.bottom() - size.height() + 1)))


class Dot(QWidget):
    clicked = Signal()
    moved = Signal()
    menu_at = Signal(QPoint)

    def __init__(self):
        super().__init__(None, NO_FOCUS)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(56, 56)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("WhiteDot · 点按打开，拖动移位")
        self.setAccessibleName("WhiteDot 拼写助手")
        self.origin = None
        self.dragging = False
        native_float(self)

    def paintEvent(self, event):
        p = QPainter(self)
        dot_art(p, 56)

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
    def __init__(self, flags):
        super().__init__(None, flags)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(STYLE)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, 1, 1, 1)
        frame = QFrame()
        frame.setObjectName("paper")
        outer.addWidget(frame)
        self.box = QVBoxLayout(frame)
        self.box.setContentsMargins(15, 12, 15, 12)
        self.box.setSpacing(9)
        native_float(self)


class Editor(QTextEdit):
    issue_click = Signal(object, QPoint)

    def __init__(self):
        super().__init__()
        self.issues = []
        self.setAcceptRichText(False)
        self.setPlaceholderText("在这里输入或粘贴英文…")
        self.setAccessibleName("英文原文")

    def mark(self, issues):
        self.issues = issues
        value = self.toPlainText()
        selections = []
        for issue in issues:
            sel = QTextEdit.ExtraSelection()
            cursor = self.textCursor()
            cursor.setPosition(utf16(value[:issue.start]))
            cursor.setPosition(utf16(value[:issue.end]), QTextCursor.KeepAnchor)
            sel.cursor = cursor
            fmt = QTextCharFormat()
            fmt.setUnderlineColor(QColor("#c23543"))
            fmt.setUnderlineStyle(QTextCharFormat.WaveUnderline)
            sel.format = fmt
            selections.append(sel)
        self.setExtraSelections(selections)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() != Qt.LeftButton or self.textCursor().hasSelection():
            return
        ix = self.cursorForPosition(event.position().toPoint()).position()
        value = self.toPlainText()
        for issue in self.issues:
            if utf16(value[:issue.start]) <= ix < utf16(value[:issue.end]):
                self.issue_click.emit(issue, event.globalPosition().toPoint())
                return


def utf16(s):
    return len(s.encode("utf-16-le")) // 2


def button(text, slot=None):
    item = QPushButton(text)
    item.setCursor(Qt.PointingHandCursor)
    if slot:
        item.clicked.connect(slot)
    return item


def copy_button(editor):
    b = button("复制")
    def update():
        b.setEnabled(bool(editor.toPlainText()))
        b.setText("复制")
    def copy():
        QApplication.clipboard().setText(editor.toPlainText())
        b.setText("已复制")
        QTimer.singleShot(1000, b, update)
    b.clicked.connect(copy)
    editor.textChanged.connect(update)
    update()
    return b


class Panel(Paper):
    closing = Signal()

    def __init__(self, external=False):
        super().__init__(NO_FOCUS if external else TOP)
        self.external = external
        self.setWindowTitle("WhiteDot")
        top = QHBoxLayout()
        self.title = QLabel("语法重写" if external else "英文校对")
        self.title.setObjectName("heading")
        top.addWidget(self.title)
        top.addStretch()
        self.rewrite = button("语法重写")
        self.rewrite.setObjectName("action")
        top.addWidget(self.rewrite)
        self.dismiss = button("×", self.closing.emit)
        self.dismiss.setAccessibleName("收起")
        self.dismiss.setFixedWidth(32)
        top.addWidget(self.dismiss)
        self.box.addLayout(top)
        self.editor = Editor()
        self.editor.setMinimumHeight(86)
        self.editor.setReadOnly(external)
        self.box.addWidget(self.editor, 1)
        row = QHBoxLayout()
        self.status = QLabel()
        self.status.setObjectName("caption")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.PlainText)
        row.addWidget(self.status, 1)
        self.original_copy = copy_button(self.editor)
        row.addWidget(self.original_copy)
        self.box.addLayout(row)
        self.result_group = QWidget()
        result_layout = QVBoxLayout(self.result_group)
        result_layout.setContentsMargins(0, 5, 0, 0)
        row = QHBoxLayout()
        result_label = QLabel("重写结果")
        result_label.setObjectName("heading")
        row.addWidget(result_label)
        row.addStretch()
        self.result = QTextEdit()
        self.result.setAccessibleName("重写结果")
        self.result.setReadOnly(True)
        self.result.setPlaceholderText("等待重写…")
        self.result.setMinimumHeight(80)
        self.result_copy = copy_button(self.result)
        row.addWidget(self.result_copy)
        result_layout.addLayout(row)
        result_layout.addWidget(self.result)
        self.box.addWidget(self.result_group, 1)
        self.result_group.setVisible(external)
        self.rewrite.setEnabled(False)
        if external:
            self.rewrite.setText("重新生成")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.closing.emit()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        event.ignore()
        self.closing.emit()


class Mark(QWidget):
    """Only the narrow strip directly under a flagged word intercepts a click."""
    clicked = Signal(object, QPoint)
    def __init__(self):
        super().__init__(None, NO_FOCUS)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.PointingHandCursor)
        self.issue = None
        native_float(self)

    def display(self, rect, issue):
        self.issue = issue
        self.setGeometry(round(rect.x), math.ceil(rect.y + rect.h) - 4,
                         max(3, round(rect.w)), 5)
        self.show()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(255, 255, 255, 2))
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor("#d73645"), 1.6))
        path = QPainterPath()
        path.moveTo(0, 2.6)
        for x in range(0, self.width(), 4):
            path.quadTo(x + 1, .7, x + 2, 2.6)
            path.quadTo(x + 3, 4.5, x + 4, 2.6)
        p.drawPath(path)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.issue:
            self.clicked.emit(self.issue, event.globalPosition().toPoint())


class Suggestion(Paper):
    chosen = Signal(str)
    def __init__(self, issue):
        super().__init__(NO_FOCUS)
        self.setMaximumWidth(360)
        top = QHBoxLayout()
        label = QLabel(issue.original)
        label.setTextFormat(Qt.PlainText)
        label.setWordWrap(True)
        label.setObjectName("heading")
        top.addWidget(label, 1)
        top.addWidget(button("×", self.hide))
        self.box.addLayout(top)
        why = QLabel(issue.explanation)
        why.setTextFormat(Qt.PlainText)
        why.setWordWrap(True)
        self.box.addWidget(why)
        for word in issue.suggestions:
            b = button(word.replace("&", "&&") or "删除")
            b.clicked.connect(lambda checked=False, value=word: self.chosen.emit(value))
            self.box.addWidget(b)
