from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QMimeData, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QContextMenuEvent, QDrag, QMouseEvent, QResizeEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSizePolicy,
)
from qfluentwidgets import CardWidget

from app.models.task import Task
from app.ui.task_tooltip import DescriptionHover, description_tooltip


class FullTextLabel(QLabel):
    """完整显示的长文本标题。

    wordWrap 的 QLabel 把 minimumSizeHint 报告为完整文本单行宽，布局
    会按它分配宽度：任务卡片宽固定时 QLabel 被分到完整文本宽（溢出
    卡片、wordWrap 不换行）。重写 minimumSizeHint 为 (0, 行高) 后布局
    只给可用宽，文本在可用宽内换行完整显示。"""

    def minimumSizeHint(self) -> QSize:
        height = super().minimumSizeHint().height()
        return QSize(0, height)


class TaskItem(CardWidget):
    """任务卡片：CardWidget 现成圆角卡片（hover 高亮），只显示
    完成勾选、标题（可换行完整显示）、截止时间与紧急程度徽章。"""

    COMPACT_HEIGHT = 44
    NO_DUE_HEIGHT = 34
    TASK_ID_MIME_TYPE = "application/x-sitetask-task-id"

    complete_requested = Signal(int)
    edit_requested = Signal(int)
    change_due_date_requested = Signal(int)
    duplicate_requested = Signal(int)
    delete_requested = Signal(int)
    drag_started = Signal()
    drag_finished = Signal()

    def __init__(self, task: Task, today: date, *, draggable: bool = False) -> None:
        super().__init__()
        self.task = task
        self.is_no_due = task.no_due or (
            task.status.value == "pending" and task.due_date < today
        )
        self.draggable = draggable and task.id is not None
        self._drag_start_position: QPoint | None = None
        self.setObjectName("taskItem")
        self.setMinimumHeight(
            self.NO_DUE_HEIGHT if self.is_no_due else self.COMPACT_HEIGHT
        )

        self.complete_checkbox = QCheckBox()
        self.complete_checkbox.setObjectName("taskCompleteCheckbox")
        self.complete_checkbox.setToolTip("Mark completed")
        # 不设任何拖拽手掌光标：卡片整块可拖拽（用户要求指针保持默认），
        # 勾选框显式箭头以隔离未来可能的祖先光标设置
        self.complete_checkbox.setCursor(Qt.CursorShape.ArrowCursor)
        self.complete_checkbox.toggled.connect(self._on_completion_toggled)

        # 标题不省略：窗口宽度随最长标题自适应（MainWidget._fit_width_to_titles）；
        # FullTextLabel 重写 minimumSizeHint（0, 行高）避免完整文本宽撑爆容器，
        # 超长标题在可用宽内换行完整显示
        self.title_label = FullTextLabel(task.title)
        self.title_label.setObjectName("taskTitle")
        self.title_label.setWordWrap(True)
        self.title_label.setMinimumWidth(0)
        self.title_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )

        self.metadata_label = QLabel(self._metadata_text(task, today))
        self.metadata_label.setObjectName("taskMetadata")

        # 紧急度不显示文字徽章，右侧小圆点表示（level 属性驱动 QSS 配色）
        self.priority_dot = QLabel()
        self.priority_dot.setObjectName("taskPriorityDot")
        self.priority_dot.setFixedSize(8, 8)
        self.priority_dot.setProperty("level", str(task.priority))
        tooltip = description_tooltip(task.description)
        for target in (self, self.title_label, self.metadata_label, self.priority_dot):
            target.setToolTip(tooltip)
        self.description_hover = DescriptionHover(
            self, (self, self.title_label, self.metadata_label, self.priority_dot),
            lambda _target, _event: (self.task, QRect(self.mapToGlobal(QPoint()), self.size())),
        )
        if self.is_no_due:
            # NO DUE is a dense long-term list: the group heading already conveys
            # the date state, and urgency is intentionally not shown here.
            self.metadata_label.hide()
            self.priority_dot.hide()

        info_layout = QHBoxLayout()
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(8)
        info_layout.addWidget(self.metadata_label)
        info_layout.addWidget(self.priority_dot)

        layout = QHBoxLayout(self)
        vertical_margin = 2 if self.is_no_due else 3
        layout.setContentsMargins(10, vertical_margin, 10, vertical_margin)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        # 多行文本时勾选框垂直居中（与卡片内容整体对齐，而非贴顶部）
        layout.addWidget(self.complete_checkbox, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.title_label, 1)
        layout.addLayout(info_layout, 0)

    def sizeHint(self) -> QSize:
        """卡片高度随标题换行自适应。

        QBoxLayout 的 heightForWidth 链在计算最小高度时按子项
        sizeHint 宽度（内容完整宽）传入，换行高度进不了布局；因此
        直接让 sizeHint 高度 = 当前实际宽度下的换行高度，宽度变化时
        （resizeEvent）updateGeometry 触发布局重算。"""
        base = super().sizeHint()
        return QSize(base.width(), max(base.height(), self._wrapped_height()))

    def minimumSizeHint(self) -> QSize:
        # 宽度归零：卡片内 metadata/徽章的 minimum（文本宽 ~302px）加上
        # section/容器边距会超过滚动条出现后的窄 viewport，水平撑爆容器。
        # 标题可换行压缩；正常宽度下 metadata/徽章仍按 sizeHint 完整分配。
        base = super().minimumSizeHint()
        return QSize(0, base.height())

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self.width() != event.oldSize().width():
            # 宽度变化 -> 标题换行数变化 -> 高度需求变化。
            # 不能只 updateGeometry：QScrollArea 只在自身 resizeEvent 时
            # 重算 widget 高度，重算出的新高度不会应用；直接固定自身
            # 高度（布局尊重 setFixedHeight），标题 label 撑满剩余高度，
            # 否则 QHBoxLayout 按缓存 sizeHint（单行/旧换行数）给高度，
            # 换行后的文本被垂直裁剪。
            minimum_height = (
                self.NO_DUE_HEIGHT if self.is_no_due else self.COMPACT_HEIGHT
            )
            wrapped = max(minimum_height, self._wrapped_height())
            self.setFixedHeight(wrapped)
            margins = self.layout().contentsMargins()
            self.title_label.setFixedHeight(
                wrapped - margins.top() - margins.bottom()
            )

    def _wrapped_height(self) -> int:
        """给定卡片当前宽度，标题换行完整显示所需的卡片总高。

        不能用 title_label.heightForWidth：label 被 setFixedHeight 固定后，
        Qt 的 heightForWidth 返回当前固定高度（不再按宽度重算换行高度），
        宽度每次变化卡片高度就 +2 滚雪球增大。这里用与 QLabel 内部一致
        的 fontMetrics.boundingRect 独立计算，不读取 label 状态。"""
        layout = self.layout()
        margins = layout.contentsMargins()
        spacing = layout.spacing()
        fixed_width = (
            self.complete_checkbox.minimumSizeHint().width()
            + margins.left()
            + margins.right()
            + spacing
        )
        if not self.is_no_due:
            fixed_width += (
                self.metadata_label.minimumSizeHint().width()
                + self.priority_dot.width()
                + spacing * 2
            )
        label_width = max(0, self.width() - fixed_width)
        fm = self.title_label.fontMetrics()
        label_height = fm.boundingRect(
            QRect(0, 0, label_width, 10_000),
            int(Qt.TextFlag.TextWordWrap),
            self.title_label.text(),
        ).height()
        # +2：CardWidget 自带 1px 上下边框
        return label_height + margins.top() + margins.bottom() + 2

    def mark_completed(self) -> None:
        self.complete_checkbox.blockSignals(True)
        self.complete_checkbox.setChecked(True)
        self.complete_checkbox.setEnabled(False)
        self.complete_checkbox.blockSignals(False)
        title_font = self.title_label.font()
        title_font.setStrikeOut(True)
        self.title_label.setFont(title_font)

    def build_context_menu(self) -> QMenu:
        menu = QMenu(self)
        actions = (
            ("Edit", self.edit_requested),
            ("Mark Completed", self.complete_requested),
            ("Change Due Date", self.change_due_date_requested),
            ("Duplicate", self.duplicate_requested),
            ("Delete", self.delete_requested),
        )
        for label, signal in actions:
            action = menu.addAction(label)
            action.triggered.connect(lambda checked=False, target=signal: self._emit(target))
        return menu

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        self.build_context_menu().exec(event.globalPos())

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._emit(self.edit_requested)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self.draggable and event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_position = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            not self.draggable
            or self._drag_start_position is None
            or not event.buttons() & Qt.MouseButton.LeftButton
        ):
            super().mouseMoveEvent(event)
            return
        distance = (
            event.position().toPoint() - self._drag_start_position
        ).manhattanLength()
        if distance < QApplication.startDragDistance():
            super().mouseMoveEvent(event)
            return

        task_id = self.task.id
        if task_id is None:
            return
        mime_data = QMimeData()
        mime_data.setData(self.TASK_ID_MIME_TYPE, str(task_id).encode("ascii"))
        drag = QDrag(self)
        drag.setMimeData(mime_data)
        drag.setPixmap(self.grab())
        drag.setHotSpot(self._drag_start_position)
        self.drag_started.emit()
        drag.exec(Qt.DropAction.MoveAction)
        self.drag_finished.emit()
        self._drag_start_position = None

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_start_position = None
        super().mouseReleaseEvent(event)

    def _on_completion_toggled(self, checked: bool) -> None:
        if checked:
            self._emit(self.complete_requested)

    def _emit(self, signal: Signal) -> None:
        if self.task.id is not None:
            signal.emit(self.task.id)

    @staticmethod
    def _metadata_text(task: Task, today: date) -> str:
        if task.no_due or (
            task.status.value == "pending" and task.due_date < today
        ):
            return "No due"
        if task.due_date == today:
            date_text = "Today"
        elif task.due_date == today + timedelta(days=1):
            date_text = "Tomorrow"
        else:
            date_text = f"{task.due_date.day} {task.due_date.strftime('%b')}"

        time_text = task.due_time.strftime("%H:%M") if task.due_time else "All day"
        return f"{date_text} · {time_text}"
