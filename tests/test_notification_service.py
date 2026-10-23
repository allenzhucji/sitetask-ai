from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from app.database.connection import Database
from app.database.task_repository import TaskRepository
from app.models.settings import NotificationSettings
from app.models.task import Category, Task, TaskStatus
from app.services.notification_service import (
    NotificationService,
    NotificationType,
)


ZONE = ZoneInfo("Indian/Mauritius")


class MutableClock:
    def __init__(self, now: datetime):
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class FakeSender:
    def __init__(self, *, fails: bool = False):
        self.fails = fails
        self.sent: list[tuple[str, str]] = []

    def send(self, title: str, message: str) -> None:
        if self.fails:
            raise RuntimeError("toast unavailable")
        self.sent.append((title, message))


def make_task(
    due_date: date,
    due_time: time | None,
    *,
    title: str = "Submit monthly report",
) -> Task:
    created_at = datetime(2026, 7, 17, 8, 0, tzinfo=ZONE)
    return Task(
        title=title,
        due_date=due_date,
        due_time=due_time,
        category=Category.REPORT,
        created_at=created_at,
        updated_at=created_at,
    )


def make_service(tmp_path, now: datetime, *, sender=None):
    clock = MutableClock(now)
    repository = TaskRepository(
        Database(tmp_path / "data" / "sitetask.db"),
        clock=clock,
    )
    fake_sender = sender or FakeSender()
    service = NotificationService(repository, sender=fake_sender, clock=clock)
    return service, repository, clock, fake_sender


def test_one_hour_and_due_notifications_are_each_sent_once(tmp_path):
    service, repository, clock, sender = make_service(
        tmp_path,
        datetime(2026, 7, 17, 16, 0, tzinfo=ZONE),
    )
    task = repository.create_task(make_task(date(2026, 7, 17), time(17, 0)))
    settings = NotificationSettings()

    first = service.check_due_tasks(settings)
    duplicate = service.check_due_tasks(settings)
    clock.now = datetime(2026, 7, 17, 17, 0, tzinfo=ZONE)
    at_due = service.check_due_tasks(settings)
    due_duplicate = service.check_due_tasks(settings)

    assert first.sent == 1
    assert duplicate.sent == 0
    assert at_due.sent == 1
    assert due_duplicate.sent == 0
    assert [title for title, _ in sender.sent] == [
        "Task due in 1 hour",
        "Task due now",
    ]
    assert "Submit monthly report" in sender.sent[0][1]
    assert repository.has_notification(task.id, NotificationType.ONE_HOUR_BEFORE)
    assert repository.has_notification(task.id, NotificationType.AT_DUE_TIME)


def test_future_task_becomes_notification_eligible_independent_of_widget(tmp_path):
    service, repository, clock, sender = make_service(
        tmp_path,
        datetime(2026, 7, 17, 9, 0, tzinfo=ZONE),
    )
    task = repository.create_task(make_task(date(2026, 10, 1), time(17, 0)))

    assert task not in repository.list_widget_tasks(date(2026, 7, 17))
    assert service.check_due_tasks(NotificationSettings()).sent == 0
    clock.now = datetime(2026, 10, 1, 16, 0, tzinfo=ZONE)

    result = service.check_due_tasks(NotificationSettings())

    assert result.sent == 1
    assert len(sender.sent) == 1


def test_completed_cancelled_and_deleted_tasks_do_not_notify(tmp_path):
    service, repository, _, sender = make_service(
        tmp_path,
        datetime(2026, 7, 17, 16, 0, tzinfo=ZONE),
    )
    completed = repository.create_task(
        make_task(date(2026, 7, 17), time(17, 0), title="Completed")
    )
    cancelled = repository.create_task(
        make_task(date(2026, 7, 17), time(17, 0), title="Cancelled")
    )
    deleted = repository.create_task(
        make_task(date(2026, 7, 17), time(17, 0), title="Deleted")
    )
    repository.complete_task(completed.id)
    repository.update_task(
        cancelled.model_copy(update={"status": TaskStatus.CANCELLED})
    )
    repository.record_notification(
        deleted.id,
        NotificationType.ONE_HOUR_BEFORE,
        datetime(2026, 7, 17, 16, 0, tzinfo=ZONE),
    )
    assert repository.delete_task(deleted.id)

    result = service.check_due_tasks(NotificationSettings())

    assert result.sent == 0
    assert sender.sent == []
    assert repository.get_task(deleted.id) is None


def test_disabled_paused_and_all_day_tasks_do_not_notify(tmp_path):
    service, repository, _, sender = make_service(
        tmp_path,
        datetime(2026, 7, 17, 16, 0, tzinfo=ZONE),
    )
    repository.create_task(make_task(date(2026, 7, 17), time(17, 0)))
    repository.create_task(
        make_task(date(2026, 7, 17), None, title="All-day task")
    )

    assert service.check_due_tasks(
        NotificationSettings(enabled=False)
    ).sent == 0
    assert service.check_due_tasks(NotificationSettings(), paused=True).sent == 0
    assert sender.sent == []


def test_sender_failure_is_retryable_and_not_logged(tmp_path):
    sender = FakeSender(fails=True)
    service, repository, _, _ = make_service(
        tmp_path,
        datetime(2026, 7, 17, 16, 0, tzinfo=ZONE),
        sender=sender,
    )
    task = repository.create_task(make_task(date(2026, 7, 17), time(17, 0)))

    failed = service.check_due_tasks(NotificationSettings())
    assert failed.failed == 1
    assert not repository.has_notification(
        task.id,
        NotificationType.ONE_HOUR_BEFORE,
    )

    sender.fails = False
    retried = service.check_due_tasks(NotificationSettings())

    assert retried.sent == 1


def test_old_overdue_task_does_not_emit_late_due_notification(tmp_path):
    service, repository, _, sender = make_service(
        tmp_path,
        datetime(2026, 7, 17, 16, 0, tzinfo=ZONE),
    )
    repository.create_task(make_task(date(2026, 7, 16), time(9, 0)))

    result = service.check_due_tasks(NotificationSettings())

    assert result.sent == 0
    assert sender.sent == []


def test_changing_due_schedule_clears_previous_notification_log(tmp_path):
    _, repository, _, _ = make_service(
        tmp_path,
        datetime(2026, 7, 17, 16, 0, tzinfo=ZONE),
    )
    task = repository.create_task(make_task(date(2026, 7, 17), time(17, 0)))
    repository.record_notification(
        task.id,
        NotificationType.ONE_HOUR_BEFORE,
        datetime(2026, 7, 17, 16, 0, tzinfo=ZONE),
    )

    updated = repository.update_task(
        task.model_copy(update={"due_date": date(2026, 8, 15)})
    )

    assert updated.due_date == date(2026, 8, 15)
    assert not repository.has_notification(
        task.id,
        NotificationType.ONE_HOUR_BEFORE,
    )
