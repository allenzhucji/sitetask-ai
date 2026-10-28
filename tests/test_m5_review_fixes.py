"""Codex re-review §6.A gaps G1-G5 for migration 5 (see docs/02-cloud-protocol-v1.2.md §17)."""
from __future__ import annotations

from datetime import date, datetime, time
import json
import sqlite3
import uuid

import pytest
from PySide6.QtCore import QLockFile

import app.database.migrations as migrations
from app.database.connection import Database
from app.database.task_repository import TaskRepository
from app.models.task import Task, TaskStatus
from app.services.local_identity import LocalIdentityService
from app.services.local_queue import LocalTaskQueue
from app.utils.paths import AppPaths
from scripts.task_queue import atomic_json, digest, encode, revision, submit
from tests.test_migration_v5 import _rows, v4  # noqa: F401  (v4 is a fixture)

NOW = datetime.fromisoformat('2026-10-19T10:00:00+04:00')
TODAY = date(2026, 10, 19)
OLD = '2026-10-01T00:00:00.000Z'
OLD_DEADLINE = '2026-10-31T00:00:00.000Z'
FIELDS = dict(title='Mail task', description='d', due_date='2026-10-21', no_due=False,
              category='IRF', priority='normal')


def q(database, sql, args=()):
    with database.transaction() as connection:
        return [dict(r) for r in connection.execute(sql, args)]


def cmd(op, ref='PROJECT:NEW', **extra):
    value = {'version': 1, 'command_id': str(uuid.uuid4()), 'operation': op}
    if op != 'ping':
        value['source_reference'] = ref
    value.update(extra)
    return value


@pytest.fixture
def repo(tmp_path):
    return TaskRepository(Database(tmp_path / 'data' / 'sitetask.db'), clock=lambda: NOW)


def make(repo, title='Task', **kwargs):
    values = dict(title=title, due_date=TODAY, created_at=NOW, updated_at=NOW)
    values.update(kwargs)
    return repo.create_task(Task(**values))


def life(database, task_id):
    return q(database, 'SELECT * FROM task_lifecycle WHERE task_id=?', (task_id,))[0]


def tomb(database, task_id):
    return q(database, 'SELECT * FROM task_tombstones WHERE task_id=?', (task_id,))[0]


def clocks(row):
    return {k: row[k] for k in ('episode', 'inactive_since', 'retention_deadline', 'clock_source')}


# ---------------------------------------------------------------- G1 -------
def test_g1_migrated_v4_copy_replays_old_ledger_and_runs_every_fresh_operation(v4):
    database, ids, root = v4
    # A real pre-upgrade ledger row, written exactly as the v4 inbox did (positional INSERT).
    old_cmd = cmd('create', ref='PROJECT:A', fields=FIELDS)
    old_result = {'command_id': old_cmd['command_id'], 'payload_sha256': digest(old_cmd),
                  'status': 'existing', 'reason': 'source_reference_exists_no_changes',
                  'processed_at': NOW.isoformat()}
    with database.transaction() as connection:
        connection.execute('INSERT INTO local_queue_commands VALUES (?, ?, ?, ?)',
                           (old_cmd['command_id'], digest(old_cmd), encode(old_result).decode('utf-8'),
                            NOW.isoformat()))
    assert migrations.apply_migrations(database, backup_root=root / 'backups') == (5, 6)
    atomic_json(root / 'config/local_queue.json', {'enabled': True, 'version': 1})
    repo = TaskRepository(database, clock=lambda: NOW)
    queue = LocalTaskQueue(repo, root)
    try:
        assert queue.execute(old_cmd) == old_result                       # replay of pre-upgrade entry
        assert queue.execute({**old_cmd, 'fields': {**FIELDS, 'title': 'x'}})['reason'] == 'command_id_reused'
        created = queue.execute(cmd('create', fields=FIELDS))
        assert created['status'] == 'created'
        assert queue.execute(cmd('update', expected_revision=created['revision'],
                                 fields={'description': 'from mail'}))['status'] == 'updated'
        assert queue.execute(cmd('get'))['task']['description'] == 'from mail'
        assert queue.execute(cmd('ping'))['status'] == 'ok'
        tracked = _rows(database)[ids['tracked']]
        assert queue.execute(cmd('update', ref='PROJECT:A', expected_revision=revision(tracked),
                                 fields={'description': 'legacy row'}))['status'] == 'updated'
        # Full file path (submit -> tick -> receipt) on the migrated copy.
        via_file = cmd('get')
        assert submit(root, via_file)['status'] == 'queued'
        queue.tick()
        receipt = json.loads((root / 'data/integration/receipts' / (via_file['command_id'] + '.json')).read_text('utf-8'))
        assert receipt['status'] == 'found'
        rows = q(database, 'SELECT channel, actor_token_id, request_sha256 FROM local_queue_commands')
        assert len(rows) == 2 + 6 and {r['channel'] for r in rows} == {'inbox'}
        assert {r['actor_token_id'] for r in rows} == {None} and {r['request_sha256'] for r in rows} == {None}
    finally:
        queue.close()


