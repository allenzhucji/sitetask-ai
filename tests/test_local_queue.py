from datetime import datetime
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import uuid

import pytest
from app.database.connection import Database
from app.database.task_repository import TaskRepository
from app.models.task import Task
from app.services.local_queue import LocalTaskQueue
from app.services.settings_service import SettingsService
from app.ui.main_widget import MainWidget
from app.ui.task_editor_dialog import TaskEditorDialog
from app.utils.paths import AppPaths
from scripts.task_queue import atomic_json, decode, digest, read_tasks, revision, submit, validate

NOW = datetime.fromisoformat('2026-10-06T10:00:00+04:00')


def command(op='create', ref='PROJECT:TEST-1', **kwargs):
    value = dict(version=1, command_id=str(uuid.uuid4()), operation=op)
    if op != 'ping':
        value['source_reference'] = ref
    if op == 'create':
        value['fields'] = dict(title='Follow up inspection', description='Confirm with consultant.',
                               due_date='2026-10-07', no_due=False, category='IRF', priority='normal')
    value.update(kwargs)
    return value


@pytest.fixture
def setup(tmp_path):
    paths = AppPaths(tmp_path)
    repo = TaskRepository(Database(paths.database_file), clock=lambda: NOW)
    atomic_json(tmp_path / 'config/local_queue.json', {'enabled': True, 'version': 1})
    queue = LocalTaskQueue(repo, tmp_path)
    yield repo, queue, tmp_path
    queue.close()


def result(root, cmd):
    return json.loads((root / 'data/integration/receipts' / (cmd['command_id'] + '.json')).read_text(encoding='utf-8'))


def test_create_update_read_and_source_and_id_dedup(setup):
    repo, queue, root = setup
    cmd = command()
    assert submit(root, cmd)['status'] == 'queued'
    assert repo.list_all_tasks() == []
    queue.tick()
    created = result(root, cmd)
    assert created['status'] == 'created'
    assert created['task']['due_time'] is None
    assert submit(root, cmd) == created
    assert queue.execute(cmd) == created
    other = command()
    assert queue.execute(other)['status'] == 'existing'
    assert len(repo.list_all_tasks()) == 1
    update = command('update', expected_revision=created['revision'], fields={'description': 'New verified requirement.'})
    updated = queue.execute(update)
    assert updated['status'] == 'updated'
    assert queue.execute(command('get'))['task']['description'] == 'New verified requirement.'
    assert read_tasks(root, cmd['source_reference'])[0]['revision'] == updated['revision']
    same_id_other_payload = {**cmd, 'fields': {**cmd['fields'], 'title': 'Changed'}}
    assert queue.execute(same_id_other_payload)['reason'] == 'command_id_reused'
    with pytest.raises(ValueError):
        submit(root, same_id_other_payload)


@pytest.mark.parametrize('status', ['completed', 'cancelled'])
def test_closed_tasks_never_reopen_or_change(setup, status):
    repo, queue, root = setup
    created = queue.execute(command())
    task = repo.get_task(created['task']['id'])
    repo.update_task(task.model_copy(update={'status': status}))
    before = read_tasks(root)
    assert queue.execute(command())['status'] == 'protected'
    assert queue.execute(command('update', expected_revision=before[0]['revision'], fields={'title': 'New'}))['status'] == 'protected'
    assert read_tasks(root) == before


def test_delete_and_historical_exclusions_preserved(setup):
    repo, queue, root = setup
    created = queue.execute(command())
    repo.delete_task(created['task']['id'])
    assert queue.execute(command())['reason'] == 'deleted_or_identity_changed'
    for ref in ['PROJECT:T002', 'PROJECT:T003', 'PROJECT:T004', 'PROJECT:T013']:
        assert queue.execute(command(ref=ref))['reason'] == 'previously_completed_excluded'
    assert read_tasks(root) == []


def test_manual_conflict_even_when_caller_rereads(setup):
    repo, queue, root = setup
    created = queue.execute(command())
    repo.update_task(repo.get_task(created['task']['id']).model_copy(update={'description': 'USER EDIT'}))
    before = read_tasks(root)
    cmd = command('update', expected_revision=created['revision'], fields={'description': 'MAIL'})
    assert queue.execute(cmd)['reason'] == 'revision_changed'
    cmd['command_id'] = str(uuid.uuid4())
    cmd['expected_revision'] = before[0]['revision']
    assert queue.execute(cmd)['reason'] == 'manual_changes_since_queue_write'
    assert read_tasks(root) == before


def test_legacy_task_update_requires_current_revision_and_duplicate_refs_conflict(setup):
    repo, queue, root = setup
    task = repo.create_task(Task(title='Legacy', due_date='2026-10-06', source_reference='PROJECT:TEST-1'))
    snapshot = read_tasks(root)[0]
    updated = queue.execute(command('update', expected_revision=snapshot['revision'], fields={'description': 'Concise'}))
    assert updated['status'] == 'updated'
    repo.duplicate_task(task.id)
    assert queue.execute(command())['reason'] == 'ambiguous_source_reference'


