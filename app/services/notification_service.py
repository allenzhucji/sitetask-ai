from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol

from app.database.task_repository import TaskRepository
from app.models.settings import NotificationSettings
from app.models.task import Task, current_local_datetime


class NotificationType(StrEnum):
    ONE_HOUR_BEFORE = "one_hour_before"
    AT_DUE_TIME = "at_due_time"


class NotificationSender(Protocol):
    def send(self, title: str, message: str) -> None: ...


class WindowsNotificationSender:
    def send(self, title: str, message: str) -> None:
        from winotify import Notification

        Notification(
            app_id="SiteTask AI",
            title=title,
            msg=message,
        ).show()


@dataclass(frozen=True, slots=True)
class NotificationCheckResult:
    sent: int = 0
    skipped: int = 0
    failed: int = 0


class NotificationService:
    DUE_GRACE_PERIOD = timedelta(hours=1)

    def __init__(
        self,
        repository: TaskRepository,
        *,
        sender: NotificationSender | None = None,
        clock: Callable[[], datetime] = current_local_datetime,
    ) -> None:
        self.repository = repository
        self.sender = sender or WindowsNotificationSender()
        self.clock = clock

    def check_due_tasks(
        self,
        settings: NotificationSettings,
        *,
        paused: bool = False,
    ) -> NotificationCheckResult:
        if paused or not settings.enabled:
            return NotificationCheckResult()

        now = self.clock()
        if now.tzinfo is None:
            now = now.astimezone()
        candidates = self.repository.list_notification_candidates(
            (now - self.DUE_GRACE_PERIOD).date(),
            (now + timedelta(hours=1)).date(),
        )

        sent = skipped = failed = 0
        for task in candidates:
            notification_type = self._eligible_type(task, now, settings)
            if notification_type is None or task.id is None:
                skipped += 1
                continue
            if self.repository.has_notification(task.id, notification_type):
                skipped += 1
                continue

            title = (
                "Task due in 1 hour"
                if notification_type is NotificationType.ONE_HOUR_BEFORE
                else "Task due now"
            )
            try:
                self.sender.send(title, self._message(task))
            except Exception:
                failed += 1
                continue
            if self.repository.record_notification(task.id, notification_type, now):
                sent += 1
            else:
                skipped += 1
        return NotificationCheckResult(sent=sent, skipped=skipped, failed=failed)

    def _eligible_type(
        self,
        task: Task,
        now: datetime,
        settings: NotificationSettings,
    ) -> NotificationType | None:
        if task.due_time is None:
            return None
        due_at = datetime.combine(task.due_date, task.due_time, tzinfo=now.tzinfo)
        if (
            settings.one_hour_before
            and due_at - timedelta(hours=1) <= now < due_at
        ):
            return NotificationType.ONE_HOUR_BEFORE
        if (
            settings.at_due_time
            and due_at <= now < due_at + self.DUE_GRACE_PERIOD
        ):
            return NotificationType.AT_DUE_TIME
        return None

    @staticmethod
    def _message(task: Task) -> str:
        due_time = task.due_time.strftime("%H:%M") if task.due_time else "All day"
        return f"{task.title}\n{task.due_date.isoformat()} · {due_time}"
