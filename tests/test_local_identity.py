"""Local identity inside (local_identity table) and outside (config file) the database."""
from __future__ import annotations

from datetime import date, datetime
import json
import shutil

from app.database.connection import Database
from app.database.task_repository import TaskRepository
from app.models.task import Task
from app.services.local_identity import IdentityStatus, LocalIdentityService
from app.utils.paths import AppPaths

NOW = datetime.fromisoformat('2026-10-19T10:00:00+04:00')


def setup(root):
    paths = AppPaths(root)
    database = Database(paths.database_file)
    repo = TaskRepository(database, clock=lambda: NOW)
    return paths, database, repo, LocalIdentityService(paths, database)


def add(repo):
    return repo.create_task(Task(title='t', due_date=date(2026, 10, 20), created_at=NOW, updated_at=NOW))


def test_new_then_paired_and_file_is_outside_database(tmp_path):
    paths, _, repo, service = setup(tmp_path)
    assert service.check().status is IdentityStatus.NEW
    recorded = service.record()
    assert recorded.status is IdentityStatus.PAIRED
    data = json.loads((paths.config_dir / 'instance_identity.json').read_text(encoding='utf-8'))
    assert data['db_id'] == recorded.database.db_id and data['epoch'] == 1 and data['instance_id']
    add(repo)
    assert service.check().status is IdentityStatus.PAIRED
    instance = data['instance_id']
    service.record()
    assert json.loads((paths.config_dir / 'instance_identity.json').read_text())['instance_id'] == instance


def test_copied_database_is_detected(tmp_path):
    paths, database, _, service = setup(tmp_path / 'a')
    service.record()
    other = tmp_path / 'b'
    (other / 'data').mkdir(parents=True)
    shutil.copy2(database.path, other / 'data' / 'sitetask.db')
    shutil.copytree(paths.config_dir, other / 'config')
    copied = LocalIdentityService(AppPaths(other), Database(other / 'data' / 'sitetask.db'))
    assert copied.check().status is IdentityStatus.MOVED_OR_COPIED
    assert copied.record().status is IdentityStatus.MOVED_OR_COPIED  # evidence not overwritten


def test_replaced_database_is_detected(tmp_path):
    paths, database, _, service = setup(tmp_path)
    service.record()
    database.path.unlink()
    TaskRepository(Database(paths.database_file))
    assert service.check().status is IdentityStatus.DATABASE_CHANGED


def test_restored_older_backup_is_detected(tmp_path):
    paths, database, repo, service = setup(tmp_path)
    backup = tmp_path / 'backup.db'
    shutil.copy2(database.path, backup)
    task = add(repo)
    repo.delete_task(task.id)
    service.record()
    shutil.copy2(backup, database.path)
    result = service.check()
    assert result.status is IdentityStatus.ROLLBACK_SUSPECTED
    assert result.database.max_task_id < result.recorded['max_task_id_seen']


def test_pre_v5_database_is_unavailable(tmp_path):
    paths = AppPaths(tmp_path)
    database = Database(paths.database_file)
    database.path.parent.mkdir(parents=True)
    database.connect().close()
    assert LocalIdentityService(paths, database).check().status is IdentityStatus.UNAVAILABLE
