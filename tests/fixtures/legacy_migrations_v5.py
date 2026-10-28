from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import uuid

from app.database.connection import Database


SCHEMA_VERSION = 5
LEGACY_LEDGER = "schema_migrations"
# Migration 5 renames the ledger. Builds that only know migrations 1-4 then see
# an empty legacy ledger, re-run migration 2 (ALTER ... ADD sort_order), fail
# with "duplicate column name" and roll back, so they can never open this DB.
LEDGER = "schema_migrations_v5"
RETENTION_DAYS = 30
SQLITE_UTC_NOW = "strftime('%Y-%m-%dT%H:%M:%fZ','now')"
SQLITE_UTC_DEADLINE = f"strftime('%Y-%m-%dT%H:%M:%fZ','now','+{RETENTION_DAYS} days')"


class SchemaError(RuntimeError):
    """The database schema cannot be opened safely by this build."""


class DatabaseTooNewError(SchemaError):
    pass


class MigrationBackupError(SchemaError):
    pass


class MigrationLockedError(SchemaError):
    """Another process holds the integration consumer lock; upgrading now is unsafe."""


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    statements: tuple[str, ...]


def _active(row: str) -> str:
    # "Active" = not completed and not deleted; cancelled-but-not-deleted is active.
    return f"({row}.status <> 'completed' AND {row}.deleted_at IS NULL)"


def _state(row: str) -> str:
    return f"(CASE WHEN {row}.deleted_at IS NOT NULL THEN 'deleted:' || {row}.status ELSE {row}.status END)"


def _utc(expression: str) -> str:
    # Normalise an app-written ISO timestamp (local offset) to the UTC text format.
    return f"COALESCE(strftime('%Y-%m-%dT%H:%M:%fZ', {expression}), {expression})"


def _namespace(row: str) -> str:
    return (f"(CASE WHEN {row}.source_reference LIKE 'PROJECT:%' THEN 'PROJECT' "
            f"WHEN {row}.source_reference LIKE 'CLOUD:%' THEN 'CLOUD' ELSE NULL END)")


V5_SCHEMA = (
    "ALTER TABLE tasks ADD COLUMN deleted_at TEXT",
    "ALTER TABLE tasks ADD COLUMN deleted_by TEXT",
    "CREATE INDEX idx_tasks_deleted_at ON tasks(deleted_at)",
    "ALTER TABLE local_queue_commands ADD COLUMN channel TEXT NOT NULL DEFAULT 'inbox'",
    "ALTER TABLE local_queue_commands ADD COLUMN actor_token_id TEXT",
    "ALTER TABLE local_queue_commands ADD COLUMN request_sha256 TEXT",
    """CREATE TABLE local_identity (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        db_id TEXT NOT NULL, epoch INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL, schema_marker TEXT NOT NULL)""",
    # episode: +1 on every active -> inactive transition (0 = never inactive).
    # clock_source: where inactive_since came from; NULL while active.
    """CREATE TABLE task_lifecycle (
        task_id INTEGER PRIMARY KEY,
        episode INTEGER NOT NULL DEFAULT 0,
        inactive_since TEXT, retention_deadline TEXT, inactive_reason TEXT,
        clock_source TEXT CHECK (clock_source IN ('transition','completed_at','unknown_legacy')),
        cloud_excluded INTEGER NOT NULL DEFAULT 0, exclusion_reason TEXT,
        content_expired_at TEXT)""",
    """CREATE TABLE task_changes (
        change_seq INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('baseline','insert','update','delete')),
        changed_at TEXT NOT NULL)""",
    "CREATE INDEX idx_task_changes_task ON task_changes(task_id, change_seq)",
    """CREATE TABLE task_state_events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL, from_state TEXT, to_state TEXT NOT NULL,
        at TEXT NOT NULL)""",
    # Content-free. Three separate clocks: inactive episode start, recycle-bin
    # (soft) deletion and physical deletion; the deadline is inherited, never restarted.
    """CREATE TABLE task_tombstones (
        task_id INTEGER PRIMARY KEY, source_reference TEXT, namespace TEXT,
        kind TEXT NOT NULL CHECK (kind IN ('hard_delete','purge','legacy_hard_delete')),
        episode INTEGER, inactive_since TEXT, soft_deleted_at TEXT, physically_deleted_at TEXT,
        retention_deadline TEXT,
        clock_source TEXT CHECK (clock_source IN ('transition','completed_at','unknown_legacy')),
        content_expired_at TEXT, change_seq INTEGER)""",
)