# ---------------------------------------------------------------- G2 -------
def test_g2_backfill_never_invents_clocks(v4):
    database, ids, root = v4
    migrations.apply_migrations(database, backup_root=root / 'backups')
    legacy = life(database, ids['legacy'])
    assert clocks(legacy) == {'episode': 1, 'inactive_since': None, 'retention_deadline': None,
                              'clock_source': 'unknown_legacy'}
    assert legacy['cloud_excluded'] == 1 and legacy['inactive_reason'] == 'completed'
    assert life(database, ids['completed'])['clock_source'] == 'completed_at'
    assert life(database, ids['completed'])['episode'] == 1
    for active in ('tracked', 'cancelled', 'manual'):
        assert clocks(life(database, ids[active])) == {'episode': 0, 'inactive_since': None,
                                                       'retention_deadline': None, 'clock_source': None}
    gone = tomb(database, ids['gone'])
    assert gone['kind'] == 'legacy_hard_delete' and gone['clock_source'] == 'unknown_legacy'
    assert all(gone[k] is None for k in ('episode', 'inactive_since', 'soft_deleted_at',
                                         'physically_deleted_at', 'retention_deadline'))


def test_g2_unknown_legacy_clock_stays_unknown_until_deliberate_reactivation(v4):
    database, ids, root = v4
    migrations.apply_migrations(database, backup_root=root / 'backups')
    repo = TaskRepository(database, clock=lambda: NOW)
    task_id = ids['legacy']
    unknown = clocks(life(database, task_id))
    repo.update_task(repo.get_task(task_id).model_copy(update={'description': 'edited while completed'}))
    repo.complete_task(task_id)              # same-state write
    repo.soft_delete_task(task_id)           # completed -> deleted: still the same inactive episode
    repo.undelete_task(task_id)              # still completed
    assert clocks(life(database, task_id)) == unknown and life(database, task_id)['cloud_excluded'] == 1
    repo.mark_expired_content(datetime(2099, 1, 1).astimezone())   # no deadline -> never "expires"
    assert life(database, task_id)['content_expired_at'] is None
    repo.restore_task(task_id)               # deliberate reopen -> active, exclusion lifted
    reopened = life(database, task_id)
    assert reopened['cloud_excluded'] == 0 and reopened['clock_source'] is None and reopened['episode'] == 1
    repo.complete_task(task_id)              # a genuine transition starts a real clock
    second = life(database, task_id)
    assert second['episode'] == 2 and second['clock_source'] == 'transition'
    assert second['inactive_since'] is not None and second['retention_deadline'] > second['inactive_since']


