from __future__ import annotations

from datetime import date, datetime, time

import pytest
from PySide6.QtCore import QDate, QTime, QTimer
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from app.database.connection import Database
from app.database.task_repository import TaskRepository
from app.models.task import Category, Priority, Task, TaskStatus
from app.services.settings_service import SettingsService
from app.ui.main_widget import MainWidget
from app.ui.task_editor_dialog import TaskEditorDialog
from app.utils.paths import AppPaths


TODAY = date(2026, 7, 17)
NOW = datetime.fromisoformat("2026-07-17T09:00:00+04:00")


@pytest.fixture
def widget_and_repository(qtbot, tmp_path):
    paths = AppPaths(tmp_path)
    repository = TaskRepository(Database(paths.database_file), clock=lambda: NOW)
    widget = MainWidget(
        SettingsService(paths),
        repository,
        today_provider=lambda: TODAY,
        now_provider=lambda: NOW,
    )
    qtbot.addWidget(widget)
    widget.show()
    return widget, repository


def complete_dialog(**changes):
    dialog = QApplication.activeModalWidget()
    assert isinstance(dialog, TaskEditorDialog)
    if "title" in changes:
        dialog.title_input.setText(changes["title"])
    if "description" in changes:
        dialog.description_input.setPlainText(changes["description"])
    if "due_date" in changes:
        value = changes["due_date"]
        dialog.due_date_input.setDate(QDate(value.year, value.month, value.day))
    if "due_time" in changes:
        value = changes["due_time"]
        dialog.all_day_checkbox.setChecked(value is None)
        if value is not None:
            dialog.due_time_input.setTime(QTime(value.hour, value.minute))
    for field, combo_name in (
        ("category", "category_input"),
        ("priority", "priority_input"),
        ("status", "status_input"),
    ):
        if field in changes:
            combo = getattr(dialog, combo_name)
            combo.setCurrentIndex(combo.findData(changes[field]))
    dialog.button_box.button(QDialogButtonBox.StandardButton.Save).click()


def test_editor_loads_and_returns_all_task_fields(qtbot):
    task = Task(
        title="Review drawing",
        description="Check revision C",
        due_date=TODAY,
        due_time=time(10, 30),
        category=Category.DRAWING,
        priority=Priority.HIGH,
        status=TaskStatus.PENDING,
        created_at=NOW,
        updated_at=NOW,
    )
    dialog = TaskEditorDialog(task, today_provider=lambda: TODAY)
    qtbot.addWidget(dialog)

    values = dialog.values()
    assert values == {
        "title": "Review drawing",
        "description": "Check revision C",
        "due_date": TODAY,
        "due_time": time(10, 30),
        "no_due": False,
        "category": Category.DRAWING,
        "priority": Priority.HIGH,
        "status": TaskStatus.PENDING,
    }


def test_editor_can_create_no_due_task_and_disables_date_controls(qtbot):
    dialog = TaskEditorDialog(today_provider=lambda: TODAY)
    qtbot.addWidget(dialog)
    dialog.title_input.setText("Long-term follow-up")
    dialog.no_due_checkbox.setChecked(True)

    values = dialog.values()
    assert values["no_due"] is True
    assert values["due_time"] is None
    assert not dialog.due_date_input.isEnabled()
    assert not dialog.due_time_input.isEnabled()
    assert not dialog.all_day_checkbox.isEnabled()


def test_full_editor_creates_far_future_task(widget_and_repository):
    widget, repository = widget_and_repository
    QTimer.singleShot(
        0,
        lambda: complete_dialog(
            title="Annual records review",
            description="Archive approved documents",
            due_date=date(2027, 1, 10),
            due_time=None,
            category=Category.FOLLOW_UP,
            priority=Priority.NORMAL,
        ),
    )

    widget.open_task_editor()

    tasks = repository.list_all_tasks()
    assert len(tasks) == 1
    assert tasks[0].due_date == date(2027, 1, 10)
    assert tasks[0].description == "Archive approved documents"
    assert widget.sections == []
    assert repository.count_later_tasks(TODAY) == 1


def test_editing_due_date_moves_task_in_and_out_of_widget(widget_and_repository):
    widget, repository = widget_and_repository
    task = repository.create_task(
        Task(
            title="Submit report",
            due_date=date(2026, 9, 1),
            created_at=NOW,
            updated_at=NOW,
        )
    )

    QTimer.singleShot(0, lambda: complete_dialog(due_date=date(2026, 7, 18)))
    widget.open_task_editor(task.id)
    assert [section.title for section in widget.sections] == ["TOMORROW"]

    QTimer.singleShot(0, lambda: complete_dialog(due_date=date(2026, 10, 1)))
    widget.open_task_editor(task.id)
    assert widget.sections == []
    assert repository.get_task(task.id).due_date == date(2026, 10, 1)
    assert repository.count_later_tasks(TODAY) == 1
