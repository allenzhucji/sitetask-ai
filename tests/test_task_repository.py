from __future__ import annotations

from datetime import date, datetime, time

import pytest

from app.database.connection import Database
from app.database.task_repository import TaskRepository
from app.models.task import Category, Priority, Task, TaskStatus


CREATED_AT = datetime.fromisoformat("2026-07-17T08:00:00+04:00")
REPOSITORY_NOW = datetime.fromisoformat("2026-07-17T09:30:00+04:00")


@pytest.fixture
def repository(tmp_path) -> TaskRepository:
    return TaskRepository(
        Database(tmp_path / "data" / "sitetask.db"),
        clock=lambda: REPOSITORY_NOW,
    )


def make_future_task() -> Task:
    return Task(
        title="Submit annual report",
        description="Prepare final supporting documents",
        due_date=date(2027, 1, 10),
        due_time=time(17, 0),
        category=Category.REPORT,
        priority=Priority.NORMAL,
        created_at=CREATED_AT,
        updated_at=CREATED_AT,
    )


def test_create_and_get_future_task(repository):
    created = repository.create_task(make_future_task())
    loaded = repository.get_task(created.id)

    assert created.id is not None
    assert loaded == created
    assert loaded.due_date == date(2027, 1, 10)
    assert loaded.due_time == time(17, 0)
    assert loaded.status is TaskStatus.PENDING


def test_update_task_fields_and_timestamp(repository):
    created = repository.create_task(make_future_task())
    edited = created.model_copy(
        update={
            "title": "Review drawing Rev. C",
            "due_date": date(2026, 7, 18),
            "due_time": time(10, 15),
            "category": Category.DRAWING,
            "priority": Priority.HIGH,
        }
    )

    updated = repository.update_task(edited)

    assert updated is not None
    assert updated.title == "Review drawing Rev. C"
    assert updated.due_date == date(2026, 7, 18)
    assert updated.due_time == time(10, 15)
    assert updated.category is Category.DRAWING
    assert updated.priority is Priority.HIGH
    assert updated.updated_at == REPOSITORY_NOW


def test_complete_and_restore_task(repository):
    created = repository.create_task(make_future_task())

    completed = repository.complete_task(created.id)

    assert completed is not None
    assert completed.status is TaskStatus.COMPLETED
    assert completed.completed_at == REPOSITORY_NOW

    restored = repository.restore_task(created.id)

    assert restored is not None
    assert restored.status is TaskStatus.PENDING
    assert restored.completed_at is None
    assert restored.updated_at == REPOSITORY_NOW


def test_delete_task_is_idempotent(repository):
    created = repository.create_task(make_future_task())

    assert repository.delete_task(created.id) is True
    assert repository.get_task(created.id) is None
    assert repository.delete_task(created.id) is False


def _make_task(
    title: str,
    due_date: date = date(2026, 8, 1),
    priority: Priority = Priority.NORMAL,
) -> Task:
    return Task(
        title=title,
        due_date=due_date,
        priority=priority,
        created_at=CREATED_AT,
        updated_at=CREATED_AT,
    )


def _create_and_return(repository: TaskRepository, task: Task) -> Task:
    return repository.create_task(task)


class TestReorderTasksForDate:
    def test_persists_complete_manual_order(self, repository):
        a = _create_and_return(repository, _make_task("A"))
        b = _create_and_return(repository, _make_task("B"))
        c = _create_and_return(repository, _make_task("C"))

        reordered = repository.reorder_tasks_for_date(
            a.due_date,
            [c.id, a.id, b.id],
        )

        assert [task.id for task in reordered] == [c.id, a.id, b.id]
        sort_orders = [
            repository.get_task(task_id).sort_order
            for task_id in [c.id, a.id, b.id]
        ]
        assert sort_orders == [0, 1, 2]
        assert [
            task.id
            for task in repository.list_widget_tasks(date(2026, 8, 1))
        ] == [c.id, a.id, b.id]

    def test_first_dragged_task_becomes_urgent_atomically(self, repository):
        first = _create_and_return(repository, _make_task("First"))
        dragged = _create_and_return(repository, _make_task("Dragged", priority=Priority.LOW))

        repository.reorder_tasks_for_date(
            first.due_date,
            [dragged.id, first.id],
            make_first_urgent=True,
        )

        assert repository.get_task(dragged.id).priority is Priority.URGENT
        assert repository.get_task(dragged.id).sort_order == 0
        assert repository.get_task(first.id).priority is Priority.NORMAL

    @pytest.mark.parametrize(
        "ordered_ids",
        [[], [9999]],
    )
    def test_rejects_empty_or_missing_ids(self, repository, ordered_ids):
        with pytest.raises(ValueError):
            repository.reorder_tasks_for_date(date(2026, 8, 1), ordered_ids)

    def test_rejects_duplicate_ids_without_writes(self, repository):
        task = _create_and_return(repository, _make_task("A"))

        with pytest.raises(ValueError):
            repository.reorder_tasks_for_date(task.due_date, [task.id, task.id])

        assert repository.get_task(task.id).sort_order is None

    def test_rejects_incomplete_list_without_writes(self, repository):
        a = _create_and_return(repository, _make_task("A"))
        _create_and_return(repository, _make_task("B"))

        with pytest.raises(ValueError):
            repository.reorder_tasks_for_date(a.due_date, [a.id])

        assert repository.get_task(a.id).sort_order is None

    def test_rejects_cross_date_task_without_writes(self, repository):
        a = _create_and_return(repository, _make_task("A"))
        other = _create_and_return(
            repository,
            _make_task("Other date", due_date=date(2026, 8, 2)),
        )

        with pytest.raises(ValueError):
            repository.reorder_tasks_for_date(a.due_date, [a.id, other.id])

        assert repository.get_task(a.id).sort_order is None
        assert repository.get_task(other.id).sort_order is None

    def test_rejects_completed_task(self, repository):
        task = _create_and_return(repository, _make_task("Completed"))
        repository.complete_task(task.id)

        with pytest.raises(ValueError):
            repository.reorder_tasks_for_date(task.due_date, [task.id])