def test_g2_episodes_count_real_transitions_only(repo):
    db = repo.database
    task = make(repo, 'Episodes')
    cancelled = make(repo, 'Cancelled', status=TaskStatus.CANCELLED)
    assert life(db, task.id)['episode'] == 0 and life(db, cancelled.id)['episode'] == 0  # cancelled = active
    repo.complete_task(task.id)
    assert life(db, task.id)['episode'] == 1
    repo.soft_delete_task(task.id)           # completed -> deleted: same episode
    assert life(db, task.id)['episode'] == 1
    repo.undelete_task(task.id)
    repo.restore_task(task.id)               # reopen: episode ends, counter kept
    assert life(db, task.id)['episode'] == 1 and life(db, task.id)['inactive_since'] is None
    repo.update_task(repo.get_task(task.id).model_copy(update={'status': TaskStatus.COMPLETED,
                                                                'completed_at': NOW}))  # editor path
    assert life(db, task.id)['episode'] == 2 and life(db, task.id)['clock_source'] == 'transition'
    repo.soft_delete_task(cancelled.id)      # active -> deleted starts an episode too
    assert life(db, cancelled.id)['episode'] == 1 and life(db, cancelled.id)['inactive_reason'] == 'deleted'


def test_g2_identity_change_seq_survives_pruning(tmp_path):
    paths = AppPaths(tmp_path)
    database = Database(paths.database_file)
    repo = TaskRepository(database, clock=lambda: NOW)
    for i in range(3):
        make(repo, f'T{i}')
    service = LocalIdentityService(paths, database)
    before = service.read_database_identity()
    assert before.max_change_seq == 3
    with database.transaction() as connection:
        connection.execute('DELETE FROM task_changes')  # future checkpoint pruning
    after = service.read_database_identity()
    assert after.max_change_seq == before.max_change_seq and after.max_task_id == before.max_task_id


# ---------------------------------------------------------------- G3 -------
def _seed_install(root):
    atomic_json(root / 'config/local_queue.json', {'enabled': True, 'version': 1})
    atomic_json(root / 'config/settings.json', {'theme': 'light'})
    inbox = root / 'data/integration/inbox'
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / 'pending.json').write_text('{}', encoding='utf-8')
    (inbox / '.writing-tmp123').write_text('partial', encoding='utf-8')
    (root / 'data/integration/receipts').mkdir(exist_ok=True)
    (root / 'data/integration/receipts/r.json').write_text('{}', encoding='utf-8')


def test_g3_backup_set_includes_config_and_integration_under_lock(v4):
    database, _, root = v4
    _seed_install(root)
    migrations.apply_migrations(database, backup_root=root / 'backups')
    (backup,) = (root / 'backups').glob('pre-migration-v6-*')
    assert json.loads((backup / 'config/settings.json').read_text('utf-8')) == {'theme': 'light'}
    assert (backup / 'config/local_queue.json').exists()
    assert (backup / 'integration/inbox/pending.json').exists()
    assert (backup / 'integration/receipts/r.json').exists()
    assert not (backup / 'integration/inbox/.writing-tmp123').exists()
    assert not list(backup.rglob('*.lock'))
    manifest = json.loads((backup / 'manifest.json').read_text('utf-8'))
    assert manifest['version'] == 2 and manifest['integration_lock'] == 'held'
    assert 'inbox/pending.json' in manifest['copied']['integration']
    assert 'settings.json' in manifest['copied']['config']
    assert manifest['runtime']['schema_before'] == 4 and manifest['runtime']['schema_after'] == 6
    other = QLockFile(str(root / 'data/integration/consumer.lock'))  # released after the upgrade
    assert other.tryLock(0)
    other.unlock()


def test_g3_upgrade_refused_while_another_consumer_holds_the_lock(v4):
    database, _, root = v4
    _seed_install(root)
    before = _rows(database)
    holder = QLockFile(str(root / 'data/integration/consumer.lock'))
    holder.setStaleLockTime(0)
    assert holder.tryLock(0)
    try:
        with pytest.raises(migrations.MigrationLockedError):
            migrations.apply_migrations(database, backup_root=root / 'backups')
        assert not (root / 'backups').exists()                   # nothing copied
        assert q(database, 'PRAGMA user_version') == [{'user_version': 0}]
        assert _rows(database) == before
    finally:
        holder.unlock()
    assert migrations.apply_migrations(database, backup_root=root / 'backups') == (5, 6)


