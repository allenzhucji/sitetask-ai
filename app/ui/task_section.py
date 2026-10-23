from __future__ import annotations

from datetime import date

from PySide6.QtCore import Signal
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from app.models.task import Task
from app.ui.task_item import TaskItem


class TaskSection(QWidget):
    move_requested = Signal(int, object, object, bool)

    def __init__(
        self,
        title: str,
        tasks: list[Task],
        today: date,
        *,
        due_date: date | None = None,
        no_due_target: bool = False,
        items_draggable: bool = False,
        accepts_drops: bool = False,
    ) -> None:
        super().__init__()
        self.title = title
        self.tasks = tasks
        self.today = today
        self.no_due_target = no_due_target
        self.due_date = (
            None
            if no_due_target
            else due_date if due_date is not None else (tasks[0].due_date if tasks else None)
        )
        self.items_draggable = items_draggable and bool(tasks)
        self.accepts_drops = accepts_drops and (
            self.no_due_target or self.due_date is not None
        )
        self.setObjectName("taskSection")
        self.setAcceptDrops(self.accepts_drops)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("sectionTitle")
        self.task_items = [
            TaskItem(task, today, draggable=self.items_draggable) for task in tasks
        ]
        self.drop_indicator = QFrame()
        self.drop_indicator.setObjectName("dropIndicator")
        self.drop_indicator.setFixedHeight(3)
        self.drop_indicator.hide()

        self.task_layout = QVBoxLayout(self)
        self.task_layout.setContentsMargins(8, 3, 8, 2)
        self.task_layout.setSpacing(3)
        self.task_layout.addWidget(self.title_label)
        for task_item in self.task_items:
            self.task_layout.addWidget(task_item)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        dragged_task_id = self._dragged_task_id(event)
        if self.accepts_drops and dragged_task_id is not None:
            self._set_drag_active(True)
            self._show_drop_indicator(dragged_task_id, event.position().y())
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        dragged_task_id = self._dragged_task_id(event)
        if self.accepts_drops and dragged_task_id is not None:
            self._show_drop_indicator(dragged_task_id, event.position().y())
            event.acceptProposedAction()
            return
        event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._clear_drop_indicator()
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:
        self._clear_drop_indicator()
        dragged_task_id = self._dragged_task_id(event)
        original_ids = self._task_ids()
        if (
            not self.accepts_drops
            or dragged_task_id is None
            or (self.due_date is None and not self.no_due_target)
        ):
            event.ignore()
            return

        ordered_ids = self.ordered_task_ids_for_drop(
            dragged_task_id,
            event.position().y(),
        )
        if ordered_ids == original_ids:
            event.acceptProposedAction()
            return
        make_first_urgent = (
            not self.no_due_target
            and self.due_date == self.today
            and ordered_ids[0] == dragged_task_id
        )
        self.move_requested.emit(
            dragged_task_id,
            self.due_date,
            ordered_ids,
            make_first_urgent,
        )
        event.acceptProposedAction()

    def ordered_task_ids_for_drop(
        self,
        dragged_task_id: int,
        drop_y: float,
    ) -> list[int]:
        """Return the same-date order represented by a vertical drop position."""
        original_ids = self._task_ids()
        remaining_items = [
            item for item in self.task_items if item.task.id != dragged_task_id
        ]
        insertion_index = sum(
            drop_y >= item.geometry().center().y() for item in remaining_items
        )
        ordered_ids = [
            task_id for task_id in original_ids if task_id != dragged_task_id
        ]
        ordered_ids.insert(insertion_index, dragged_task_id)
        return ordered_ids

    def set_empty_drop_target_visible(self, visible: bool) -> None:
        if self.task_items:
            return
        self.setVisible(visible and self.accepts_drops)

    def _show_drop_indicator(self, dragged_task_id: int, drop_y: float) -> None:
        ordered_ids = self.ordered_task_ids_for_drop(dragged_task_id, drop_y)
        insertion_index = ordered_ids.index(dragged_task_id)
        self.task_layout.removeWidget(self.drop_indicator)
        self.task_layout.insertWidget(1 + insertion_index, self.drop_indicator)
        self.drop_indicator.show()

    def _clear_drop_indicator(self) -> None:
        self.drop_indicator.hide()
        self._set_drag_active(False)

    def _task_ids(self) -> list[int]:
        return [item.task.id for item in self.task_items if item.task.id is not None]

    @staticmethod
    def _dragged_task_id(
        event: QDragEnterEvent | QDragMoveEvent | QDropEvent,
    ) -> int | None:
        mime_data = event.mimeData()
        if not mime_data.hasFormat(TaskItem.TASK_ID_MIME_TYPE):
            return None
        try:
            encoded_task_id = bytes(mime_data.data(TaskItem.TASK_ID_MIME_TYPE))
            return int(encoded_task_id.decode("ascii"))
        except (TypeError, ValueError, UnicodeDecodeError):
            return None

    def _set_drag_active(self, active: bool) -> None:
        self.setProperty("dragActive", active)
        self.style().unpolish(self)
        self.style().polish(self)
