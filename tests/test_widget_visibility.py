from __future__ import annotations

from datetime import date, datetime, time

import pytest

from app.database.connection import Database
from app.database.task_repository import TaskRepository
from app.models.task import Category, Priority, Task, TaskStatus


TODAY = date(2026, 7, 17)
FIXED_NOW = datetime.fromisoformat("2026-07-17T08:00:00+04:00")


@pytest.fixture
def repository(tmp_path) -> TaskRepository:
    return TaskRepository(
        Database(tmp_path / "sitetask.db"),
        clock=lambda: FIXED_NOW,
    )


def add_task(
    repository: TaskRepository,
    title: str,
    due_date: date,
    *,
    due_time: time | None = None,
    priority: Priority = Priority.NORMAL,
    status: TaskStatus = TaskStatus.PENDING,
    description: str | None = None,
) -> Task:
    return repository.create_task(
        Task(
            title=title,
            description=description,
            due_date=due_date,
            due_time=due_time,
            category=Category.OTHER,
            priority=priority,
            status=status,
            created_at=FIXED_NOW,
            updated_at=FIXED_NOW,
        )
    )


def ids(tasks: list[Task]) -> set[int | None]:
    return {task.id for task in tasks}


def test_far_future_task_is_saved_but_only_listed_as_upcoming_and_later(repository):
    future = add_task(repository, "Submit monthly report", date(2026, 8, 15))

    assert repository.get_task(future.id) == future
    assert future.id not in ids(repository.list_widget_tasks(TODAY))
    assert future.id in ids(repository.list_later_tasks(TODAY))
    assert future.id in ids(repository.list_upcoming_tasks(TODAY))


def test_task_enters_three_day_window_when_today_changes(repository):
    task = add_task(repository, "Monday site inspection", date(2026, 7, 20))

    assert task.id not in ids(repository.list_widget_tasks(date(2026, 7, 17)))
    assert task.id in ids(repository.list_later_tasks(date(2026, 7, 17)))

    new_today = date(2026, 7, 18)
    assert task.id in ids(repository.list_widget_tasks(new_today))
    assert task.id in ids(repository.list_next_three_days_tasks(new_today))
    assert task.id not in ids(repository.list_later_tasks(new_today))


def test_overdue_pending_task_remains_visible_until_completed(repository):
    overdue = add_task(repository, "Close old IRF", date(2026, 6, 1))

    assert overdue.id in ids(repository.list_widget_tasks(TODAY))
    assert overdue.id in ids(repository.list_overdue_tasks(TODAY))
    assert overdue.id in ids(repository.list_no_due_tasks(TODAY))

    repository.complete_task(overdue.id)

    assert overdue.id not in ids(repository.list_widget_tasks(TODAY))
    assert overdue.id in ids(repository.list_completed_tasks())


def test_unfinished_today_task_rolls_into_no_due_on_next_day(repository):
    task = add_task(repository, "Unfinished today", TODAY)

    assert task.id not in ids(repository.list_no_due_tasks(TODAY))
    assert task.id in ids(repository.list_no_due_tasks(date(2026, 7, 18)))
    assert task.id in ids(repository.list_widget_tasks(date(2026, 7, 18)))


def test_explicit_no_due_task_is_pinned_and_excluded_from_dated_lists(repository):
    task = repository.create_task(
        Task(
            title="Long-term task",
            due_date=date(2027, 1, 1),
            due_time=time(9, 0),
            no_due=True,
            created_at=FIXED_NOW,
            updated_at=FIXED_NOW,
        )
    )

    assert task.id in ids(repository.list_no_due_tasks(TODAY))
    assert task.id in ids(repository.list_widget_tasks(TODAY))
    assert task.id not in ids(repository.list_upcoming_tasks(TODAY))
    assert task.id not in ids(repository.list_later_tasks(TODAY))
    assert task.id not in ids(
        repository.list_notification_candidates(TODAY, date(2027, 1, 2))
    )


def test_filters_search_and_counts_use_pending_status(repository):
    overdue = add_task(repository, "Overdue inspection", date(2026, 7, 10))
    today = add_task(
        repository,
        "Reply IRF-023",
        date(2026, 7, 17),
        description="Reply to consultant",
    )
    later = add_task(repository, "Renew permit", date(2026, 10, 1))
    completed = add_task(
        repository,
        "Completed report",
        date(2026, 7, 18),
        status=TaskStatus.COMPLETED,
    )
    cancelled = add_task(
        repository,
        "Cancelled meeting",
        date(2026, 7, 18),
        status=TaskStatus.CANCELLED,
    )

    assert repository.count_widget_tasks(TODAY) == 2
    assert repository.count_later_tasks(TODAY) == 1
    assert ids(repository.list_next_three_days_tasks(TODAY)) == {today.id}
    assert ids(repository.list_overdue_tasks(TODAY)) == {overdue.id}
    assert ids(repository.list_completed_tasks()) == {completed.id}
    assert {later.id, completed.id, cancelled.id} <= ids(repository.list_all_tasks())
    assert ids(repository.search_tasks("IRF-023")) == {today.id}
    assert ids(repository.search_tasks("consultant")) == {today.id}
    assert repository.search_tasks("%") == []


def test_widget_automatically_orders_by_priority_then_due_time(repository):
    overdue = add_task(repository, "Overdue", date(2026, 7, 16), due_time=time(16, 0))
    early = add_task(
        repository,
        "Early timed",
        TODAY,
        due_time=time(9, 0),
        priority=Priority.NORMAL,
    )
    urgent_same_time = add_task(
        repository,
        "Urgent at ten",
        TODAY,
        due_time=time(10, 0),
        priority=Priority.URGENT,
    )
    normal_same_time = add_task(
        repository,
        "Normal at ten",
        TODAY,
        due_time=time(10, 0),
        priority=Priority.NORMAL,
    )
    all_day = add_task(
        repository,
        "All day urgent",
        TODAY,
        priority=Priority.URGENT,
    )

    assert [task.id for task in repository.list_widget_tasks(TODAY)] == [
        overdue.id,
        urgent_same_time.id,
        all_day.id,
        early.id,
        normal_same_time.id,
    ]