def test_g3_backup_retries_until_inbox_is_stable(v4, monkeypatch):
    database, _, root = v4
    _seed_install(root)
    real_copytree = migrations.shutil.copytree
    calls = []

    tops = {root / 'data/integration', root / 'config'}

    def racing(source, target, *args, **kwargs):
        if source in tops:
            calls.append(source)
            if len(calls) == 1:  # a CLI submitter publishes a request mid-copy
                (root / 'data/integration/inbox/late.json').write_text('{}', encoding='utf-8')
        return real_copytree(source, target, *args, **kwargs)

    monkeypatch.setattr(migrations.shutil, 'copytree', racing)
    migrations.apply_migrations(database, backup_root=root / 'backups')
    (backup,) = (root / 'backups').glob('pre-migration-v6-*')
    assert (backup / 'integration/inbox/late.json').exists()
    assert len(calls) == 3  # integration twice (retry), config once


def test_g3_backup_refuses_when_inbox_never_settles(v4, monkeypatch):
    database, _, root = v4
    _seed_install(root)
    real_copytree = migrations.shutil.copytree

    def always_racing(source, target, *args, **kwargs):
        if source == root / 'data/integration':
            (root / 'data/integration/inbox' / f'{uuid.uuid4()}.json').write_text('{}', encoding='utf-8')
        return real_copytree(source, target, *args, **kwargs)

    monkeypatch.setattr(migrations.shutil, 'copytree', always_racing)
    with pytest.raises(migrations.MigrationBackupError, match='kept changing'):
        migrations.apply_migrations(database, backup_root=root / 'backups')
    assert q(database, 'PRAGMA user_version') == [{'user_version': 0}]
    other = QLockFile(str(root / 'data/integration/consumer.lock'))  # released on failure too
    assert other.tryLock(0)
    other.unlock()


# ---------------------------------------------------------------- G4 -------
def _snapshot(database):
    return {table: q(database, f'SELECT * FROM {table}') for table in
            ('tasks', 'notification_log', 'task_lifecycle', 'task_changes', 'task_tombstones',
             'task_state_events', 'local_queue_sources')}


def test_g4_tombstone_failure_rolls_back_single_hard_delete(repo):
    db = repo.database
    task = make(repo, 'Keep me', due_time=time(9, 0), source_reference='PROJECT:RB')
    with db.transaction() as connection:
        connection.execute("INSERT INTO local_queue_sources (source_reference, task_id) VALUES ('PROJECT:RB', ?)",
                           (task.id,))
    repo.record_notification(task.id, 'at_due_time', NOW)
    with db.transaction() as connection:
        connection.execute("""CREATE TRIGGER fail_tombstone BEFORE INSERT ON task_tombstones
                              BEGIN SELECT RAISE(ABORT, 'tombstone write failed'); END""")
    before = _snapshot(db)
    with pytest.raises(sqlite3.DatabaseError, match='tombstone write failed'):
        repo.delete_task(task.id)
    assert _snapshot(db) == before  # notification, task, lifecycle, mail marker: all intact


def test_g4_tombstone_failure_rolls_back_whole_bulk_purge(repo):
    db = repo.database
    first, second = make(repo, 'First'), make(repo, 'Second')
    repo.record_notification(first.id, 'at_due_time', NOW)
    repo.soft_delete_task(first.id)
    repo.soft_delete_task(second.id)
    with db.transaction() as connection:
        connection.execute(f"""CREATE TRIGGER fail_second BEFORE INSERT ON task_tombstones
                               WHEN NEW.task_id = {second.id}
                               BEGIN SELECT RAISE(ABORT, 'tombstone write failed'); END""")
    before = _snapshot(db)
    with pytest.raises(sqlite3.DatabaseError):
        repo.purge_deleted_tasks()
    assert _snapshot(db) == before
    assert {t.id for t in repo.list_deleted_tasks()} == {first.id, second.id}


