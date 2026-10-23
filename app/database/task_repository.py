from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import date, datetime, timedelta

from app.database.connection import Database
from app.database.migrations import apply_migrations
from app.models.task import Priority, Task, TaskStatus, current_local_datetime


class TaskRepository:
    def __init__(
        self,
        database: Database,
        clock: Callable[[], datetime] = current_local_datetime,
    ) -> None:
        self.database = database
        self.clock = clock
        apply_migrations(database)

    def create_task(self, task: Task) -> Task:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                """
                INSERT INTO tasks (
                    title, description, due_date, due_time, category, priority,
                    status, source, source_reference, no_due, sort_order,
                    created_at, updated_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._task_values(task),
            )
            task_id = cursor.lastrowid

        created = self.get_task(task_id)
        if created is None:  # Defensive: SQLite returned an id but no row.
            raise RuntimeError("Created task could not be loaded")
        return created

    def get_task(self, task_id: int | None) -> Task | None:
        if task_id is None:
            return None
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
        return self._row_to_task(row)

    def update_task(self, task: Task) -> Task | None:
        if task.id is None:
            raise ValueError("Cannot update a task without an id")

        original = self.get_task(task.id)
        if original is None:
            return None
        update_values: dict[str, object] = {"updated_at": self.clock()}
        if original.due_date != task.due_date or original.no_due != task.no_due:
            update_values["sort_order"] = None
        if task.no_due:
            update_values["due_time"] = None
        updated_task = task.model_copy(update=update_values)
        with self.database.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE tasks
                SET title = ?, description = ?, due_date = ?, due_time = ?,
                    category = ?, priority = ?, status = ?, source = ?,
                    source_reference = ?, no_due = ?, sort_order = ?,
                    updated_at = ?, completed_at = ?
                WHERE id = ?
                """,
                (
                    updated_task.title,
                    updated_task.description,
                    updated_task.due_date.isoformat(),
                    self._serialize_time(updated_task),
                    updated_task.category,
                    updated_task.priority,
                    updated_task.status,
                    updated_task.source,
                    updated_task.source_reference,
                    int(updated_task.no_due),
                    updated_task.sort_order,
                    updated_task.updated_at.isoformat(),
                    self._serialize_datetime(updated_task.completed_at),
                    updated_task.id,
                ),
            )
            if (
                original.due_date != updated_task.due_date
                or original.due_time != updated_task.due_time
                or original.no_due != updated_task.no_due
            ):
                connection.execute(
                    "DELETE FROM notification_log WHERE task_id = ?",
                    (updated_task.id,),
                )
        if cursor.rowcount == 0:
            return None
        return self.get_task(updated_task.id)

    def delete_task(self, task_id: int) -> bool:
        with self.database.transaction() as connection:
            connection.execute(
                "DELETE FROM notification_log WHERE task_id = ?",
                (task_id,),
            )
            cursor = connection.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        return cursor.rowcount > 0

    def complete_task(self, task_id: int) -> Task | None:
        completed_at = self.clock()
        with self.database.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE tasks
                SET status = ?, completed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    TaskStatus.COMPLETED,
                    completed_at.isoformat(),
                    completed_at.isoformat(),
                    task_id,
                ),
            )
        if cursor.rowcount == 0:
            return None
        return self.get_task(task_id)

    def restore_task(self, task_id: int) -> Task | None:
        updated_at = self.clock()
        with self.database.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE tasks
                SET status = ?, completed_at = NULL, updated_at = ?
                WHERE id = ?
                """,
                (TaskStatus.PENDING, updated_at.isoformat(), task_id),
            )
        if cursor.rowcount == 0:
            return None
        return self.get_task(task_id)

    def duplicate_task(self, task_id: int) -> Task | None:
        original = self.get_task(task_id)
        if original is None:
            return None

        now = self.clock()
        duplicate = original.model_copy(
            update={
                "id": None,
                "title": f"{original.title} (Copy)",
                "status": TaskStatus.PENDING,
                "sort_order": None,
                "created_at": now,
                "updated_at": now,
                "completed_at": None,
            }
        )
        return self.create_task(duplicate)

    def list_widget_tasks(self, today: date, days_ahead: int = 3) -> list[Task]:
        visible_end_date = self._visible_end_date(today, days_ahead)
        return self._fetch_tasks(
            """
            SELECT *
            FROM tasks
            WHERE status = ?
              AND (
                no_due = 1
                OR due_date < ?
                OR (no_due = 0 AND due_date BETWEEN ? AND ?)
              )
            ORDER BY
              CASE WHEN no_due = 1 OR due_date < ? THEN 0 ELSE 1 END,
              CASE WHEN sort_order IS NULL THEN 1 ELSE 0 END,
              sort_order ASC,
              CASE priority
                WHEN 'urgent' THEN 0
                WHEN 'high' THEN 1
                WHEN 'normal' THEN 2
                WHEN 'low' THEN 3
                ELSE 4
              END,
              CASE WHEN due_time IS NULL THEN 1 ELSE 0 END,
              due_time ASC,
              due_date ASC,
              created_at ASC
            """,
            (
                TaskStatus.PENDING,
                today.isoformat(),
                today.isoformat(),
                visible_end_date.isoformat(),
                today.isoformat(),
            ),
        )

    def list_upcoming_tasks(self, today: date) -> list[Task]:
        return self._fetch_tasks(
            """
            SELECT * FROM tasks
            WHERE status = ? AND no_due = 0 AND due_date >= ?
            ORDER BY due_date ASC,
                     CASE WHEN due_time IS NULL THEN 1 ELSE 0 END,
                     due_time ASC,
                     created_at ASC
            """,
            (TaskStatus.PENDING, today.isoformat()),
        )

    def list_next_three_days_tasks(
        self,
        today: date,
        days_ahead: int = 3,
    ) -> list[Task]:
        visible_end_date = self._visible_end_date(today, days_ahead)
        return self._fetch_tasks(
            """
            SELECT * FROM tasks
            WHERE status = ? AND no_due = 0 AND due_date BETWEEN ? AND ?
            ORDER BY due_date ASC,
                     CASE WHEN due_time IS NULL THEN 1 ELSE 0 END,
                     due_time ASC,
                     created_at ASC
            """,
            (TaskStatus.PENDING, today.isoformat(), visible_end_date.isoformat()),
        )

    def list_later_tasks(self, today: date, days_ahead: int = 3) -> list[Task]:
        visible_end_date = self._visible_end_date(today, days_ahead)
        return self._fetch_tasks(
            """
            SELECT * FROM tasks
            WHERE status = ? AND no_due = 0 AND due_date > ?
            ORDER BY due_date ASC,
                     CASE WHEN due_time IS NULL THEN 1 ELSE 0 END,
                     due_time ASC
            """,
            (TaskStatus.PENDING, visible_end_date.isoformat()),
        )

    def list_overdue_tasks(self, today: date) -> list[Task]:
        return self._fetch_tasks(
            """
            SELECT * FROM tasks
            WHERE status = ? AND no_due = 0 AND due_date < ?
            ORDER BY due_date ASC,
                     CASE WHEN due_time IS NULL THEN 1 ELSE 0 END,
                     due_time ASC
            """,
            (TaskStatus.PENDING, today.isoformat()),
        )

    def list_no_due_tasks(self, today: date) -> list[Task]:
        """Return explicit long-term tasks and pending tasks past their date."""
        return self._fetch_tasks(
            """
            SELECT * FROM tasks
            WHERE status = ? AND (no_due = 1 OR due_date < ?)
            ORDER BY
              CASE WHEN sort_order IS NULL THEN 1 ELSE 0 END,
              sort_order ASC,
              CASE priority
                WHEN 'urgent' THEN 0
                WHEN 'high' THEN 1
                WHEN 'normal' THEN 2
                WHEN 'low' THEN 3
                ELSE 4
              END,
              created_at ASC
            """,
            (TaskStatus.PENDING, today.isoformat()),
        )

    def list_completed_tasks(self) -> list[Task]:
        return self._fetch_tasks(
            """
            SELECT * FROM tasks
            WHERE status = ?
            ORDER BY completed_at DESC, due_date DESC, created_at DESC
            """,
            (TaskStatus.COMPLETED,),
        )

    def list_all_tasks(self) -> list[Task]:
        return self._fetch_tasks(
            """
            SELECT * FROM tasks
            ORDER BY no_due DESC,
                     due_date ASC,
                     CASE WHEN due_time IS NULL THEN 1 ELSE 0 END,
                     due_time ASC,
                     created_at ASC
            """
        )

    def count_widget_tasks(self, today: date, days_ahead: int = 3) -> int:
        visible_end_date = self._visible_end_date(today, days_ahead)
        return self._count_tasks(
            """
            SELECT COUNT(*) FROM tasks
            WHERE status = ?
              AND (
                no_due = 1
                OR due_date < ?
                OR (no_due = 0 AND due_date BETWEEN ? AND ?)
              )
            """,
            (
                TaskStatus.PENDING,
                today.isoformat(),
                today.isoformat(),
                visible_end_date.isoformat(),
            ),
        )

    def count_later_tasks(self, today: date, days_ahead: int = 3) -> int:
        visible_end_date = self._visible_end_date(today, days_ahead)
        return self._count_tasks(
            "SELECT COUNT(*) FROM tasks WHERE status = ? AND no_due = 0 AND due_date > ?",
            (TaskStatus.PENDING, visible_end_date.isoformat()),
        )

    def search_tasks(self, query: str) -> list[Task]:
        term = query.strip()
        if not term:
            return self.list_all_tasks()

        pattern = f"%{self._escape_like(term)}%"
        return self._fetch_tasks(
            """
            SELECT * FROM tasks
            WHERE title LIKE ? ESCAPE '\\'
               OR COALESCE(description, '') LIKE ? ESCAPE '\\'
               OR COALESCE(source_reference, '') LIKE ? ESCAPE '\\'
            ORDER BY no_due DESC,
                     due_date ASC,
                     CASE WHEN due_time IS NULL THEN 1 ELSE 0 END,
                     due_time ASC,
                     created_at ASC
            """,
            (pattern, pattern, pattern),
        )

    def list_notification_candidates(
        self,
        start_date: date,
        end_date: date,
    ) -> list[Task]:
        return self._fetch_tasks(
            """
            SELECT * FROM tasks
            WHERE status = ?
              AND no_due = 0
              AND due_time IS NOT NULL
              AND due_date BETWEEN ? AND ?
            ORDER BY due_date ASC, due_time ASC, created_at ASC
            """,
            (
                TaskStatus.PENDING,
                start_date.isoformat(),
                end_date.isoformat(),
            ),
        )

    def has_notification(self, task_id: int, notification_type: str) -> bool:
        with self.database.transaction() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM notification_log
                WHERE task_id = ? AND notification_type = ?
                """,
                (task_id, notification_type),
            ).fetchone()
        return row is not None

    def record_notification(
        self,
        task_id: int,
        notification_type: str,
        sent_at: datetime,
    ) -> bool:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO notification_log (
                    task_id, notification_type, sent_at
                ) VALUES (?, ?, ?)
                """,
                (task_id, notification_type, sent_at.isoformat()),
            )
        return cursor.rowcount > 0

    def _fetch_tasks(
        self,
        query: str,
        parameters: tuple[object, ...] = (),
    ) -> list[Task]:
        with self.database.transaction() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [Task.model_validate(dict(row)) for row in rows]

    def _count_tasks(self, query: str, parameters: tuple[object, ...]) -> int:
        with self.database.transaction() as connection:
            row = connection.execute(query, parameters).fetchone()
        return int(row[0])

    @staticmethod
    def _visible_end_date(today: date, days_ahead: int) -> date:
        if days_ahead < 1:
            raise ValueError("days_ahead must be at least 1")
        return today + timedelta(days=days_ahead - 1)

    @staticmethod
    def _escape_like(value: str) -> str:
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    @staticmethod
    def _serialize_time(task: Task) -> str | None:
        if task.due_time is None:
            return None
        return task.due_time.isoformat(timespec="minutes")

    @staticmethod
    def _serialize_datetime(value: datetime | None) -> str | None:
        return value.isoformat() if value is not None else None

    def reorder_tasks_for_date(
        self,
        due_date: date,
        ordered_task_ids: list[int],
        *,
        make_first_urgent: bool = False,
    ) -> list[Task]:
        """Persist the complete order of pending tasks for one due date."""
        if not ordered_task_ids:
            raise ValueError("ordered_task_ids must not be empty")
        with self.database.transaction() as connection:
            rows = connection.execute(
                """
                SELECT id FROM tasks
                WHERE due_date = ? AND no_due = 0 AND status = ?
                """,
                (due_date.isoformat(), TaskStatus.PENDING),
            ).fetchall()
            existing_ids = {int(row["id"]) for row in rows}
            supplied_ids = set(ordered_task_ids)
            if (
                len(supplied_ids) != len(ordered_task_ids)
                or supplied_ids != existing_ids
            ):
                raise ValueError(
                    "ordered_task_ids must exactly match pending tasks for due_date"
                )

            now = self.clock()
            timestamp = now.isoformat()
            for index, task_id in enumerate(ordered_task_ids):
                connection.execute(
                    "UPDATE tasks SET sort_order = ?, updated_at = ? WHERE id = ?",
                    (index, timestamp, task_id),
                )
            if make_first_urgent:
                connection.execute(
                    "UPDATE tasks SET priority = ?, updated_at = ? WHERE id = ?",
                    (Priority.URGENT, timestamp, ordered_task_ids[0]),
                )

        tasks = [self.get_task(task_id) for task_id in ordered_task_ids]
        if any(task is None for task in tasks):
            raise RuntimeError("Reordered task could not be loaded")
        return [task for task in tasks if task is not None]

    def move_task_to_date(
        self,
        task_id: int,
        target_due_date: date | None,
        target_ordered_task_ids: list[int],
        *,
        make_first_urgent: bool = False,
        today: date | None = None,
    ) -> list[Task]:
        """Move a pending task into a dated or NO DUE group atomically."""
        if not target_ordered_task_ids:
            raise ValueError("target_ordered_task_ids must not be empty")
        if target_due_date is None and today is None:
            raise ValueError("today is required when moving a task to NO DUE")
        with self.database.transaction() as connection:
            moving_task = connection.execute(
                "SELECT due_date, no_due, status FROM tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
            if moving_task is None or moving_task["status"] != TaskStatus.PENDING:
                raise ValueError("Only an existing pending task can be moved")

            source_due_date = date.fromisoformat(str(moving_task["due_date"]))
            source_no_due = bool(moving_task["no_due"])
            if target_due_date is None:
                assert today is not None
                target_rows = connection.execute(
                    """
                    SELECT id FROM tasks
                    WHERE status = ? AND (no_due = 1 OR due_date < ?)
                    """,
                    (TaskStatus.PENDING, today.isoformat()),
                ).fetchall()
                source_in_target = source_no_due or source_due_date < today
            else:
                target_rows = connection.execute(
                    """
                    SELECT id FROM tasks
                    WHERE status = ? AND no_due = 0 AND due_date = ?
                    """,
                    (TaskStatus.PENDING, target_due_date.isoformat()),
                ).fetchall()
                source_in_target = (
                    not source_no_due and source_due_date == target_due_date
                )
            expected_ids = {int(row["id"]) for row in target_rows}
            if not source_in_target:
                expected_ids.add(task_id)

            supplied_ids = set(target_ordered_task_ids)
            if (
                len(supplied_ids) != len(target_ordered_task_ids)
                or supplied_ids != expected_ids
                or task_id not in supplied_ids
            ):
                raise ValueError(
                    "target_ordered_task_ids must exactly match target pending tasks"
                )

            timestamp = self.clock().isoformat()
            if target_due_date is None:
                connection.execute(
                    """
                    UPDATE tasks
                    SET no_due = 1, due_time = NULL, sort_order = NULL,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (timestamp, task_id),
                )
                connection.execute(
                    "DELETE FROM notification_log WHERE task_id = ?",
                    (task_id,),
                )
            elif source_no_due or source_due_date != target_due_date:
                connection.execute(
                    """
                    UPDATE tasks SET due_date = ?, no_due = 0,
                        sort_order = NULL, updated_at = ?
                    WHERE id = ?
                    """,
                    (target_due_date.isoformat(), timestamp, task_id),
                )
                connection.execute(
                    "DELETE FROM notification_log WHERE task_id = ?",
                    (task_id,),
                )

            for index, ordered_task_id in enumerate(target_ordered_task_ids):
                connection.execute(
                    "UPDATE tasks SET sort_order = ?, updated_at = ? WHERE id = ?",
                    (index, timestamp, ordered_task_id),
                )
            if make_first_urgent:
                connection.execute(
                    "UPDATE tasks SET priority = ?, updated_at = ? WHERE id = ?",
                    (Priority.URGENT, timestamp, target_ordered_task_ids[0]),
                )

        tasks = [self.get_task(item_id) for item_id in target_ordered_task_ids]
        if any(task is None for task in tasks):
            raise RuntimeError("Moved task could not be loaded")
        return [task for task in tasks if task is not None]

    @classmethod
    def _task_values(cls, task: Task) -> tuple[object, ...]:
        return (
            task.title,
            task.description,
            task.due_date.isoformat(),
            cls._serialize_time(task),
            task.category,
            task.priority,
            task.status,
            task.source,
            task.source_reference,
            int(task.no_due),
            task.sort_order,
            task.created_at.isoformat(),
            task.updated_at.isoformat(),
            cls._serialize_datetime(task.completed_at),
        )

    @staticmethod
    def _row_to_task(row: sqlite3.Row | None) -> Task | None:
        if row is None:
            return None
        return Task.model_validate(dict(row))
