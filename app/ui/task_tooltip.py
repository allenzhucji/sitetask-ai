from __future__ import annotations

from html import escape
import re
from urllib.parse import urlsplit
from time import monotonic

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QKeySequence, QPainter, QPen, QShortcut, QTextCursor, QTextDocument, QTextOption
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout

from app.models.task import Task


def description_parts(description: str) -> tuple[str, list[str]]:
    """Keep source URLs available without filling the reading area with them."""
    marker = "\n来源邮件：\n"
    if marker not in description:
        return description, []
    body, tail = description.rsplit(marker, 1)
    urls = [line.strip() for line in tail.splitlines() if line.strip()]
    try:
        valid = bool(urls) and all(urlsplit(url).scheme == "https" and urlsplit(url).hostname for url in urls)
    except ValueError:
        valid = False
    if not valid:
        return description, []
    return body.rstrip(), urls


def description_tooltip(description: str | None) -> str:
    """Readable, escaped description with explicit line and long-token wrapping."""
    if not description or not description.strip():
        return ""
    text = description.strip().replace("\r\n", "\n").replace("\r", "\n")
    # Qt rich-text tooltips otherwise grow beyond the screen for a long URL.
    # Invisible break opportunities preserve every visible character.
    text = re.sub(
        r"\S{25,}",
        lambda match: "\u200b".join(
            match[0][start : start + 24] for start in range(0, len(match[0]), 24)
        ),
        text,
    )
    body = escape(text).replace("\n", "<br>")
    return f'<qt><table width="440"><tr><td>{body}</td></tr></table></qt>'


class SelectableDescriptionEdit(QPlainTextEdit):
    """Standard press-drag selection plus stationary left-button long press."""

    def __init__(self):
        super().__init__()
        self._press_position = None
        self._press_anchor = 0
        self._drag_selecting = False
        self.long_press_timer = QTimer(self)
        self.long_press_timer.setSingleShot(True)
        self.long_press_timer.setInterval(450)
        self.long_press_timer.timeout.connect(self._select_pressed_word)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_position = event.position().toPoint()
            self._press_anchor = self.cursorForPosition(self._press_position).position()
            self._drag_selecting = False
            self.long_press_timer.start()

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        if self._press_position is not None:
            distance = (event.position().toPoint() - self._press_position).manhattanLength()
            if distance >= QApplication.startDragDistance():
                self.long_press_timer.stop()
                if event.buttons() & Qt.MouseButton.LeftButton:
                    cursor = self.textCursor()
                    cursor.setPosition(self._press_anchor)
                    cursor.setPosition(self.cursorForPosition(event.position().toPoint()).position(), QTextCursor.MoveMode.KeepAnchor)
                    self.setTextCursor(cursor)
                    self._drag_selecting = True

    def mouseReleaseEvent(self, event):
        self.long_press_timer.stop()
        self._press_position = None
        selection = self.textCursor()
        super().mouseReleaseEvent(event)
        if self._drag_selecting:
            self.setTextCursor(selection)
        self._drag_selecting = False

    def _select_pressed_word(self):
        if self._press_position is not None:
            cursor = self.cursorForPosition(self._press_position)
            cursor.select(QTextCursor.SelectionType.WordUnderCursor)
            self.setTextCursor(cursor)
            self._press_anchor = cursor.selectionStart()

    def hideEvent(self, event):
        self.long_press_timer.stop()
        self._press_position = None
        super().hideEvent(event)


