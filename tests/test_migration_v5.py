"""Migration 5: ordering, exact baseline rebase, backup, guards, old-build lockout."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import sqlite3
import uuid

import pytest

import app.database.migrations as migrations
from app.database.connection import Database
from app.database.task_repository import TaskRepository
from app.services.local_queue import LocalTaskQueue
from scripts.task_queue import atomic_json, revision
from tests.fixtures import legacy_migrations_v4

NOW = datetime.fromisoformat('2026-10-19T10:00:00+04:00')
COMPLETED_AT = '2026-10-01T09:30:00+04:00'


def _insert(connection, title, status='pending', ref=None, completed_at=None):
    return connection.execute(
        '''INSERT INTO tasks (title, due_date, status, source_reference, created_at, updated_at, completed_at)
           VALUES (?, '2026-10-20', ?, ?, ?, ?, ?)''',
        (title, status, ref, NOW.isoformat(), NOW.isoformat(), completed_at)).lastrowid


@pytest.fixture
def v4(tmp_path, monkeypatch):
    """A realistic schema-4 database built with the real migrations 1-4."""
    database = Database(tmp_path / 'data' / 'sitetask.db')
    all_migrations = migrations.MIGRATIONS
    monkeypatch.setattr(migrations, 'MIGRATIONS', all_migrations[:3])
    migrations.apply_migrations(database)
    with database.transaction() as connection:
        ids = {
            'tracked': _insert(connection, 'Tracked pending', ref='PROJECT:A'),
            'completed': _insert(connection, 'Completed', 'completed', 'PROJECT:B', COMPLETED_AT),
            'legacy': _insert(connection, 'Legacy completed', 'completed'),
            'cancelled': _insert(connection, 'Cancelled', 'cancelled'),
            'manual': _insert(connection, 'Manually edited', ref='PROJECT:C'),
            'gone': _insert(connection, 'Hard deleted before upgrade', ref='PROJECT:D'),
        }
    monkeypatch.setattr(migrations, 'MIGRATIONS', all_migrations[:4])
    assert migrations.apply_migrations(database, backup_root=tmp_path / 'backups-m4') == (4,)
    with database.transaction() as connection:
        connection.execute("UPDATE tasks SET description='manual edit' WHERE id=?", (ids['manual'],))
        connection.execute('DELETE FROM tasks WHERE id=?', (ids['gone'],))
        # Old-style ledger row exactly as the v4 inbox wrote it (no column list).
        connection.execute('INSERT INTO local_queue_commands VALUES (?, ?, ?, ?)',
                           (str(uuid.uuid4()), 'a' * 64, '{}', NOW.isoformat()))
    monkeypatch.setattr(migrations, 'MIGRATIONS', all_migrations)
    return database, ids, tmp_path


def _rows(database):
    with database.transaction() as connection:
        return {row['id']: dict(row) for row in connection.execute('SELECT * FROM tasks')}


def _tables(connection):
    return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type IN ('table','trigger')")}


def test_v5_preserves_every_task_field_and_marks_schema(v4):
    database, _, root = v4
    before = _rows(database)
    assert migrations.apply_migrations(database, backup_root=root / 'backups') == (5, 6)
    after = _rows(database)
    assert {k: {c: v for c, v in row.items() if c not in ('deleted_at', 'deleted_by')} for k, row in after.items()} == before
    assert all(row['deleted_at'] is None and row['deleted_by'] is None for row in after.values())
    with database.transaction() as connection:
        assert connection.execute('PRAGMA user_version').fetchone()[0] == 6
        assert [r[0] for r in connection.execute('SELECT version FROM schema_migrations_v5 ORDER BY version')] == [1, 2, 3, 4, 5, 6]
        assert 'schema_migrations' not in _tables(connection)
        identity = connection.execute('SELECT * FROM local_identity').fetchone()
        assert str(uuid.UUID(identity['db_id'])) == identity['db_id'] and identity['epoch'] == 1
        assert {'task_v5_after_insert', 'task_v5_after_update', 'task_v5_after_delete',
                'local_queue_deleted'} <= _tables(connection)
        legacy = connection.execute('SELECT channel FROM local_queue_commands').fetchone()
        assert legacy['channel'] == 'inbox'
    assert migrations.apply_migrations(database) == ()


def test_v5_rebases_only_exactly_matching_baselines(v4):
    database, ids, root = v4
    with database.transaction() as connection:
        old_manual = connection.execute("SELECT last_revision FROM local_queue_sources WHERE source_reference='PROJECT:C'").fetchone()[0]
    migrations.apply_migrations(database, backup_root=root / 'backups')
    with database.transaction() as connection:
        sources = {r['source_reference']: dict(r) for r in connection.execute('SELECT * FROM local_queue_sources')}
        rows = {r['id']: r for r in connection.execute('SELECT * FROM tasks')}
    assert sources['PROJECT:A']['last_revision'] == revision(rows[ids['tracked']])
    assert sources['PROJECT:B']['last_revision'] == revision(rows[ids['completed']])
    assert sources['PROJECT:C']['last_revision'] == old_manual != revision(rows[ids['manual']])
    assert sources['PROJECT:D']['deleted'] == 1
    # Inbox behaviour after upgrade: tracked task updatable, manual edits still protected.
    atomic_json(root / 'config/local_queue.json', {'enabled': True, 'version': 1})
    repo = TaskRepository(database, clock=lambda: NOW)
    queue = LocalTaskQueue(repo, root)
    try:
        def update(ref, rev):
            return queue.execute({'version': 1, 'command_id': str(uuid.uuid4()), 'operation': 'update',
                                  'source_reference': ref, 'expected_revision': rev,
                                  'fields': {'description': 'from mail'}})
        assert update('PROJECT:A', revision(rows[ids['tracked']]))['status'] == 'updated'
        assert update('PROJECT:C', revision(rows[ids['manual']]))['reason'] == 'manual_changes_since_queue_write'
        with database.transaction() as connection:
            channels = {r[0] for r in connection.execute('SELECT channel FROM local_queue_commands')}
        assert channels == {'inbox'}
    finally:
        queue.close()


def test_v5_lifecycle_backfill_and_legacy_completed(v4):
    database, ids, root = v4
    migrations.apply_migrations(database, backup_root=root / 'backups')
    with database.transaction() as connection:
        life = {r['task_id']: dict(r) for r in connection.execute('SELECT * FROM task_lifecycle')}
        tombstones = {r['task_id']: dict(r) for r in connection.execute('SELECT * FROM task_tombstones')}
        baseline = connection.execute("SELECT COUNT(*) FROM task_changes WHERE kind='baseline'").fetchone()[0]
        events = connection.execute('SELECT COUNT(*) FROM task_state_events').fetchone()[0]
    completed = datetime.fromisoformat(COMPLETED_AT).astimezone(timezone.utc)
    assert life[ids['completed']]['inactive_since'] == completed.strftime('%Y-%m-%dT%H:%M:%S.000Z')
    assert life[ids['completed']]['retention_deadline'] == (completed + timedelta(days=30)).strftime('%Y-%m-%dT%H:%M:%S.000Z')
    assert life[ids['completed']]['cloud_excluded'] == 0
    assert life[ids['legacy']]['cloud_excluded'] == 1
    assert life[ids['legacy']]['exclusion_reason'] == 'legacy_completed_without_completed_at'
    for active in ('tracked', 'cancelled', 'manual'):  # cancelled counts as active
        assert life[ids[active]]['inactive_since'] is None
    assert tombstones[ids['gone']]['kind'] == 'legacy_hard_delete'
    assert tombstones[ids['gone']]['source_reference'] == 'PROJECT:D'
    assert baseline == 6 and events == 0  # backfill happens before triggers exist


def test_pre_upgrade_backup_is_consistent_and_verified(v4):
    database, _, root = v4
    migrations.apply_migrations(database, backup_root=root / 'backups')
    (backup_dir,) = (root / 'backups').glob('pre-migration-v6-*')
    copy = sqlite3.connect(backup_dir / 'sitetask.db')
    try:
        assert copy.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert copy.execute('PRAGMA user_version').fetchone()[0] == 0
        assert copy.execute('SELECT COUNT(*) FROM tasks').fetchone()[0] == 5
        assert copy.execute("SELECT name FROM sqlite_master WHERE name='schema_migrations'").fetchone()
        assert copy.execute("SELECT COUNT(*) FROM pragma_table_info('tasks') WHERE name='deleted_at'").fetchone()[0] == 0
    finally:
        copy.close()
    manifest = json.loads((backup_dir / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest['pending'] == [5, 6] and manifest['integrity_check'] == 'ok' and manifest['tasks'] == 5


def test_backup_failure_refuses_migration(v4):
    database, _, root = v4
    blocker = root / 'not-a-directory'
    blocker.write_text('x', encoding='utf-8')
    with pytest.raises(migrations.MigrationBackupError):
        migrations.apply_migrations(database, backup_root=blocker)
    with database.transaction() as connection:
        assert connection.execute('PRAGMA user_version').fetchone()[0] == 0
        assert 'schema_migrations' in _tables(connection)
        assert connection.execute("SELECT COUNT(*) FROM pragma_table_info('tasks') WHERE name='deleted_at'").fetchone()[0] == 0


def test_backup_blocks_concurrent_writers(v4):
    database, _, root = v4
    seen = {}
    original = migrations._backup_before_upgrade

    def probe(*args, **kwargs):
        other = sqlite3.connect(database.path, timeout=0.05)
        try:
            with pytest.raises(sqlite3.OperationalError, match='locked'):
                other.execute("UPDATE tasks SET title='raced' WHERE id=1")
            seen['blocked'] = True
        finally:
            other.close()
        return original(*args, **kwargs)

    migrations._backup_before_upgrade = probe
    try:
        migrations.apply_migrations(database, backup_root=root / 'backups')
    finally:
        migrations._backup_before_upgrade = original
    assert seen == {'blocked': True}


def test_interrupted_v5_rolls_back_completely_and_retries(v4, monkeypatch):
    database, _, root = v4
    before = _rows(database)
    monkeypatch.setattr(migrations, 'V5_TRIGGERS', migrations.V5_TRIGGERS + ('INVALID SQL',))
    with pytest.raises(sqlite3.Error):
        migrations.apply_migrations(database, backup_root=root / 'backups')
    with database.transaction() as connection:
        names = _tables(connection)
        assert 'schema_migrations' in names and 'schema_migrations_v5' not in names
        assert not {'local_identity', 'task_lifecycle', 'task_changes', 'task_tombstones'} & names
        assert connection.execute('PRAGMA user_version').fetchone()[0] == 0
    assert _rows(database) == before
    monkeypatch.undo()
    monkeypatch.setattr(migrations, 'MIGRATIONS', migrations.MIGRATIONS)
    assert migrations.apply_migrations(database, backup_root=root / 'backups') == (5, 6)


def test_newer_database_is_refused(tmp_path):
    database = Database(tmp_path / 'data' / 'sitetask.db')
    migrations.apply_migrations(database)
    with database.transaction() as connection:
        connection.execute('PRAGMA user_version = 7')
    with pytest.raises(migrations.DatabaseTooNewError):
        migrations.apply_migrations(database)
    with database.transaction() as connection:
        connection.execute('PRAGMA user_version = 6')
        connection.execute("INSERT INTO schema_migrations_v5 VALUES (9, 'x')")
    with pytest.raises(migrations.DatabaseTooNewError):
        TaskRepository(database)


def test_both_ledgers_present_is_refused(tmp_path):
    database = Database(tmp_path / 'data' / 'sitetask.db')
    migrations.apply_migrations(database)
    with database.transaction() as connection:
        connection.execute('CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)')
    with pytest.raises(migrations.SchemaError):
        migrations.apply_migrations(database)


def test_legacy_v4_build_cannot_open_migrated_database(v4):
    database, _, root = v4
    migrations.apply_migrations(database, backup_root=root / 'backups')
    before = _rows(database)
    # The real migration runner shipped with schema-4 builds (git baseline copy).
    with pytest.raises(sqlite3.OperationalError, match='duplicate column name: sort_order'):
        legacy_migrations_v4.apply_migrations(database)
    with database.transaction() as connection:
        assert 'schema_migrations' not in _tables(connection)  # its attempt rolled back
        assert connection.execute('PRAGMA user_version').fetchone()[0] == 6
    assert _rows(database) == before
    assert migrations.apply_migrations(database) == ()


def test_fresh_database_gets_full_schema_without_backup(tmp_path):
    database = Database(tmp_path / 'data' / 'sitetask.db')
    assert migrations.apply_migrations(database) == (1, 2, 3, 4, 5, 6)
    assert not (tmp_path / 'backups').exists()
