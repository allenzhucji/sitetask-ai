from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import ComboBox

from app.models.parsed_task import ParsedTaskResult
from app.models.task import Category, Priority
from app.utils.validation import (
    normalize_task_title,
    parse_due_date,
    parse_optional_due_time,
)


class TaskPreviewDialog(QDialog):
    def __init__(
        self,
        result: ParsedTaskResult,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.result = result
        self.setWindowTitle("Task Preview")
        self.setModal(True)
        self.setMinimumWidth(430)

        self.title_input = QLineEdit()
        title = result.title
        if result.ambiguity_reason == "No actionable task title was found.":
            title = ""
        self.title_input.setText(title)
        self.description_input = QTextEdit(result.description or "")
        self.description_input.setMaximumHeight(80)
        self.due_date_input = QLineEdit(
            result.due_date.isoformat() if result.due_date else ""
        )
        self.due_date_input.setPlaceholderText("YYYY-MM-DD")
        self.due_time_input = QLineEdit(
            result.due_time.strftime("%H:%M") if result.due_time else ""
        )
        self.due_time_input.setPlaceholderText("HH:MM or blank for All day")

        self.category_input = ComboBox()
        for category in Category:
            self.category_input.addItem(str(category), userData=category)
        self.category_input.setCurrentIndex(self.category_input.findData(result.category))
        self.priority_input = ComboBox()
        for priority in Priority:
            self.priority_input.addItem(str(priority), userData=priority)
        self.priority_input.setCurrentIndex(self.priority_input.findData(result.priority))

        self.source_label = QLabel(
            "Local parser" if result.parser_source == "local" else "AI"
        )
        self.confidence_label = QLabel(f"{result.confidence:.0%}")
        self.default_time_label = QLabel("Using default time")
        self.default_time_label.setVisible(result.used_default_time)

        warnings: list[str] = []
        if result.confidence < 0.65:
            warnings.append("Low confidence — please review all fields.")
        if result.ambiguity_reason:
            warnings.append(result.ambiguity_reason)
        self.warning_label = QLabel("\n".join(warnings))
        self.warning_label.setObjectName("previewWarning")
        self.warning_label.setWordWrap(True)
        self.warning_label.setVisible(bool(warnings))

        form = QFormLayout()
        form.addRow("Task Title", self.title_input)
        form.addRow("Description", self.description_input)
        form.addRow("Due Date", self.due_date_input)
        form.addRow("Due Time", self.due_time_input)
        form.addRow("Category", self.category_input)
        form.addRow("Priority", self.priority_input)
        form.addRow("Source", self.source_label)
        form.addRow("Confidence", self.confidence_label)
        form.addRow("", self.default_time_label)
        form.addRow("Ambiguity Warning", self.warning_label)

        self.cancel_button = QPushButton("Cancel")
        self.edit_button = QPushButton("Edit")
        self.confirm_button = QPushButton("Confirm and Add")
        self.cancel_button.clicked.connect(self.reject)
        self.edit_button.clicked.connect(self.enable_editing)
        self.confirm_button.clicked.connect(self._confirm)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.edit_button)
        buttons.addWidget(self.confirm_button)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(buttons)

        for line_edit in (self.title_input, self.due_date_input, self.due_time_input):
            line_edit.textChanged.connect(self._update_confirm_state)

        self._set_editable(False)
        if result.needs_confirmation or result.confidence < 0.65:
            self.enable_editing()
        self._update_confirm_state()

    def enable_editing(self) -> None:
        self._set_editable(True)
        self.edit_button.setEnabled(False)
        self.title_input.setFocus()

    def values(self) -> dict[str, object]:
        return {
            "title": normalize_task_title(self.title_input.text()),
            "description": self.description_input.toPlainText().strip() or None,
            "due_date": parse_due_date(self.due_date_input.text()),
            "due_time": parse_optional_due_time(self.due_time_input.text()),
            "category": Category(self.category_input.currentData()),
            "priority": Priority(self.priority_input.currentData()),
        }

    def _set_editable(self, editable: bool) -> None:
        self.title_input.setReadOnly(not editable)
        self.description_input.setReadOnly(not editable)
        self.due_date_input.setReadOnly(not editable)
        self.due_time_input.setReadOnly(not editable)
        self.category_input.setEnabled(editable)
        self.priority_input.setEnabled(editable)

    def _update_confirm_state(self) -> None:
        try:
            normalize_task_title(self.title_input.text())
            parse_due_date(self.due_date_input.text())
            parse_optional_due_time(self.due_time_input.text())
        except ValueError:
            self.confirm_button.setEnabled(False)
        else:
            self.confirm_button.setEnabled(True)

    def _confirm(self) -> None:
        try:
            self.values()
        except ValueError as error:
            self.warning_label.setText(str(error))
            self.warning_label.show()
            return
        self.accept()
