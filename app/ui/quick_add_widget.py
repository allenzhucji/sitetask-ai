from __future__ import annotations

from collections.abc import Callable
from datetime import date, time

from PySide6.QtCore import QDate, QTime, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from app.ui.date_combo import DateComboBox


class QuickAddWidget(QWidget):
    submitted = Signal(str, str, str)
    full_editor_requested = Signal()

    def __init__(
        self,
        *,
        today_provider: Callable[[], date] = date.today,
        default_due_time: str = "17:00",
    ) -> None:
        super().__init__()
        self.today_provider = today_provider
        self.setObjectName("quickAddWidget")

        heading = QLabel("＋ Quick Task")
        heading.setObjectName("quickAddHeading")

        self.title_input = QLineEdit()
        self.title_input.setObjectName("quickTaskTitle")
        self.title_input.setPlaceholderText("Task title")

        # 滚动日期选择：下拉为日期列表（宽度与控件一致），替代日历弹窗
        self.date_input = DateComboBox(today=self.today_provider())
        self.date_input.setObjectName("quickTaskDate")
        self.date_input.setMaximumWidth(120)
        self._date_manually_set = False
        self._reset_date()
        self.date_input.dateChanged.connect(self._on_date_changed)

        # 时间输入用原生 QTimeEdit：qfluentwidgets 的 Fluent TimeEdit 在
        # PySide6 移植版下存在文本区渲染缺陷（lineEdit 几何错乱、文字
        # 不可见），原生控件由 dark.qss 提供圆角/边框/disabled 样式
        self.time_input = QTimeEdit()
        self.time_input.setObjectName("quickTaskTime")
        self.time_input.setDisplayFormat("HH:mm")
        self.time_input.setMaximumWidth(120)
        self.set_default_due_time(default_due_time)

        self.all_day_checkbox = QCheckBox("All day")
        self.all_day_checkbox.setObjectName("quickTaskAllDay")
        self.all_day_checkbox.setChecked(True)
        self.all_day_checkbox.toggled.connect(
            lambda checked: self.time_input.setEnabled(not checked)
        )
        self.time_input.setEnabled(False)

        self.add_button = QPushButton("Add")
        self.add_button.setObjectName("quickTaskAddButton")
        self.add_button.clicked.connect(self._submit)

        self.full_editor_button = QPushButton("More…")
        self.full_editor_button.setObjectName("fullTaskEditorButton")
        self.full_editor_button.setToolTip("Open full task editor")
        self.full_editor_button.clicked.connect(self.full_editor_requested)

        self.status_label = QLabel()
        self.status_label.setObjectName("quickTaskStatus")
        self.status_label.setWordWrap(True)
        self.status_label.hide()

        field_layout = QGridLayout()
        field_layout.setContentsMargins(0, 0, 0, 0)
        field_layout.setSpacing(6)
        field_layout.addWidget(self.date_input, 0, 0)
        field_layout.addWidget(self.time_input, 0, 1)
        field_layout.addWidget(self.all_day_checkbox, 0, 2)
        field_layout.addWidget(self.add_button, 1, 0, 1, 2)
        field_layout.addWidget(self.full_editor_button, 1, 2)
        field_layout.setColumnStretch(0, 1)
        field_layout.setColumnStretch(1, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 9, 10, 9)
        layout.setSpacing(6)
        layout.addWidget(heading)
        layout.addWidget(self.title_input)
        layout.addLayout(field_layout)
        layout.addWidget(self.status_label)

        self.title_input.returnPressed.connect(self._submit)

    def show_message(self, message: str, *, error: bool = False) -> None:
        self.status_label.setText(message)
        self.status_label.setStyleSheet(
            "color: #e07a7a;" if error else "color: #79c2bb;"
        )
        self.status_label.show()

    def clear_inputs(self) -> None:
        self.title_input.clear()
        self._reset_date()
        self._date_manually_set = False
        self.all_day_checkbox.setChecked(True)
        self.title_input.setFocus()

    def set_default_due_time(self, value: str) -> None:
        parsed = time.fromisoformat(value)
        self.time_input.setTime(QTime(parsed.hour, parsed.minute))

    def refresh_date_if_auto(self) -> None:
        """Advance the default date to the latest today after a day rollover.

        Only applies when the user has not picked a date manually; a date the
        user chose explicitly (for example tomorrow) is never overwritten.
        """
        if self._date_manually_set:
            return
        today = self.today_provider()
        if self.date_input.date().toPython() < today:
            self._reset_date()

    def _on_date_changed(self, _date: QDate) -> None:
        self._date_manually_set = True

    def _reset_date(self) -> None:
        today = self.today_provider()
        self.date_input.blockSignals(True)
        self.date_input.setDate(QDate(today.year, today.month, today.day))
        self.date_input.blockSignals(False)

    def _submit(self) -> None:
        self.submitted.emit(
            self.title_input.text(),
            # 使用编辑框原文，使直接键入的有效/无效日期都进入统一验证；
            # 下拉选择时 currentText 同样是 YYYY-MM-DD。
            self.date_input.currentText().strip(),
            "" if self.all_day_checkbox.isChecked() else self.time_input.time().toString("HH:mm"),
        )
