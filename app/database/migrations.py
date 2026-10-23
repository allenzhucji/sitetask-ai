from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json

from app.database.connection import Database


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    statements: tuple[str, ...]


MIGRATIONS = (
    Migration(
        version=1,
        statements=(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                due_date TEXT NOT NULL,
                due_time TEXT,
                category TEXT NOT NULL DEFAULT 'Other',
                priority TEXT NOT NULL DEFAULT 'normal',
                status TEXT NOT NULL DEFAULT 'pending',
                source TEXT NOT NULL DEFAULT 'manual',
                source_reference TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_tasks_due_date ON tasks(due_date)",
            "CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)",
            "CREATE INDEX IF NOT EXISTS idx_tasks_due_status ON tasks(due_date, status)",
            """
            CREATE TABLE IF NOT EXISTS notification_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                notification_type TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                UNIQUE(task_id, notification_type),
                FOREIGN KEY(task_id) REFERENCES tasks(id)
            )
            """,
        ),
    ),
    Migration(
        version=2,
        statements=(
            "ALTER TABLE tasks ADD COLUMN sort_order INTEGER",
            """
            CREATE INDEX IF NOT EXISTS idx_tasks_due_status_sort
            ON tasks(due_date, status, sort_order)
            """,
        ),
    ),
    Migration(
        version=3,
        statements=(
            "ALTER TABLE tasks ADD COLUMN no_due INTEGER NOT NULL DEFAULT 0",
            """
            CREATE INDEX IF NOT EXISTS idx_tasks_no_due_status_sort
            ON tasks(no_due, status, sort_order)
            """,
        ),
    ),
    Migration(
        version=4,
        statements=(
            """CREATE TABLE local_queue_commands (
                command_id TEXT PRIMARY KEY, payload_sha256 TEXT NOT NULL,
                result_json TEXT NOT NULL, processed_at TEXT NOT NULL)""",
            """CREATE TABLE local_queue_sources (
                source_reference TEXT PRIMARY KEY, task_id INTEGER,
                last_revision TEXT, deleted INTEGER NOT NULL DEFAULT 0)""",
            """INSERT INTO local_queue_sources (source_reference, task_id)
                SELECT source_reference, MIN(id) FROM tasks
                WHERE source_reference LIKE 'PROJECT:%'
                GROUP BY source_reference HAVING COUNT(*) = 1""",
            """CREATE TRIGGER local_queue_deleted AFTER DELETE ON tasks
                WHEN OLD.source_reference LIKE 'PROJECT:%'
                BEGIN
                    INSERT INTO local_queue_sources (source_reference, task_id, deleted)
                    VALUES (OLD.source_reference, OLD.id, 1)
                    ON CONFLICT(source_reference) DO UPDATE SET deleted=1;
                END""",
        ),
    ),
)


def apply_migrations(database: Database) -> tuple[int, ...]:
    applied_now: list[int] = []
    with database.transaction() as connection:
        # SQLite DDL must be inside an explicit transaction for interrupted upgrades.
        connection.execute('BEGIN IMMEDIATE')
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        applied_versions = {
            row["version"]
            for row in connection.execute("SELECT version FROM schema_migrations")
        }

        for migration in MIGRATIONS:
            if migration.version in applied_versions:
                continue
            for statement in migration.statements:
                connection.execute(statement)
            if migration.version == 4:
                # Baseline existing linked tasks without changing any task field.
                for row in connection.execute('''SELECT tasks.* FROM tasks JOIN local_queue_sources s
                        ON tasks.id=s.task_id''').fetchall():
                    payload = json.dumps(dict(row), ensure_ascii=False, sort_keys=True,
                                         separators=(',', ':'), allow_nan=False).encode('utf-8')
                    connection.execute('UPDATE local_queue_sources SET last_revision=? WHERE task_id=?',
                                       (hashlib.sha256(payload).hexdigest(), row['id']))
            connection.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (migration.version, datetime.now().astimezone().isoformat()),
            )
            applied_now.append(migration.version)

    return tuple(applied_now)