def test_g4_same_state_writes_noops_and_sorting_never_move_the_clock(repo):
    db = repo.database
    done = make(repo, 'Done')
    repo.complete_task(done.id)
    with db.transaction() as connection:
        connection.execute('UPDATE task_lifecycle SET inactive_since=?, retention_deadline=? WHERE task_id=?',
                           (OLD, OLD_DEADLINE, done.id))
    pinned = clocks(life(db, done.id))
    repo.complete_task(done.id)                                              # repeated complete
    repo.update_task(repo.get_task(done.id).model_copy(update={'title': 'Renamed'}))  # same-state edit
    with db.transaction() as connection:
        connection.execute('UPDATE tasks SET sort_order=7, updated_at=? WHERE id=?', ('x', done.id))  # sorting
        connection.execute('UPDATE tasks SET title=title WHERE id=?', (done.id,))                   # noop
    repo.soft_delete_task(done.id)
    repo.undelete_task(done.id)
    assert clocks(life(db, done.id)) == pinned
    active = make(repo, 'Active')
    repo.reorder_tasks_for_date(TODAY, [active.id])
    assert clocks(life(db, active.id)) == {'episode': 0, 'inactive_since': None,
                                           'retention_deadline': None, 'clock_source': None}


# ---------------------------------------------------------------- G5 -------
def test_g5_purge_tombstone_keeps_three_separate_clocks(tmp_path):
    clock = datetime.fromisoformat('2026-10-19T10:00:00.123456+04:00')
    repo = TaskRepository(Database(tmp_path / 'data' / 'sitetask.db'), clock=lambda: clock)
    db = repo.database
    task = make(repo, 'Soft then purge', source_reference='CLOUD:' + str(uuid.uuid4()))
    repo.soft_delete_task(task.id)
    with db.transaction() as connection:   # pretend the soft delete happened on Oct 1
        connection.execute('UPDATE task_lifecycle SET inactive_since=?, retention_deadline=? WHERE task_id=?',
                           (OLD, OLD_DEADLINE, task.id))
    assert repo.purge_deleted_task(task.id)
    row = tomb(db, task.id)
    assert row['kind'] == 'purge' and row['namespace'] == 'CLOUD'
    assert row['inactive_since'] == OLD and row['retention_deadline'] == OLD_DEADLINE   # inherited
    assert row['soft_deleted_at'] == '2026-10-19T06:00:00.123Z'                       # OLD.deleted_at, UTC
    assert row['physically_deleted_at'] > row['inactive_since']                        # separate clock
    assert row['episode'] == 1 and row['clock_source'] == 'transition'


def test_g5_hard_delete_of_active_task_is_its_own_transition(repo):
    db = repo.database
    live = make(repo, 'Live')
    done = make(repo, 'Done', status=TaskStatus.COMPLETED, completed_at=NOW)
    done_clocks = clocks(life(db, done.id))
    repo.delete_task(live.id)
    repo.delete_task(done.id)
    row = tomb(db, live.id)
    assert row['kind'] == 'hard_delete' and row['soft_deleted_at'] is None and row['episode'] == 1
    assert row['inactive_since'] == row['physically_deleted_at'] and row['clock_source'] == 'transition'
    assert clocks(tomb(db, done.id)) == done_clocks       # completed -> hard delete keeps its episode
    assert q(db, 'SELECT * FROM task_lifecycle') == []


def test_g5_duplicate_drops_managed_references_only(repo):
    mail = make(repo, 'Mail', source_reference='PROJECT:DUP', source='ai')
    cloud = make(repo, 'Cloud', source_reference='CLOUD:' + str(uuid.uuid4()))
    other = make(repo, 'Other', source_reference='notes:7')
    assert repo.duplicate_task(mail.id).source_reference is None
    assert repo.duplicate_task(mail.id).source == mail.source
    assert repo.duplicate_task(cloud.id).source_reference is None
    assert repo.duplicate_task(other.id).source_reference == 'notes:7'
    refs = [r['source_reference'] for r in q(repo.database, "SELECT source_reference FROM tasks "
                                             "WHERE source_reference LIKE 'PROJECT:%' OR source_reference LIKE 'CLOUD:%'")]
    assert sorted(refs) == sorted([mail.source_reference, cloud.source_reference])
