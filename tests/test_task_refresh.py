from __future__ import annotations

from datetime import date, datetime

from PySide6.QtCore import Qt

from app.database.connection import Database
from app.database.task_repository import TaskRepository
from app.models.task import Task
from app.services.settings_service import SettingsService
from app.ui.main_widget import MainWidget
from app.utils.paths import AppPaths


FIXED_NOW = datetime.fromisoformat("2026-07-17T08:00:00+04:00")


def make_widget(tmp_path, current_date: list[date]):
    paths = AppPaths(tmp_path)
    repository = TaskRepository(Database(paths.database_file), clock=lambda: FIXED_NOW)
    widget = MainWidget(
        SettingsService(paths),
        repository,
        today_provider=lambda: current_date[0],
    )
    return widget, repository


def add_task(repository: TaskRepository, title: str, due_date: date) -> Task:
    return repository.create_task(
        Task(
            title=title,
            due_date=due_date,
            created_at=FIXED_NOW,
            updated_at=FIXED_NOW,
        )
    )


def test_refresh_timer_runs_every_sixty_seconds(qtbot, tmp_path):
    current_date = [date(2026, 7, 17)]
    widget, _ = make_widget(tmp_path, current_date)
    qtbot.addWidget(widget)

    assert widget.refresh_timer.isActive()
    assert widget.refresh_timer.interval() == 60_000


def test_empty_database_shows_add_task_guidance(qtbot, tmp_path):
    current_date = [date(2026, 7, 17)]
    widget, _ = make_widget(tmp_path, current_date)
    qtbot.addWidget(widget)
    widget.show()

    assert widget.sections == []
    assert widget.summary_label.text() == "Next 3 Days：0\nAfter 3 Days：0"
    assert widget.summary_label.alignment() == (
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    )
    assert widget.summary_label.parent() is widget.input_toggle_bar
    assert widget.summary_label.x() < widget.input_panel_toggle_button.x()
    assert widget.empty_state is not None
    assert widget.empty_state.title_label.text() == "暂无任务"
    assert widget.empty_state.message_label.text() == "使用 Quick Task 或 AI Task 添加任务"
    assert not widget.empty_state.view_later_button.isVisible()


def test_only_later_tasks_shows_later_empty_state_and_count(qtbot, tmp_path):
    current_date = [date(2026, 7, 17)]
    widget, repository = make_widget(tmp_path, current_date)
    add_task(repository, "Submit monthly report", date(2026, 8, 15))

    widget.refresh_tasks()
    widget.show()

    assert widget.sections == []
    assert widget.summary_label.text() == "Next 3 Days：0\nAfter 3 Days：1"
    assert widget.empty_state is not None
    assert widget.empty_state.title_label.text() == "未来三天暂无任务"
    assert widget.empty_state.message_label.text() == "还有 1 个后续任务"
    assert widget.empty_state.view_later_button.isVisible()
    assert not widget.empty_state.view_later_button.isEnabled()


def test_timer_refresh_recomputes_date_range_and_replaces_empty_state(qtbot, tmp_path):
    current_date = [date(2026, 7, 17)]
    widget, repository = make_widget(tmp_path, current_date)
    task = add_task(repository, "Monday inspection", date(2026, 7, 20))
    widget.refresh_tasks()

    assert widget.sections == []
    assert widget.repository.count_later_tasks(current_date[0]) == 1

    current_date[0] = date(2026, 7, 18)
    widget.refresh_timer.timeout.emit()

    assert [section.title for section in widget.sections] == ["DAY AFTER TOMORROW"]
    assert widget.sections[0].task_items[0].task.id == task.id
    assert widget.empty_state is None
    assert widget.summary_label.text() == "Next 3 Days：1\nAfter 3 Days：0"


def test_next_three_days_count_includes_no_due_tasks(qtbot, tmp_path):
    current_date = [date(2026, 7, 17)]
    widget, repository = make_widget(tmp_path, current_date)
    repository.create_task(
        Task(
            title="Long-term follow-up",
            due_date=date(2027, 1, 1),
            no_due=True,
            created_at=FIXED_NOW,
            updated_at=FIXED_NOW,
        )
    )
    add_task(repository, "Today task", current_date[0])

    widget.refresh_tasks()

    assert widget.summary_label.text() == "Next 3 Days：2\nAfter 3 Days：0"
