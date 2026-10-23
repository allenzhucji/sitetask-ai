from __future__ import annotations

from datetime import date, datetime, time

import pytest
from PySide6.QtCore import Qt

from app.database.connection import Database
from app.database.task_repository import TaskRepository
from app.models.task import Task, TaskStatus
from app.services.settings_service import SettingsService
from app.ui.all_tasks_dialog import AllTasksDialog
from app.ui.main_widget import MainWidget
from app.utils.paths import AppPaths


TODAY = date(2026, 7, 17)
NOW = datetime.fromisoformat("2026-07-17T09:00:00+04:00")


@pytest.fixture
def repository(tmp_path):
    repository = TaskRepository(Database(tmp_path / "tasks.db"), clock=lambda: NOW)
    task_data = (
        ("Overdue", date(2026, 7, 1), TaskStatus.PENDING),
        ("Today", TODAY, TaskStatus.PENDING),
        ("Tomorrow", date(2026, 7, 18), TaskStatus.PENDING),
        ("Day after", date(2026, 7, 19), TaskStatus.PENDING),
        ("Later", date(2026, 8, 15), TaskStatus.PENDING),
        ("Completed", TODAY, TaskStatus.COMPLETED),
        ("Cancelled", date(2026, 8, 20), TaskStatus.CANCELLED),
    )
    for title, due_date, status in task_data:
        repository.create_task(
            Task(
                title=title,
                due_date=due_date,
                due_time=time(10, 0) if title == "Tomorrow" else None,
                status=status,
                completed_at=NOW if status is TaskStatus.COMPLETED else None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
    return repository


def test_all_filters_use_their_repository_definitions(qtbot, repository):
    dialog = AllTasksDialog(repository, today_provider=lambda: TODAY)
    qtbot.addWidget(dialog)

    expected = {
        "Upcoming": {"Today", "Tomorrow", "Day after", "Later"},
        "Next 3 Days": {"Today", "Tomorrow", "Day after"},
        "Later": {"Later"},
        "No Due": {"Overdue"},
        "Completed": {"Completed"},
        "All": {
            "Overdue",
            "Today",
            "Tomorrow",
            "Day after",
            "Later",
            "Completed",
            "Cancelled",
        },
    }
    for filter_name, titles in expected.items():
        dialog.set_filter(filter_name)
        assert {task.title for task in dialog.current_tasks} == titles
        assert dialog.table.rowCount() == len(titles)


def test_table_displays_required_task_fields(qtbot, repository):
    dialog = AllTasksDialog(repository, today_provider=lambda: TODAY)
    qtbot.addWidget(dialog)
    dialog.set_filter("Next 3 Days")

    row = next(
        row
        for row in range(dialog.table.rowCount())
        if dialog.table.item(row, 0).text() == "Tomorrow"
    )
    assert dialog.table.item(row, 1).text() == "2026-07-18"
    assert dialog.table.item(row, 2).text() == "10:00"
    assert dialog.table.item(row, 3).text() == "Other"
    assert dialog.table.item(row, 4).text() == "normal"
    assert dialog.table.item(row, 5).text() == "pending"


def test_no_due_filter_hides_obsolete_date_and_time(qtbot, repository):
    dialog = AllTasksDialog(repository, today_provider=lambda: TODAY)
    qtbot.addWidget(dialog)
    dialog.set_filter("No Due")

    assert dialog.table.item(0, 0).text() == "Overdue"
    assert dialog.table.item(0, 1).text() == "No due"
    assert dialog.table.item(0, 2).text() == "—"


def test_title_entry_reuses_same_window_without_bottom_duplicate(qtbot, tmp_path):
    paths = AppPaths(tmp_path)
    widget = MainWidget(
        SettingsService(paths),
        today_provider=lambda: TODAY,
        now_provider=lambda: NOW,
    )
    qtbot.addWidget(widget)
    widget.show()

    qtbot.mouseClick(widget.title_bar.all_tasks_button, Qt.MouseButton.LeftButton)
    first_dialog = widget.all_tasks_dialog
    assert first_dialog is not None
    assert first_dialog.isVisible()

    first_dialog.hide()
    qtbot.mouseClick(widget.title_bar.all_tasks_button, Qt.MouseButton.LeftButton)
    assert widget.all_tasks_dialog is first_dialog
    assert first_dialog.isVisible()
    assert not hasattr(widget, "view_all_tasks_button")


def test_visible_all_tasks_window_refreshes_with_main_widget(qtbot, tmp_path):
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
    widget.open_all_tasks()
    assert widget.all_tasks_dialog.table.rowCount() == 0

    repository.create_task(
        Task(title="New task", due_date=TODAY, created_at=NOW, updated_at=NOW)
    )
    widget.refresh_tasks()

    assert widget.all_tasks_dialog.table.rowCount() == 1
    assert widget.all_tasks_dialog.table.item(0, 0).text() == "New task"