def test_no_due_has_no_timed_reminder_and_changed_schedule_clears_log(setup):
    repo, queue, root = setup
    task = repo.create_task(Task(title='Legacy timed', due_date='2026-10-06', due_time='10:00', source_reference='PROJECT:TEST-1'))
    repo.record_notification(task.id, 'due', NOW)
    first = read_tasks(root)[0]
    updated = queue.execute(command('update', expected_revision=first['revision'], fields={'description': 'Changed text'}))
    assert repo.has_notification(task.id, 'due')
    assert updated['task']['due_time'] == '10:00'
    changed = queue.execute(command('update', expected_revision=updated['revision'], fields={'no_due': True, 'due_date': None}))
    assert changed['task']['no_due'] == 1 and changed['task']['due_time'] is None
    assert not repo.has_notification(task.id, 'due')


@pytest.mark.parametrize('mutate', [
    lambda c: c.update(operation='sql'),
    lambda c: c.update(version=True),
    lambda c: c.update(command_id='../bad'),
    lambda c: c.update(source_reference='OTHER:1'),
    lambda c: c['fields'].update(status='completed'),
    lambda c: c['fields'].update(due_time='09:00'),
    lambda c: c['fields'].update(no_due=1),
    lambda c: c['fields'].update(due_date='2026-02-31'),
    lambda c: c['fields'].update(title='[PROJECT] Bad prefix'),
    lambda c: c['fields'].update(description='x' * 6001),
    lambda c: c.update(path='C:/arbitrary'),
])
def test_strict_validation(mutate):
    cmd = command()
    mutate(cmd)
    with pytest.raises((ValueError, TypeError)):
        validate(cmd)


def test_invalid_and_oversized_requests_do_not_block_following_request(setup):
    repo, queue, root = setup
    valid = command()
    submit(root, valid)
    inbox = root / 'data/integration/inbox'
    invalid_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    (inbox / (invalid_ids[0] + '.json')).write_bytes(b'{broken')
    (inbox / (invalid_ids[1] + '.json')).write_bytes(b' ' * 33000)
    queue.tick()
    assert result(root, valid)['status'] == 'created'
    for cid in invalid_ids:
        assert result(root, {'command_id': cid})['status'] == 'invalid'
    assert len(repo.list_all_tasks()) == 1
    with pytest.raises(ValueError):
        decode(b'{"version":1,"version":2}')


def test_crash_after_commit_rebuilds_receipt_without_duplicate(setup, monkeypatch):
    import app.services.local_queue as service
    repo, queue, root = setup
    cmd = command()
    submit(root, cmd)
    real = service.atomic_json
    def broken(path, value):
        if path.parent.name == 'receipts':
            raise OSError('simulated receipt disk failure')
        return real(path, value)
    monkeypatch.setattr(service, 'atomic_json', broken)
    queue.tick()
    assert len(repo.list_all_tasks()) == 1
    assert (root / 'data/integration/inbox' / (cmd['command_id'] + '.json')).exists()
    monkeypatch.setattr(service, 'atomic_json', real)
    queue.close()
    resumed = LocalTaskQueue(repo, root)
    try:
        resumed.tick()
        assert result(root, cmd)['status'] == 'created'
        assert len(repo.list_all_tasks()) == 1
    finally:
        resumed.close()


def test_failure_before_ledger_commit_rolls_back_task(setup, monkeypatch):
    repo, queue, root = setup
    cmd = command()
    real_apply = queue._apply
    def fail(connection, payload):
        real_apply(connection, payload)
        raise RuntimeError('simulated crash before receipt ledger')
    monkeypatch.setattr(queue, '_apply', fail)
    with pytest.raises(RuntimeError):
        queue.execute(cmd)
    assert read_tasks(root) == []
    monkeypatch.setattr(queue, '_apply', real_apply)
    assert queue.execute(cmd)['status'] == 'created'


def test_single_consumer_and_disabled_queue(setup):
    repo, queue, root = setup
    queue.tick()
    second = LocalTaskQueue(repo, root)
    cmd = command()
    submit(root, cmd)
    try:
        second.tick()
        assert repo.list_all_tasks() == []
        queue.tick()
        assert result(root, cmd)['status'] == 'created'
        atomic_json(root / 'config/local_queue.json', {'enabled': False, 'version': 1})
        queue.tick()
        assert queue.lock is None
        with pytest.raises(ValueError):
            submit(root, command(ref='PROJECT:TEST-2'))
    finally:
        second.close()


