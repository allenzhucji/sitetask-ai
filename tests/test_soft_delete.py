"""Soft delete, recycle bin, lifecycle tracking, purge and tombstones (schema 5)."""
from __future__ import annotations

from datetime import date, datetime, time
import uuid

import pytest

from app.database.connection import Database
from app.database.task_repository import TaskRepository
from app.models.task import Task, TaskStatus
from app.services.local_queue import LocalTaskQueue
from scripts.task_queue import atomic_json, read_tasks

NOW = datetime.fromisoformat('2026-10-19T10:00:00+04:00')
TODAY = date(2026, 10, 19)
OLD = '2026-01-01T00:00:00.000Z'


@pytest.fixture
def repo(tmp_path):
    return TaskRepository(Database(tmp_path / 'data' / 'sitetask.db'), clock=lambda: NOW)


def make(repo, title='Task', **kwargs):
    values = dict(title=title, due_date=TODAY, created_at=NOW, updated_at=NOW)
    values.update(kwargs)
    return repo.create_task(Task(**values))


def q(repo, sql, args=()):
    with repo.database.transaction() as connection:
        return [dict(r) for r in connection.execute(sql, args)]


def lifecycle(repo, task_id):
    return q(repo, 'SELECT * FROM task_lifecycle WHERE task_id=?', (task_id,))[0]


def test_soft_deleted_task_disappears_from_every_active_view(repo):
    timed = make(repo, 'Timed', due_time=time(10, 30))
    no_due = make(repo, 'Long term', no_due=True)
    later = make(repo, 'Later', due_date=date(2026, 11, 30))
    done = make(repo, 'Done', status=TaskStatus.COMPLETED, completed_at=NOW)
    for task in (timed, no_due, later, done):
        assert repo.soft_delete_task(task.id).deleted_by == 'local-ui'
    assert repo.list_widget_tasks(TODAY) == []
    assert repo.list_upcoming_tasks(TODAY) == []
    assert repo.list_next_three_days_tasks(TODAY) == []
    assert repo.list_later_tasks(TODAY) == []
    assert repo.list_no_due_tasks(TODAY) == []
    assert repo.list_overdue_tasks(date(2026, 12, 31)) == []
    assert repo.list_completed_tasks() == []
    assert repo.list_all_tasks() == []
    assert repo.count_widget_tasks(TODAY) == 0 and repo.count_later_tasks(TODAY) == 0
    assert repo.list_notification_candidates(TODAY, TODAY) == []
    assert repo.get_task(timed.id) is None
    assert repo.get_task(timed.id, include_deleted=True).is_deleted
    assert {t.id for t in repo.list_deleted_tasks()} == {timed.id, no_due.id, later.id, done.id}


def test_search_or_is_parenthesized_and_has_deleted_mode(repo):
    deleted_title = make(repo, 'Needle in title')
    active_desc = make(repo, 'Other', description='needle in description')
    deleted_ref = make(repo, 'Ref', source_reference='PROJECT:needle')
    repo.soft_delete_task(deleted_title.id)
    repo.soft_delete_task(deleted_ref.id)
    assert [t.id for t in repo.search_tasks('needle')] == [active_desc.id]
    assert {t.id for t in repo.search_tasks('needle', deleted=True)} == {deleted_title.id, deleted_ref.id}
    assert [t.id for t in repo.search_tasks('', deleted=True)] != []


def test_mutations_reject_deleted_rows(repo):
    task = make(repo, 'Guarded', due_time=time(9, 0))
    sibling = make(repo, 'Sibling')
    repo.record_notification(task.id, 'at_due_time', NOW)
    deleted = repo.soft_delete_task(task.id)
    snapshot = q(repo, 'SELECT * FROM tasks WHERE id=?', (task.id,))
    assert repo.update_task(deleted.model_copy(update={'title': 'Changed', 'due_date': date(2026, 12, 1)})) is None
    assert repo.complete_task(task.id) is None
    assert repo.restore_task(task.id) is None          # reopen
    assert repo.duplicate_task(task.id) is None
    assert repo.soft_delete_task(task.id) is None      # already deleted
    with pytest.raises(ValueError):
        repo.reorder_tasks_for_date(TODAY, [sibling.id, task.id])
    with pytest.raises(ValueError):
        repo.move_task_to_date(task.id, date(2026, 10, 20), [task.id])
    assert q(repo, 'SELECT * FROM tasks WHERE id=?', (task.id,)) == snapshot
    assert repo.has_notification(task.id, 'at_due_time')  # failed update did not clear the log
    assert repo.undelete_task(sibling.id) is None      # not deleted
    restored = repo.undelete_task(task.id)
    assert restored.deleted_at is None and restored.title == 'Guarded'
    assert [t.id for t in repo.reorder_tasks_for_date(TODAY, [sibling.id, task.id])] == [sibling.id, task.id]


