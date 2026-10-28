from __future__ import annotations

import sqlite3
from datetime import date, datetime

import pytest
from pydantic import ValidationError

from app.database.connection import Database
from app.database.migrations import apply_migrations
from app.models.task import Category, Priority, Task, TaskSource, TaskStatus
from app.utils.paths import AppPaths


FIXED_NOW = datetime.fromisoformat("2026-07-17T08:30:00+04:00")


def test_task_model_normalizes_title_and_validates_enums():
    task = Task(
        title="  Submit IRF-023 response  ",
        due_date=date(2026, 8, 15),
        category=Category.IRF,
        priority=Priority.HIGH,
        status=TaskStatus.PENDING,
        source=TaskSource.MANUAL,
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
    )

    assert task.title == "Submit IRF-023 response"
    assert task.due_date == date(2026, 8, 15)
    assert task.category is Category.IRF

    with pytest.raises(ValidationError):
        Task(title="   ", due_date=date(2026, 8, 15))


def test_first_migration_creates_database_schema(tmp_path):
    paths = AppPaths(tmp_path)
    database = Database(paths.database_file)

    assert apply_migrations(database) == (1, 2, 3, 4, 5, 6)

    with database.transaction() as connection:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = ?",
                ("table",),
            )
        }
        indexes = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = ?",
                ("index",),
            )
        }
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(tasks)")
        }

    assert paths.database_file.exists()
    assert {"tasks", "notification_log", "schema_migrations_v5"} <= tables
    assert {
        "idx_tasks_due_date",
        "idx_tasks_status",
        "idx_tasks_due_status",
        "idx_tasks_due_status_sort",
        "idx_tasks_no_due_status_sort",
    } <= indexes
    assert "sort_order" in columns
    assert "no_due" in columns


def test_migrations_can_run_repeatedly(tmp_path):
    database = Database(tmp_path / "data" / "sitetask.db")

    assert apply_migrations(database) == (1, 2, 3, 4, 5, 6)
    assert apply_migrations(database) == ()

    with database.transaction() as connection:
        migration_count = connection.execute(
            "SELECT COUNT(*) FROM schema_migrations_v5"
        ).fetchone()[0]

    assert migration_count == 6


def test_transaction_closes_connection(tmp_path):
    database = Database(tmp_path / "sitetask.db")

    with database.transaction() as connection:
        assert connection.execute("SELECT 1").fetchone()[0] == 1

    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")

