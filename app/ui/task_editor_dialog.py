from __future__ import annotations

from collections.abc import Callable
from datetime import date

from PySide6.QtCore import QDate, QTime
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QTextEdit,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import ComboBox

from app.models.task import Category, Priority, Task, TaskStatus
from app.ui.date_edit import StyledDateEdit
from app.utils.validation import normalize_task_title


class TaskEditorDialog(QDialog):
    def __init__(
        self,
        task: Task | None = None,
        *,
        default_category: str = Category.OTHER,
        default_priority: str = Priority.NORMAL,
        today_provider: Callable[[], date] = date.today,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.task = task
        self.today_provider = today_provider
        self.setWindowTitle("Edit Task" if task else "Add Task")
        self.setModal(True)
        self.setMinimumWidth(380)

        self.title_input = QLineEdit()
        self.description_input = QTextEdit()
        self.description_input.setMaximumHeight(90)
        self.due_date_input = StyledDateEdit()
        # 原生 QTimeEdit（同 quick_add_widget，Fluent TimeEdit 在 PySide6
        # 移植版下文本渲染不可靠）
        self.due_time_input = QTimeEdit()
        self.due_time_input.setDisplayFormat("HH:mm")
        self.no_due_checkbox = QCheckBox("No due (long-term task)")
        self.no_due_checkbox.toggled.connect(self._set_no_due)
        self.all_day_checkbox = QCheckBox("All day")
        self.all_day_checkbox.toggled.connect(
            lambda checked: self.due_time_input.setEnabled(
                not checked and not self.no_due_checkbox.isChecked()
            )
        )

        self.category_input = ComboBox()
        for category in Category:
            self.category_input.addItem(str(category), userData=category)
        self.priority_input = ComboBox()
        for priority in Priority:
            self.priority_input.addItem(str(priority), userData=priority)
        self.status_input = ComboBox()
        for status in TaskStatus:
            self.status_input.addItem(str(status), userData=status)

        time_row = QWidget()
        time_layout = QVBoxLayout(time_row)
        time_layout.setContentsMargins(0, 0, 0, 0)
        time_layout.setSpacing(4)
        time_layout.addWidget(self.due_time_input)
        time_layout.addWidget(self.all_day_checkbox)

        form = QFormLayout()
        form.addRow("Title", self.title_input)
        form.addRow("Description", self.description_input)
        form.addRow("", self.no_due_checkbox)
        form.addRow("Due Date", self.due_date_input)
        form.addRow("Due Time", time_row)
        form.addRow("Category", self.category_input)
        form.addRow("Priority", self.priority_input)
        form.addRow("Status", self.status_input)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.button_box)

        self._populate(task, default_category, default_priority)

    def _populate(
        self,
        task: Task | None,
        default_category: str,
        default_priority: str,
    ) -> None:
        today = self.today_provider()
        due_date = task.due_date if task else today
        self.due_date_input.setDate(QDate(due_date.year, due_date.month, due_date.day))
        self.title_input.setText(task.title if task else "")
        self.description_input.setPlainText(task.description or "" if task else "")

        due_time = task.due_time if task else None
        self.all_day_checkbox.setChecked(due_time is None)
        if due_time is not None:
            self.due_time_input.setTime(QTime(due_time.hour, due_time.minute))

        # Pending dated tasks automatically move into NO DUE after their date.
        # Editing one should reflect the group it currently belongs to.
        no_due = bool(
            task
            and (task.no_due or (task.status == TaskStatus.PENDING and due_date < today))
        )
        self.no_due_checkbox.setChecked(no_due)
        self._set_no_due(no_due)

        category = task.category if task else self._category_or_other(default_category)
        priority = task.priority if task else self._priority_or_normal(default_priority)
        status = task.status if task else TaskStatus.PENDING
        self._select_data(self.category_input, category)
        self._select_data(self.priority_input, priority)
        self._select_data(self.status_input, status)

    def values(self) -> dict[str, object]:
        due_date_value = self.due_date_input.date().toPython()
        due_time_value = None
        no_due = self.no_due_checkbox.isChecked()
        if not no_due and not self.all_day_checkbox.isChecked():
            due_time_value = self.due_time_input.time().toPython()
        description = self.description_input.toPlainText().strip() or None
        return {
            "title": normalize_task_title(self.title_input.text()),
            "description": description,
            "due_date": due_date_value,
            "due_time": due_time_value,
            "no_due": no_due,
            "category": self.category_input.currentData(),
            "priority": self.priority_input.currentData(),
            "status": self.status_input.currentData(),
        }

    def accept(self) -> None:
        try:
            values = self.values()
        except ValueError as error:
            QMessageBox.warning(self, "Invalid Task", str(error))
            return
        if not values["no_due"] and values["due_date"] < self.today_provider():
            answer = QMessageBox.question(
                self,
                "Past Due Date",
                "截止日期早于今天，仍要保存吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        super().accept()

    def _set_no_due(self, checked: bool) -> None:
        self.due_date_input.setEnabled(not checked)
        self.all_day_checkbox.setEnabled(not checked)
        self.due_time_input.setEnabled(
            not checked and not self.all_day_checkbox.isChecked()
        )

    @staticmethod
    def _select_data(combo: ComboBox, value: object) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    @staticmethod
    def _category_or_other(value: str) -> Category:
        try:
            return Category(value)
        except ValueError:
            return Category.OTHER

    @staticmethod
    def _priority_or_normal(value: str) -> Priority:
        try:
            return Priority(value)
        except ValueError:
            return Priority.NORMAL