def test_lifecycle_deadlines_follow_first_non_active_transition(repo):
    task = make(repo, 'Lifecycle')
    assert lifecycle(repo, task.id)['inactive_since'] is None
    repo.complete_task(task.id)
    first = lifecycle(repo, task.id)
    assert first['inactive_reason'] == 'completed' and first['retention_deadline'] > first['inactive_since']
    days = q(repo, 'SELECT julianday(retention_deadline) - julianday(inactive_since) AS d FROM task_lifecycle WHERE task_id=?', (task.id,))[0]['d']
    assert round(days, 6) == 30
    # Pretend completion was long ago; deleting afterwards must keep that deadline.
    with repo.database.transaction() as connection:
        connection.execute("UPDATE task_lifecycle SET inactive_since=?, retention_deadline='2026-01-31T00:00:00.000Z' WHERE task_id=?", (OLD, task.id))
    repo.soft_delete_task(task.id)
    assert lifecycle(repo, task.id)['retention_deadline'] == '2026-01-31T00:00:00.000Z'
    repo.undelete_task(task.id)  # still completed -> still non-active, deadline kept
    assert lifecycle(repo, task.id)['retention_deadline'] == '2026-01-31T00:00:00.000Z'
    repo.restore_task(task.id)  # reopen -> active again, clock cleared
    assert lifecycle(repo, task.id)['inactive_since'] is None
    repo.complete_task(task.id)  # re-complete restarts a fresh 30 days
    assert lifecycle(repo, task.id)['inactive_since'] > OLD
    cancelled = make(repo, 'Cancelled', status=TaskStatus.CANCELLED)
    assert lifecycle(repo, cancelled.id)['inactive_since'] is None  # cancelled counts as active


def test_editor_status_change_via_update_task_is_tracked(repo):
    task = make(repo, 'Editor')
    repo.update_task(task.model_copy(update={'status': TaskStatus.COMPLETED, 'completed_at': NOW}))
    events = q(repo, 'SELECT from_state, to_state FROM task_state_events WHERE task_id=? ORDER BY event_id', (task.id,))
    assert events == [{'from_state': None, 'to_state': 'pending'}, {'from_state': 'pending', 'to_state': 'completed'}]
    assert lifecycle(repo, task.id)['inactive_reason'] == 'completed'
    repo.update_task(repo.get_task(task.id).model_copy(update={'status': TaskStatus.CANCELLED, 'completed_at': None}))
    assert lifecycle(repo, task.id)['inactive_since'] is None
    created_done = make(repo, 'Created completed', status=TaskStatus.COMPLETED, completed_at=NOW)
    assert lifecycle(repo, created_done.id)['inactive_since'] is not None
    kinds = [r['kind'] for r in q(repo, 'SELECT kind FROM task_changes ORDER BY change_seq')]
    assert kinds == ['insert', 'update', 'update', 'insert']


def test_bulk_purge_is_atomic_and_leaves_tombstones_with_original_deadline(repo):
    a = make(repo, 'A', due_time=time(8, 0), source_reference='PROJECT:PURGE-A')
    b = make(repo, 'B')
    active = make(repo, 'Active')
    repo.record_notification(a.id, 'at_due_time', NOW)
    repo.complete_task(a.id)
    with repo.database.transaction() as connection:
        connection.execute("UPDATE task_lifecycle SET retention_deadline='2026-02-01T00:00:00.000Z' WHERE task_id=?", (a.id,))
    repo.soft_delete_task(a.id)
    repo.soft_delete_task(b.id)
    b_deadline = lifecycle(repo, b.id)['retention_deadline']
    with pytest.raises(ValueError):
        repo.purge_deleted_tasks([a.id, active.id])
    assert len(repo.list_deleted_tasks()) == 2 and repo.get_task(active.id) is not None
    assert repo.purge_deleted_tasks() == 2
    assert repo.list_deleted_tasks() == [] and repo.get_task(active.id) is not None
    tombstones = {r['task_id']: r for r in q(repo, 'SELECT * FROM task_tombstones')}
    assert tombstones[a.id]['kind'] == 'purge' and tombstones[a.id]['retention_deadline'] == '2026-02-01T00:00:00.000Z'
    assert tombstones[a.id]['namespace'] == 'PROJECT' and tombstones[b.id]['retention_deadline'] == b_deadline
    assert set(tombstones[a.id]) == {'task_id', 'source_reference', 'namespace', 'kind', 'episode',
                                     'inactive_since', 'soft_deleted_at', 'physically_deleted_at',
                                     'retention_deadline', 'clock_source', 'content_expired_at',
                                     'change_seq'}  # content-free
    assert q(repo, 'SELECT * FROM notification_log') == []
    assert q(repo, "SELECT deleted FROM local_queue_sources WHERE source_reference='PROJECT:PURGE-A'") == [{'deleted': 1}]
    assert q(repo, 'SELECT task_id FROM task_lifecycle') == [{'task_id': active.id}]
    assert make(repo, 'New').id > max(a.id, b.id, active.id)  # ids never reused
    with pytest.raises(ValueError):
        repo.purge_deleted_task(active.id)