V5_TRIGGERS = (
    f"""CREATE TRIGGER task_v5_after_insert AFTER INSERT ON tasks BEGIN
        INSERT INTO task_changes (task_id, kind, changed_at) VALUES (NEW.id, 'insert', {SQLITE_UTC_NOW});
        INSERT OR REPLACE INTO task_lifecycle
            (task_id, episode, inactive_since, retention_deadline, inactive_reason, clock_source)
        SELECT NEW.id,
               CASE WHEN {_active('NEW')} THEN 0 ELSE 1 END,
               CASE WHEN {_active('NEW')} THEN NULL ELSE {SQLITE_UTC_NOW} END,
               CASE WHEN {_active('NEW')} THEN NULL ELSE {SQLITE_UTC_DEADLINE} END,
               CASE WHEN NEW.deleted_at IS NOT NULL THEN 'deleted'
                    WHEN NEW.status = 'completed' THEN 'completed' END,
               CASE WHEN {_active('NEW')} THEN NULL ELSE 'transition' END;
        INSERT INTO task_state_events (task_id, from_state, to_state, at)
        VALUES (NEW.id, NULL, {_state('NEW')}, {SQLITE_UTC_NOW});
    END""",
    # Clocks follow real OLD -> NEW transitions only, so same-state writes,
    # no-ops, sorting and completed -> deleted never move the deadline.
    f"""CREATE TRIGGER task_v5_after_update AFTER UPDATE ON tasks BEGIN
        INSERT INTO task_changes (task_id, kind, changed_at) VALUES (NEW.id, 'update', {SQLITE_UTC_NOW});
        INSERT OR IGNORE INTO task_lifecycle (task_id) VALUES (NEW.id);
        INSERT INTO task_state_events (task_id, from_state, to_state, at)
        SELECT NEW.id, {_state('OLD')}, {_state('NEW')}, {SQLITE_UTC_NOW}
        WHERE {_state('OLD')} IS NOT {_state('NEW')};
        -- active -> inactive: a new episode with a fresh 30-day deadline.
        UPDATE task_lifecycle
           SET episode = episode + 1,
               inactive_since = {SQLITE_UTC_NOW}, retention_deadline = {SQLITE_UTC_DEADLINE},
               inactive_reason = CASE WHEN NEW.deleted_at IS NOT NULL THEN 'deleted' ELSE 'completed' END,
               clock_source = 'transition', content_expired_at = NULL
         WHERE task_id = NEW.id AND {_active('OLD')} AND NOT {_active('NEW')};
        -- inactive -> active (reopen / undelete of a non-completed task): episode ends.
        UPDATE task_lifecycle
           SET inactive_since = NULL, retention_deadline = NULL, inactive_reason = NULL,
               clock_source = NULL, cloud_excluded = 0, exclusion_reason = NULL,
               content_expired_at = NULL
         WHERE task_id = NEW.id AND NOT {_active('OLD')} AND {_active('NEW')};
    END""",
    # Shared by UI hard delete and recycle-bin purge (decision D5). Deleting an
    # active row is itself its active -> inactive transition; otherwise the
    # existing episode, inactive_since and deadline are inherited unchanged.
    f"""CREATE TRIGGER task_v5_after_delete AFTER DELETE ON tasks BEGIN
        INSERT INTO task_changes (task_id, kind, changed_at) VALUES (OLD.id, 'delete', {SQLITE_UTC_NOW});
        INSERT OR IGNORE INTO task_lifecycle (task_id) VALUES (OLD.id);
        UPDATE task_lifecycle
           SET episode = episode + 1,
               inactive_since = {SQLITE_UTC_NOW}, retention_deadline = {SQLITE_UTC_DEADLINE},
               inactive_reason = 'deleted', clock_source = 'transition'
         WHERE task_id = OLD.id AND {_active('OLD')};
        INSERT OR REPLACE INTO task_tombstones
            (task_id, source_reference, namespace, kind, episode, inactive_since, soft_deleted_at,
             physically_deleted_at, retention_deadline, clock_source, content_expired_at, change_seq)
        SELECT OLD.id, OLD.source_reference, {_namespace('OLD')},
               CASE WHEN OLD.deleted_at IS NOT NULL THEN 'purge' ELSE 'hard_delete' END,
               l.episode, l.inactive_since,
               CASE WHEN OLD.deleted_at IS NULL THEN NULL ELSE {_utc('OLD.deleted_at')} END,
               {SQLITE_UTC_NOW}, l.retention_deadline, l.clock_source, l.content_expired_at,
               (SELECT MAX(change_seq) FROM task_changes)
          FROM task_lifecycle l WHERE l.task_id = OLD.id;
        INSERT INTO task_state_events (task_id, from_state, to_state, at)
        VALUES (OLD.id, {_state('OLD')},
                CASE WHEN OLD.deleted_at IS NOT NULL THEN 'purged' ELSE 'hard_deleted' END,
                {SQLITE_UTC_NOW});
        DELETE FROM task_lifecycle WHERE task_id = OLD.id;
    END""",
)


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
    # Version 5 is orchestrated by _apply_v5 (ordered SQL + Python backfill).
    Migration(version=5, statements=()),
)