def test_database_busy_leaves_request_for_retry(setup):
    repo, queue, root = setup
    cmd = command()
    submit(root, cmd)
    locked = sqlite3.connect(repo.database.path)
    locked.execute('BEGIN IMMEDIATE')
    try:
        queue.tick()
        assert repo.list_all_tasks() == []
        assert (root / 'data/integration/inbox' / (cmd['command_id'] + '.json')).exists()
    finally:
        locked.rollback()
        locked.close()
    queue.tick()
    assert result(root, cmd)['status'] == 'created'


def test_upgrade_seeds_revisions_and_does_not_change_tasks(tmp_path, monkeypatch):
    import app.database.migrations as migrations
    all_migrations = migrations.MIGRATIONS
    monkeypatch.setattr(migrations, 'MIGRATIONS', all_migrations[:3])
    database = Database(tmp_path / 'data/sitetask.db')
    repo = TaskRepository(database, clock=lambda: NOW)
    task = repo.create_task(Task(title='Existing completed', due_date='2026-10-06', status='completed', source_reference='PROJECT:LEGACY'))
    before = read_tasks(tmp_path)
    monkeypatch.setattr(migrations, 'MIGRATIONS', all_migrations)
    assert migrations.apply_migrations(database) == (4,)
    assert read_tasks(tmp_path) == before
    with database.transaction() as connection:
        tracked = connection.execute('SELECT * FROM local_queue_sources').fetchone()
    assert tracked['last_revision'] == before[0]['revision']
    repo.delete_task(task.id)
    queue = LocalTaskQueue(repo, tmp_path)
    assert queue.execute(command(ref='PROJECT:LEGACY'))['status'] == 'protected'


def test_interrupted_migration_rolls_back_schema_and_retries(tmp_path, monkeypatch):
    import app.database.migrations as migrations
    all_migrations = migrations.MIGRATIONS
    monkeypatch.setattr(migrations, 'MIGRATIONS', all_migrations[:3])
    database = Database(tmp_path / 'data/sitetask.db')
    migrations.apply_migrations(database)
    broken = migrations.Migration(4, all_migrations[3].statements[:1] + ('INVALID SQL',))
    monkeypatch.setattr(migrations, 'MIGRATIONS', all_migrations[:3] + (broken,))
    with pytest.raises(sqlite3.Error):
        migrations.apply_migrations(database)
    with database.transaction() as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='local_queue_commands'").fetchone() is None
    monkeypatch.setattr(migrations, 'MIGRATIONS', all_migrations)
    assert migrations.apply_migrations(database) == (4,)


def test_running_ui_consumes_and_refreshes_pauses_for_editor_and_preserves_user_save(qtbot, setup):
    repo, queue, root = setup
    widget = MainWidget(SettingsService(AppPaths(root)), repo, today_provider=lambda: NOW.date())
    qtbot.addWidget(widget)
    widget.show()
    cmd = command()
    request_file = root / 'external-command.json'
    atomic_json(request_file, cmd)
    completed = subprocess.run([sys.executable, '-B', str(Path(__file__).parents[1] / 'scripts/task_queue.py'),
                                '--root', str(root), 'submit', str(request_file)],
                               capture_output=True, timeout=15,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    assert completed.returncode == 0 and json.loads(completed.stdout)['status'] == 'queued'
    receipt = root / 'data/integration/receipts' / (cmd['command_id'] + '.json')
    qtbot.waitUntil(receipt.exists, timeout=4000)
    created = result(root, cmd)
    assert any(item.task.id == created['task']['id'] for section in widget.sections for item in section.task_items)
    widget.open_all_tasks()
    widget.all_tasks_dialog.set_filter('All')
    widget.all_tasks_dialog.select_task(created['task']['id'])
    second = command(ref='PROJECT:TEST-2')
    submit(root, second)
    widget._set_empty_drop_targets_visible(True)
    widget.local_queue.tick()
    assert not (root / 'data/integration/receipts' / (second['command_id'] + '.json')).exists()
    widget._set_empty_drop_targets_visible(False)
    widget.local_queue.tick()
    assert result(root, second)['status'] == 'created'
    assert len(widget.all_tasks_dialog.current_tasks) == 2
    assert widget.all_tasks_dialog.selected_task().id == created['task']['id']
    edit = TaskEditorDialog(repo.get_task(created['task']['id']), parent=widget)
    qtbot.addWidget(edit)
    edit.show()
    update = command('update', expected_revision=created['revision'], fields={'description': 'External'})
    submit(root, update)
    widget.local_queue.tick()
    assert not (root / 'data/integration/receipts' / (update['command_id'] + '.json')).exists()
    repo.update_task(repo.get_task(created['task']['id']).model_copy(update={'description': 'USER SAVE'}))
    edit.close()
    qtbot.waitUntil(lambda: not edit.isVisible())
    widget.local_queue.tick()
    assert result(root, update)['status'] == 'conflict'
    assert repo.get_task(created['task']['id']).description == 'USER SAVE'
    widget.local_queue.close()