def test_ui_hard_delete_shares_tombstone_trigger(repo):
    live = make(repo, 'Live hard delete', source_reference='CLOUD:' + str(uuid.uuid4()))
    done = make(repo, 'Done hard delete', status=TaskStatus.COMPLETED, completed_at=NOW)
    done_deadline = lifecycle(repo, done.id)['retention_deadline']
    assert repo.delete_task(live.id) and repo.delete_task(done.id)
    tombstones = {r['task_id']: r for r in q(repo, 'SELECT * FROM task_tombstones')}
    assert tombstones[live.id]['kind'] == 'hard_delete' and tombstones[live.id]['namespace'] == 'CLOUD'
    assert tombstones[live.id]['retention_deadline'] > tombstones[live.id]['physically_deleted_at']  # first non-active now
    assert tombstones[done.id]['retention_deadline'] == done_deadline                  # earlier deadline kept
    last = q(repo, 'SELECT change_seq, kind FROM task_changes ORDER BY change_seq DESC LIMIT 1')[0]
    assert last['kind'] == 'delete' and tombstones[done.id]['change_seq'] == last['change_seq']


def test_content_expiry_is_recorded_separately_from_purge(repo):
    expired = make(repo, 'Expired', status=TaskStatus.COMPLETED, completed_at=NOW)
    gone = make(repo, 'Gone', status=TaskStatus.COMPLETED, completed_at=NOW)
    with repo.database.transaction() as connection:
        connection.execute("UPDATE task_lifecycle SET retention_deadline='2026-01-01T00:00:00.000Z'")
    repo.delete_task(gone.id)
    assert repo.mark_expired_content(NOW) == 2
    assert lifecycle(repo, expired.id)['content_expired_at'] is not None
    tomb = q(repo, 'SELECT kind, content_expired_at FROM task_tombstones WHERE task_id=?', (gone.id,))[0]
    assert tomb['kind'] == 'hard_delete' and tomb['content_expired_at'] is not None
    assert repo.get_task(expired.id) is not None  # expiry never removes local content
    repo.restore_task(expired.id)                 # becomes active with new state
    assert lifecycle(repo, expired.id)['content_expired_at'] is None


def test_inbox_cannot_touch_soft_deleted_tasks_and_cli_read_hides_them(repo, tmp_path):
    atomic_json(tmp_path / 'config/local_queue.json', {'enabled': True, 'version': 1})
    queue = LocalTaskQueue(repo, tmp_path)
    try:
        def cmd(op, **extra):
            value = {'version': 1, 'command_id': str(uuid.uuid4()), 'operation': op, 'source_reference': 'PROJECT:SD'}
            value.update(extra)
            return queue.execute(value)
        created = cmd('create', fields=dict(title='Mail task', description='d', due_date='2026-10-21',
                                             no_due=False, category='IRF', priority='normal'))
        repo.soft_delete_task(created['task']['id'])
        fields = dict(title='Mail task', description='d', due_date='2026-10-21', no_due=False, category='IRF', priority='normal')
        for result in (cmd('create', fields=fields), cmd('get'),
                       cmd('update', expected_revision='0' * 64, fields={'title': 'x'})):
            assert result['status'] == 'protected' and result['reason'] == 'task_deleted'
            assert 'task' not in result
        assert read_tasks(tmp_path) == []
        assert [r['task']['id'] for r in read_tasks(tmp_path, include_deleted=True)] == [created['task']['id']]
    finally:
        queue.close()