def _row_digest(row: sqlite3.Row | dict) -> str:
    # Identical to scripts/task_queue.py::revision (sorted, compact, UTF-8 JSON).
    payload = json.dumps(dict(row), ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def utc_text(value: datetime) -> str:
    value = value.astimezone(timezone.utc)
    return value.strftime('%Y-%m-%dT%H:%M:%S.') + f'{value.microsecond // 1000:03d}Z'


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _apply_v5(connection: sqlite3.Connection, now: datetime) -> None:
    """Ordered steps inside the caller's single BEGIN IMMEDIATE transaction."""
    now_text = utc_text(now)
    # 1. Capture exact pre-ALTER baselines of queue-tracked rows.
    old_hashes = {
        row['id']: _row_digest(row)
        for row in connection.execute(
            'SELECT tasks.* FROM tasks JOIN local_queue_sources s ON tasks.id = s.task_id')
    }
    # 2. Schema (columns, tables, indexes). No triggers yet: backfill must not emit events.
    for statement in V5_SCHEMA:
        connection.execute(statement)
    # 3. Identity inside the DB.
    connection.execute(
        'INSERT INTO local_identity (singleton, db_id, epoch, created_at, schema_marker) VALUES (1, ?, 1, ?, ?)',
        (str(uuid.uuid4()), now_text, f'sitetask-schema-{SCHEMA_VERSION}'))
    # 4. Lifecycle backfill (explicit legacy handling; never invents a clock).
    for row in connection.execute('SELECT id, status, completed_at FROM tasks').fetchall():
        values = (row['id'], 0, None, None, None, None, 0, None)
        if row['status'] == 'completed':
            completed = None
            if row['completed_at']:
                try:
                    completed = datetime.fromisoformat(row['completed_at'])
                    if completed.tzinfo is None:
                        completed = completed.astimezone()
                except ValueError:
                    completed = None
            if completed is not None:
                values = (row['id'], 1, utc_text(completed),
                          utc_text(completed + timedelta(days=RETENTION_DAYS)), 'completed', 'completed_at', 0, None)
            else:
                # Legacy completed row without a usable completed_at: the transition
                # time is unknown, so no clock is recorded (no migration-time stand-in)
                # and content stays ineligible for cloud upload until a deliberate
                # reactivation (the update trigger ends the episode only on inactive -> active).
                reason = ('legacy_completed_without_completed_at' if not row['completed_at']
                          else 'legacy_completed_at_unparseable')
                values = (row['id'], 1, None, None, 'completed', 'unknown_legacy', 1, reason)
        connection.execute(
            '''INSERT INTO task_lifecycle (task_id, episode, inactive_since, retention_deadline,
                   inactive_reason, clock_source, cloud_excluded, exclusion_reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', values)
    # 5. Import existing hard-delete history (migration-4 queue source markers).
    # When those deletions happened is unknown: every clock stays NULL.
    connection.execute(
        '''INSERT OR IGNORE INTO task_tombstones (task_id, source_reference, namespace, kind, clock_source)
           SELECT task_id, source_reference, 'PROJECT', 'legacy_hard_delete', 'unknown_legacy'
             FROM local_queue_sources
            WHERE deleted = 1 AND task_id IS NOT NULL
              AND task_id NOT IN (SELECT id FROM tasks)''')
    # 6. Exact conditional rebase of queue baselines (adding columns changes every revision).
    for source in connection.execute('SELECT source_reference, task_id, last_revision FROM local_queue_sources '
                                     'WHERE deleted = 0 AND last_revision IS NOT NULL').fetchall():
        if source['task_id'] not in old_hashes or source['last_revision'] != old_hashes[source['task_id']]:
            continue  # unmatched/manual change: preserve as-is
        current = connection.execute('SELECT * FROM tasks WHERE id = ?', (source['task_id'],)).fetchone()
        connection.execute('UPDATE local_queue_sources SET last_revision = ? WHERE source_reference = ?',
                           (_row_digest(current), source['source_reference']))
    # 7. Initial change-log checkpoint: one baseline entry per existing task.
    connection.execute(
        "INSERT INTO task_changes (task_id, kind, changed_at) SELECT id, 'baseline', ? FROM tasks ORDER BY id",
        (now_text,))
    # 8. Triggers last, so every later writer (UI, queue, CLI, editor) is tracked.
    for statement in V5_TRIGGERS:
        connection.execute(statement)
    # 9. Ledger rename = schema marker rejected by builds that only know 1-4.
    connection.execute(f'ALTER TABLE {LEGACY_LEDGER} RENAME TO {LEDGER}')


# Never copied: live lock files and half-written atomic_json temporaries.
_BACKUP_IGNORE = ('consumer.lock', '*.lock', '*.rmlock', '.writing-*')
_STABLE_COPY_ATTEMPTS = 3


def _listing(directory: Path) -> list[tuple[str, int, int]]:
    ignored = shutil.ignore_patterns(*_BACKUP_IGNORE)
    entries = []
    for folder, dirs, files in os.walk(directory):
        skip = ignored(folder, dirs + files)
        dirs[:] = sorted(d for d in dirs if d not in skip)
        for name in sorted(f for f in files if f not in skip):
            path = Path(folder) / name
            stat = path.stat()
            entries.append((path.relative_to(directory).as_posix(), stat.st_size, stat.st_mtime_ns))
    return entries


def _copy_stable(source: Path, target: Path) -> list[str]:
    """Copy a directory that external CLI submitters may still write to.

    The integration lock stops other consumers, but `task_queue.py submit` only
    publishes files, so the copy is accepted only if the tree did not change
    while it was being copied (retried a few times, then the upgrade is refused).
    """
    for _ in range(_STABLE_COPY_ATTEMPTS):
        before = _listing(source)
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target, ignore=shutil.ignore_patterns(*_BACKUP_IGNORE))
        if _listing(source) == before:
            return [entry[0] for entry in before]
    raise MigrationBackupError(f'{source.name} kept changing during the pre-migration backup')


def _acquire_integration_lock(database: Database):
    """Hold the queue consumer lock (same QLockFile as LocalTaskQueue) for backup + upgrade.

    The application migrates before it creates its own queue consumer, so another
    running instance (or an old build) of the same installation could otherwise
    keep writing receipts/archive files while they are being backed up.
    """
    directory = database.path.parent / 'integration'
    if not directory.is_dir():
        return None  # no consumer has ever run here, so none can be running now
    from PySide6.QtCore import QLockFile

    lock = QLockFile(str(directory / 'consumer.lock'))
    lock.setStaleLockTime(0)  # identical policy to LocalTaskQueue: never steal a live PID's lock
    if not lock.tryLock(0):
        raise MigrationLockedError('another Site Task AI process holds the integration lock; '
                                   'close every other instance before upgrading')
    return lock


def _backup_before_upgrade(database: Database, backup_root: Path, pending: list[int], applied: set[int],
                           *, integration_lock: str = 'not_present') -> Path:
    """Consistent backup set while the caller holds BEGIN IMMEDIATE (all DB writers
    blocked) and the integration lock: database, data/integration and config/."""
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    target_dir = backup_root / f'pre-migration-v{max(pending)}-{stamp}'
    try:
        target_dir.mkdir(parents=True, exist_ok=False)
        target = target_dir / database.path.name
        source = sqlite3.connect(f'{database.path.resolve().as_uri()}?mode=ro', uri=True)
        destination = sqlite3.connect(target)
        try:
            source.backup(destination)  # single step: one consistent snapshot
            check = destination.execute('PRAGMA integrity_check').fetchall()
            source_count = source.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]
            backup_count = destination.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]
        finally:
            destination.close()
            source.close()
        if [tuple(row) for row in check] != [('ok',)] or source_count != backup_count:
            raise MigrationBackupError('pre-migration backup failed integrity verification')
        copied = {}
        for name, directory in (('integration', database.path.parent / 'integration'),
                                ('config', database.path.parent.parent / 'config')):
            if directory.is_dir():
                copied[name] = _copy_stable(directory, target_dir / name)
        manifest = {
            'version': 2, 'source': str(database.path.resolve()), 'applied': sorted(applied),
            'pending': pending, 'tasks': source_count, 'integrity_check': 'ok',
            'sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
            'copied': copied, 'integration_lock': integration_lock,
            # Restore needs the matching build: keep this executable/runtime with the backup.
            'runtime': {'executable': sys.executable, 'frozen': bool(getattr(sys, 'frozen', False)),
                        'schema_before': max(applied), 'schema_after': SCHEMA_VERSION},
            'created_at': datetime.now().astimezone().isoformat(),
        }
        (target_dir / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    except MigrationBackupError:
        raise
    except (OSError, sqlite3.Error) as error:
        raise MigrationBackupError(f'pre-migration backup failed: {type(error).__name__}') from error
    return target_dir


def apply_migrations(database: Database, *, backup_root: Path | None = None) -> tuple[int, ...]:
    held: list = []  # integration lock, released only after the upgrade committed or rolled back
    try:
        return _apply_migrations(database, backup_root, held)
    finally:
        for lock in held:
            lock.unlock()


def _apply_migrations(database: Database, backup_root: Path | None, held: list) -> tuple[int, ...]:
    applied_now: list[int] = []
    known = max(migration.version for migration in MIGRATIONS)
    with database.transaction() as connection:
        # SQLite DDL must be inside an explicit transaction for interrupted upgrades.
        # BEGIN IMMEDIATE also quiesces every other writer for backup + migration.
        connection.execute('BEGIN IMMEDIATE')
        user_version = connection.execute('PRAGMA user_version').fetchone()[0]
        if user_version > SCHEMA_VERSION:
            raise DatabaseTooNewError(f'database schema {user_version} is newer than this build ({SCHEMA_VERSION})')
        has_legacy = _table_exists(connection, LEGACY_LEDGER)
        has_current = _table_exists(connection, LEDGER)
        if has_current and has_legacy:
            raise SchemaError('both legacy and current migration ledgers exist; refusing to open')
        if has_current:
            ledger = LEDGER
        else:
            if user_version >= 5:
                raise SchemaError('database is marked schema 5 but its migration ledger is missing')
            ledger = LEGACY_LEDGER
            connection.execute(
                f"""CREATE TABLE IF NOT EXISTS {LEGACY_LEDGER} (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )"""
            )
        applied_versions = {row["version"] for row in connection.execute(f"SELECT version FROM {ledger}")}
        if applied_versions and max(applied_versions) > known:
            raise DatabaseTooNewError(f'database has migration {max(applied_versions)}; this build knows {known}')
        pending = [m.version for m in MIGRATIONS if m.version not in applied_versions]
        if pending and applied_versions:
            # Non-blocking, so holding the DB write lock here cannot deadlock with a consumer.
            lock = _acquire_integration_lock(database)
            if lock is not None:
                held.append(lock)
            _backup_before_upgrade(database, backup_root or database.path.parent.parent / 'backups',
                                   pending, applied_versions,
                                   integration_lock='held' if lock is not None else 'not_present')

        for migration in MIGRATIONS:
            if migration.version in applied_versions:
                continue
            now = datetime.now().astimezone()
            for statement in migration.statements:
                connection.execute(statement)
            if migration.version == 4:
                # Baseline existing linked tasks without changing any task field.
                for row in connection.execute('''SELECT tasks.* FROM tasks JOIN local_queue_sources s
                        ON tasks.id=s.task_id''').fetchall():
                    connection.execute('UPDATE local_queue_sources SET last_revision=? WHERE task_id=?',
                                       (_row_digest(row), row['id']))
            if migration.version == 5:
                _apply_v5(connection, now)
                ledger = LEDGER
            connection.execute(
                f"INSERT INTO {ledger} (version, applied_at) VALUES (?, ?)",
                (migration.version, now.isoformat()),
            )
            applied_now.append(migration.version)
        if 5 in applied_now:
            connection.execute(f'PRAGMA user_version = {SCHEMA_VERSION}')

    return tuple(applied_now)
