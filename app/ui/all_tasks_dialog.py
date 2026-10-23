from __future__ import annotations

from collections.abc import Callable
from datetime import date

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import ComboBox

from app.database.task_repository import TaskRepository
from app.models.task import Task
from app.ui.task_tooltip import DescriptionHover, description_tooltip, refresh_description_popup


class AllTasksDialog(QDialog):
    edit_requested = Signal(int)
    complete_requested = Signal(int)
    restore_requested = Signal(int)
    delete_requested = Signal(int)

    FILTERS = (
        "Upcoming",
        "Next 3 Days",
        "Later",
        "No Due",
        "Completed",
        "All",
    )
    HEADERS = ("Title", "Due Date", "Due Time", "Category", "Priority", "Status")

    def __init__(
        self,
        repository: TaskRepository,
        *,
        today_provider: Callable[[], date] = date.today,
        days_ahead: int = 3,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.repository = repository
        self.today_provider = today_provider
        self.days_ahead = days_ahead
        self.current_tasks: list[Task] = []

        self.setWindowTitle("All Tasks")
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips, True)
        self.resize(760, 520)
        self.setMinimumSize(620, 400)

        filter_label = QLabel("Filter")
        self.filter_combo = ComboBox()
        self.filter_combo.setObjectName("allTasksFilter")
        self.filter_combo.addItems(self.FILTERS)
        self.filter_combo.currentTextChanged.connect(self.refresh)

        self.search_input = QLineEdit()
        self.search_input.setObjectName("allTasksSearch")
        self.search_input.setPlaceholderText("Search tasks")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self.refresh)

        self.count_label = QLabel()
        self.count_label.setObjectName("allTasksCount")

        filter_layout = QHBoxLayout()
        filter_layout.addWidget(filter_label)
        filter_layout.addWidget(self.filter_combo)
        filter_layout.addWidget(self.search_input, 1)
        filter_layout.addStretch(1)
        filter_layout.addWidget(self.count_label)

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setObjectName("allTasksTable")
        self.description_hover = DescriptionHover(self, (self.table.viewport(),), self._hover_task)
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 250)
        self.table.setColumnWidth(1, 95)
        self.table.setColumnWidth(2, 75)
        self.table.setColumnWidth(3, 120)
        self.table.setColumnWidth(4, 75)
        self.table.itemSelectionChanged.connect(self._update_action_buttons)
        self.table.itemDoubleClicked.connect(lambda _item: self._emit_edit())

        self.edit_button = QPushButton("Edit")
        self.edit_button.setObjectName("allTasksEditButton")
        self.edit_button.clicked.connect(self._emit_edit)
        self.status_button = QPushButton("Mark Completed")
        self.status_button.setObjectName("allTasksStatusButton")
        self.status_button.clicked.connect(self._emit_status_change)
        self.delete_button = QPushButton("Delete")
        self.delete_button.setObjectName("allTasksDeleteButton")
        self.delete_button.clicked.connect(self._emit_delete)

        action_layout = QHBoxLayout()
        action_layout.addStretch(1)
        action_layout.addWidget(self.edit_button)
        action_layout.addWidget(self.status_button)
        action_layout.addWidget(self.delete_button)

        layout = QVBoxLayout(self)
        layout.addLayout(filter_layout)
        layout.addWidget(self.table)
        layout.addLayout(action_layout)

        self.refresh()

    @property
    def selected_filter(self) -> str:
        return self.filter_combo.currentText()

    def _hover_task(self, _target, event):
        row = self.table.indexAt(event.pos()).row()
        if 0 <= row < len(self.current_tasks):
            viewport = self.table.viewport()
            anchor = QRect(viewport.mapToGlobal(QPoint(0, self.table.rowViewportPosition(row))),
                           viewport.size())
            anchor.setHeight(self.table.rowHeight(row))
            return self.current_tasks[row], anchor
        return None

    def set_filter(self, filter_name: str) -> None:
        index = self.filter_combo.findText(filter_name)
        if index < 0:
            raise ValueError(f"Unknown task filter: {filter_name}")
        self.filter_combo.setCurrentIndex(index)
        self.refresh()

    def refresh(self) -> None:
        today = self.today_provider()
        filter_name = self.selected_filter
        if filter_name == "Upcoming":
            tasks = self.repository.list_upcoming_tasks(today)
        elif filter_name == "Next 3 Days":
            tasks = self.repository.list_next_three_days_tasks(today, self.days_ahead)
        elif filter_name == "Later":
            tasks = self.repository.list_later_tasks(today, self.days_ahead)
        elif filter_name == "No Due":
            tasks = self.repository.list_no_due_tasks(today)
        elif filter_name == "Completed":
            tasks = self.repository.list_completed_tasks()
        else:
            tasks = self.repository.list_all_tasks()

        search_text = self.search_input.text().strip()
        if search_text:
            matching_ids = {
                task.id for task in self.repository.search_tasks(search_text)
            }
            tasks = [task for task in tasks if task.id in matching_ids]

        self.current_tasks = tasks
        self.table.setRowCount(len(tasks))
        for row, task in enumerate(tasks):
            tooltip = description_tooltip(task.description)
            is_no_due = task.no_due or (
                task.status.value == "pending" and task.due_date < today
            )
            values = (
                task.title,
                "No due" if is_no_due else task.due_date.isoformat(),
                (
                    "—"
                    if is_no_due
                    else task.due_time.strftime("%H:%M")
                    if task.due_time
                    else "All day"
                ),
                str(task.category),
                str(task.priority),
                str(task.status),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(tooltip)
                item.setData(Qt.ItemDataRole.UserRole, task.id)
                if task.status.value == "completed":
                    font = item.font()
                    font.setStrikeOut(True)
                    item.setFont(font)
                self.table.setItem(row, column, item)
        self.count_label.setText(f"{len(tasks)} task" + ("" if len(tasks) == 1 else "s"))
        self._update_action_buttons()

        refresh_description_popup(self, tasks)

    def selected_task(self) -> Task | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.current_tasks):
            return None
        return self.current_tasks[row]

    def select_task(self, task_id: int) -> bool:
        for row, task in enumerate(self.current_tasks):
            if task.id == task_id:
                self.table.selectRow(row)
                return True
        return False

    def _update_action_buttons(self) -> None:
        task = self.selected_task()
        self.edit_button.setEnabled(task is not None)
        self.delete_button.setEnabled(task is not None)
        if task is None:
            self.status_button.setText("Mark Completed")
            self.status_button.setEnabled(False)
        elif task.status.value == "completed":
            self.status_button.setText("Restore")
            self.status_button.setEnabled(True)
        elif task.status.value == "pending":
            self.status_button.setText("Mark Completed")
            self.status_button.setEnabled(True)
        else:
            self.status_button.setText("Unavailable")
            self.status_button.setEnabled(False)

    def _emit_edit(self) -> None:
        task = self.selected_task()
        if task is not None and task.id is not None:
            self.edit_requested.emit(task.id)

    def _emit_status_change(self) -> None:
        task = self.selected_task()
        if task is None or task.id is None:
            return
        if task.status.value == "completed":
            self.restore_requested.emit(task.id)
        elif task.status.value == "pending":
            self.complete_requested.emit(task.id)

    def _emit_delete(self) -> None:
        task = self.selected_task()
        if task is not None and task.id is not None:
            self.delete_requested.emit(task.id)

    def showEvent(self, event: QShowEvent) -> None:
        self.refresh()
        super().showEvent(event)