def test_new_tasks_keep_automatic_priority_order(repository):
    normal = _create_and_return(repository, _make_task("Normal"))
    urgent = _create_and_return(
        repository,
        _make_task("Urgent", priority=Priority.URGENT),
    )

    assert normal.sort_order is None
    assert urgent.sort_order is None
    assert [task.id for task in repository.list_widget_tasks(date(2026, 8, 1))] == [
        urgent.id,
        normal.id,
    ]


def test_due_date_change_clears_manual_order(repository):
    a = _create_and_return(repository, _make_task("A"))
    b = _create_and_return(repository, _make_task("B"))
    repository.reorder_tasks_for_date(a.due_date, [b.id, a.id])

    moved = repository.update_task(
        b.model_copy(update={"due_date": date(2026, 8, 2)})
    )

    assert moved.sort_order is None


def test_duplicate_does_not_copy_manual_order(repository):
    original = _create_and_return(repository, _make_task("Original"))
    repository.reorder_tasks_for_date(original.due_date, [original.id])

    duplicate = repository.duplicate_task(original.id)

    assert duplicate is not None
    assert duplicate.sort_order is None


class TestMoveTaskToDate:
    def test_moves_task_and_persists_target_order(self, repository):
        moving = _create_and_return(
            repository,
            _make_task("Moving", due_date=date(2026, 8, 1), priority=Priority.LOW),
        )
        target = _create_and_return(
            repository,
            _make_task("Target", due_date=date(2026, 8, 2)),
        )

        ordered = repository.move_task_to_date(
            moving.id,
            target.due_date,
            [moving.id, target.id],
            make_first_urgent=True,
        )

        assert [task.id for task in ordered] == [moving.id, target.id]
        moved = repository.get_task(moving.id)
        assert moved.due_date == target.due_date
        assert moved.priority is Priority.URGENT
        assert moved.sort_order == 0
        assert repository.get_task(target.id).sort_order == 1

    def test_invalid_target_order_rolls_back_date(self, repository):
        moving = _create_and_return(
            repository,
            _make_task("Moving", due_date=date(2026, 8, 1)),
        )
        target = _create_and_return(
            repository,
            _make_task("Target", due_date=date(2026, 8, 2)),
        )

        with pytest.raises(ValueError, match="exactly match"):
            repository.move_task_to_date(
                moving.id,
                target.due_date,
                [moving.id],
            )

        assert repository.get_task(moving.id).due_date == date(2026, 8, 1)
        assert repository.get_task(target.id).sort_order is None

    def test_date_move_clears_existing_notifications(self, repository):
        moving = _create_and_return(
            repository,
            _make_task("Moving", due_date=date(2026, 8, 1)),
        )
        repository.record_notification(moving.id, "at_due_time", REPOSITORY_NOW)

        repository.move_task_to_date(
            moving.id,
            date(2026, 8, 2),
            [moving.id],
        )

        assert not repository.has_notification(moving.id, "at_due_time")

    def test_rejects_completed_task_without_changes(self, repository):
        moving = _create_and_return(repository, _make_task("Completed"))
        repository.complete_task(moving.id)

        with pytest.raises(ValueError, match="pending"):
            repository.move_task_to_date(
                moving.id,
                date(2026, 8, 2),
                [moving.id],
            )

        assert repository.get_task(moving.id).due_date == moving.due_date