class DescriptionPopup(QFrame):
    """A non-modal hover surface that accepts selection, scrolling and copy."""

    LEAVE_DELAY = 0.7

    def __init__(self, parent):
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setObjectName("descriptionPopup")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.task_id = None
        self.anchor = QRect()
        self._outside_since = None
        self.full_description = ""

        eyebrow = QLabel("任务详情")
        eyebrow.setObjectName("descriptionEyebrow")
        copy_button = QPushButton("复制全部")
        copy_button.setObjectName("descriptionCopy")
        copy_button.setFixedHeight(30)
        copy_button.clicked.connect(lambda: QApplication.clipboard().setText(self.full_description))
        close_button = QPushButton("×")
        close_button.setObjectName("descriptionClose")
        close_button.setFixedSize(30, 30)
        close_button.setToolTip("关闭 · Esc")
        close_button.clicked.connect(self.hide)
        self.copy_button = copy_button
        self.close_button = close_button
        header = QHBoxLayout()
        header.setSpacing(8)
        header.addWidget(eyebrow)
        header.addStretch()
        header.addWidget(copy_button)
        header.addWidget(close_button)

        self.title_label = QLabel()
        self.title_label.setObjectName("descriptionTitle")
        self.title_label.setTextFormat(Qt.TextFormat.PlainText)
        self.title_label.setWordWrap(True)
        self.text_edit = SelectableDescriptionEdit()
        self.text_edit.setObjectName("descriptionText")
        self.text_edit.setReadOnly(True)
        self.text_edit.setFrameShape(QFrame.Shape.NoFrame)
        self.text_edit.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        self.text_edit.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.text_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.text_edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.source_label = QLabel()
        self.source_label.setObjectName("descriptionSources")
        self.source_label.setTextFormat(Qt.TextFormat.RichText)
        self.source_label.setOpenExternalLinks(True)
        self.source_label.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.source_label.hide()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 16, 22, 20)
        layout.setSpacing(10)
        layout.addLayout(header)
        layout.addWidget(self.title_label)
        layout.addWidget(self.text_edit, 1)
        layout.addWidget(self.source_label)
        self.setStyleSheet("""
            QFrame#descriptionPopup { background: transparent; border: none; }
            QLabel#descriptionEyebrow { color: #9aa9bc; font-size: 11px; background: transparent; }
            QLabel#descriptionTitle { color: #f4f7fc; font-size: 14px; font-weight: 600; background: transparent; }
            QPlainTextEdit#descriptionText { background: transparent; color: #dce3ef; border: none;
                font-size: 13px; selection-background-color: #355f87; selection-color: #ffffff; }
            QPushButton#descriptionCopy, QPushButton#descriptionClose { background: #343d4c;
                color: #bce7fa; border: 1px solid #455269; border-radius: 7px;
                min-height: 28px; max-height: 28px; padding: 0 10px; font-size: 11px; }
            QPushButton#descriptionClose { min-width: 28px; max-width: 28px; padding: 0; color: #b9c4d4; font-size: 18px; }
            QLabel#descriptionSources { color: #9aa9bc; font-size: 11px; background: transparent; padding-top: 2px; }
            QPushButton#descriptionCopy:hover, QPushButton#descriptionClose:hover { background: #43546a; color: white; }
            QScrollBar:vertical { width: 6px; background: transparent; margin: 0; }
            QScrollBar::handle:vertical { background: #5b6b81; border-radius: 3px; min-height: 24px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
        """)
        self.poll = QTimer(self)
        self.poll.setInterval(100)
        self.poll.timeout.connect(self._check_hover)
        self.escape_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self.escape_shortcut.activated.connect(self.hide)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        for inset, alpha in ((1, 12), (3, 18), (5, 28)):
            painter.setBrush(QColor(0, 0, 0, alpha))
            painter.drawRoundedRect(self.rect().adjusted(inset, inset, -inset, -inset), 17, 17)
        painter.setBrush(QColor(31, 37, 49, 248))
        painter.setPen(QPen(QColor(103, 125, 154, 140), 1))
        painter.drawRoundedRect(self.rect().adjusted(7, 7, -7, -7), 13, 13)

    def update_task(self, task: Task):
        description = task.description or ""
        if not description.strip():
            self.hide()
            return
        self.task_id = task.id
        self.title_label.setText(task.title)
        self.full_description = description
        body, urls = description_parts(description)
        links = " &nbsp; · &nbsp; ".join(
            f'<a href="{escape(url, quote=True)}" style="color:#9cd7ee;text-decoration:none;">'
            + ("查看原邮件 ↗" if len(urls) == 1 else f"原邮件 {index} ↗") + "</a>"
            for index, url in enumerate(urls, 1)
        )
        self.source_label.setText(links)
        self.source_label.setVisible(bool(urls))
        # A routine 60-second task refresh must not clear a user's selection.
        if self.text_edit.toPlainText() != body:
            self.text_edit.setPlainText(body)

    def show_task(self, task: Task, anchor: QRect):
        same_task = self.isVisible() and self.task_id == task.id
        self.update_task(task)
        self.anchor = QRect(anchor)
        self._outside_since = None
        if not same_task:
            screen = QApplication.screenAt(anchor.center()) or QApplication.primaryScreen()
            area = screen.availableGeometry()
            width = min(480, area.width() - 20)
            document = QTextDocument()
            document.setDefaultFont(self.text_edit.font())
            document.setPlainText(self.text_edit.toPlainText())
            document.setTextWidth(width - 54)
            height = min(max(180, int(document.size().height()) + 125 + (24 if not self.source_label.isHidden() else 0)), 480, area.height() - 24)
            self.resize(width, height)
            x = anchor.right() + 8
            if x + width > area.right():
                x = anchor.left() - width - 8
            x = max(area.left() + 10, min(x, area.right() - width - 10))
            y = max(area.top() + 10, min(anchor.top(), area.bottom() - height - 10))
            self.move(QPoint(x, y))
            self.show()
        self.poll.start()

    def _check_hover(self):
        point = QCursor.pos()
        menu = QApplication.activePopupWidget()
        inside = self.frameGeometry().contains(point) or self.anchor.contains(point)
        selecting = bool(QApplication.mouseButtons() & Qt.MouseButton.LeftButton) and self.text_edit.hasFocus()
        if inside or selecting or (menu is not None and self.isAncestorOf(menu)):
            self._outside_since = None
        elif self._outside_since is None:
            self._outside_since = monotonic()
        elif monotonic() - self._outside_since >= self.LEAVE_DELAY:
            self.hide()

    def hideEvent(self, event):
        self.poll.stop()
        super().hideEvent(event)


class DescriptionHover(QObject):
    def __init__(self, owner, targets, resolve):
        super().__init__(owner)
        self.owner = owner
        self.resolve = resolve
        for target in targets:
            target.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.ToolTip:
            result = self.resolve(watched, event)
            if result is not None:
                task, anchor = result
                if task.description and task.description.strip():
                    window = self.owner.window()
                    popup = getattr(window, "description_popup", None)
                    if popup is None:
                        popup = DescriptionPopup(window)
                        window.description_popup = popup
                    popup.show_task(task, anchor)
            return True  # Suppress the non-interactive native tooltip.
        return super().eventFilter(watched, event)


def refresh_description_popup(window, tasks):
    popup = getattr(window, "description_popup", None)
    if popup is None or not popup.isVisible():
        return
    task = next((item for item in tasks if item.id == popup.task_id), None)
    if task is None:
        popup.hide()
    else:
        popup.update_task(task)
