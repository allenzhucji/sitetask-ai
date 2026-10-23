from __future__ import annotations

from datetime import date, datetime

import pytest
from PySide6.QtCore import QDate, QTime, Qt
from PySide6.QtWidgets import QMessageBox

from app.database.connection import Database
from app.database.task_repository import TaskRepository
from app.services.settings_service import SettingsService
from app.ui.main_widget import MainWidget
from app.utils.paths import AppPaths


TODAY = date(2026, 7, 17)
FIXED_NOW = datetime.fromisoformat("2026-07-17T08:00:00+04:00")


@pytest.fixture
def widget_and_repository(qtbot, tmp_path):
    paths = AppPaths(tmp_path)
    repository = TaskRepository(Database(paths.database_file), clock=lambda: FIXED_NOW)
    widget = MainWidget(
        SettingsService(paths),
        repository,
        today_provider=lambda: TODAY,
        now_provider=lambda: FIXED_NOW,
    )
    qtbot.addWidget(widget)
    widget.show()
    return widget, repository


def submit(widget: MainWidget, qtbot, title: str, due_date: str, due_time: str = ""):
    widget.quick_add.title_input.setText(title)
    widget.quick_add.date_input.setDate(QDate.fromString(due_date, "yyyy-MM-dd"))
    widget.quick_add.all_day_checkbox.setChecked(not due_time)
    if due_time:
        widget.quick_add.time_input.setTime(QTime.fromString(due_time, "HH:mm"))
    qtbot.mouseClick(widget.quick_add.add_button, Qt.MouseButton.LeftButton)


def test_date_and_time_use_format_safe_controls_and_time_is_optional(
    widget_and_repository,
    qtbot,
):
    widget, repository = widget_and_repository

    assert widget.quick_add.date_input.currentText() == TODAY.isoformat()
    assert widget.quick_add.date_input.date().toPython() == TODAY
    assert widget.quick_add.time_input.displayFormat() == "HH:mm"
    assert widget.quick_add.all_day_checkbox.isChecked()
    assert not widget.quick_add.time_input.isEnabled()

    submit(widget, qtbot, "   ", "2026-07-18")
    assert widget.quick_add.status_label.text() == "任务标题不能为空。"
    assert repository.list_all_tasks() == []


def test_date_can_be_typed_directly_and_far_future_value_is_saved(
    widget_and_repository,
    qtbot,
):
    widget, repository = widget_and_repository
    date_input = widget.quick_add.date_input

    assert date_input.isEditable()
    date_input.lineEdit().setFocus()
    date_input.lineEdit().selectAll()
    qtbot.keyClicks(date_input.lineEdit(), "2027-01-10")
    qtbot.keyPress(date_input.lineEdit(), Qt.Key.Key_Return)

    assert date_input.currentText() == "2027-01-10"
    assert date_input.date().toPython() == date(2027, 1, 10)
    assert date_input.findText("2027-01-10") >= 0

    widget.quick_add.title_input.setText("Annual document review")
    qtbot.mouseClick(widget.quick_add.add_button, Qt.MouseButton.LeftButton)

    tasks = repository.list_all_tasks()
    assert len(tasks) == 1
    assert tasks[0].due_date == date(2027, 1, 10)


def test_setting_existing_date_repeatedly_does_not_duplicate_menu_item(
    widget_and_repository,
):
    widget, _repository = widget_and_repository
    date_input = widget.quick_add.date_input
    today = QDate(TODAY.year, TODAY.month, TODAY.day)

    date_input.setDate(today)
    date_input.setDate(today)

    matching_items = [
        date_input.itemText(index)
        for index in range(date_input.count())
        if date_input.itemText(index) == TODAY.isoformat()
    ]
    assert matching_items == [TODAY.isoformat()]


def test_invalid_typed_date_uses_existing_validation_message(
    widget_and_repository,
    qtbot,
):
    widget, repository = widget_and_repository
    widget.quick_add.title_input.setText("Invalid date test")
    widget.quick_add.date_input.lineEdit().selectAll()
    qtbot.keyClicks(widget.quick_add.date_input.lineEdit(), "2026-02-30")

    qtbot.mouseClick(widget.quick_add.add_button, Qt.MouseButton.LeftButton)

    assert repository.list_all_tasks() == []
    assert widget.quick_add.status_label.text() == "日期格式无效，请使用 YYYY-MM-DD。"


def test_today_task_is_added_displayed_and_inputs_are_cleared(
    widget_and_repository,
    qtbot,
):
    widget, repository = widget_and_repository

    submit(widget, qtbot, "  Inspect reinforcement  ", "2026-07-17", "09:30")

    tasks = repository.list_all_tasks()
    assert len(tasks) == 1
    assert tasks[0].title == "Inspect reinforcement"
    assert tasks[0].due_time.strftime("%H:%M") == "09:30"
    assert [section.title for section in widget.sections] == ["TODAY"]
    assert widget.quick_add.title_input.text() == ""
    assert widget.quick_add.date_input.date().toPython() == TODAY
    assert widget.quick_add.all_day_checkbox.isChecked()
    assert widget.quick_add.status_label.text() == "任务已添加。"


def test_far_future_task_is_saved_but_not_expanded_in_widget(
    widget_and_repository,
    qtbot,
):
    widget, repository = widget_and_repository

    submit(widget, qtbot, "Annual document review", "2027-01-10")

    tasks = repository.list_all_tasks()
    assert len(tasks) == 1
    assert tasks[0].due_date == date(2027, 1, 10)
    assert tasks[0].due_time is None
    assert widget.sections == []
    assert repository.count_later_tasks(TODAY) == 1
    assert widget.summary_label.text() == "Next 3 Days：0\nAfter 3 Days：1"
    assert widget.quick_add.status_label.text() == "任务已保存，将在进入未来三天范围后显示。"


def test_past_task_can_be_added_after_confirmation(
    widget_and_repository,
    qtbot,
    monkeypatch,
):
    widget, repository = widget_and_repository
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    submit(widget, qtbot, "Close old IRF", "2026-06-01")

    tasks = repository.list_all_tasks()
    assert len(tasks) == 1
    assert tasks[0].due_date == date(2026, 6, 1)
    assert [section.title for section in widget.sections] == ["NO DUE"]
