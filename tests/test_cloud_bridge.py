import json
import sqlite3
import uuid
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
import pytest
from app.database.connection import Database
from app.database.task_repository import TaskRepository
from app.models.task import Task
from app.services.cloud_store import CloudStore
from app.services.cloud_protocol import decode,validate_request,business_revision,utcnow
from app.services.cloud_network import validate_origin
from scripts.task_queue import digest,encode

@pytest.fixture
def store(tmp_path):return CloudStore(TaskRepository(Database(tmp_path/'data'/'sitetask.db')))

def request(op='create',target=None,base=None,fields=None,cid=None):
    if op=='create' and fields is None:fields=dict(title='检查墙柱',description='line\n二 😀',due_date='2026-10-28',no_due=False,category='IRF',priority='normal')
    return dict(v=1,command_id=cid or str(uuid.uuid4()),op=op,target=target,base_revision=base,fields=fields,reason=None)

def delivery(store,r,**overrides):
    now=datetime.now(timezone.utc)
    ts=lambda d:d.isoformat(timespec='milliseconds').replace('+00:00','Z')
    ident=store.identity()
    e=dict(ev=1,db_id=ident['db_id'],command_id=r['command_id'],request_sha256=digest(r),request=r,
        actor=dict(token_id='a'*16,scope='assistant'),assigned_source_reference='CLOUD:'+r['command_id'] if r['op']=='create' else None,
        accepted_at=ts(now),execute_before=ts(now+timedelta(days=7)))
    d=dict(envelope=e,epoch=ident['epoch'],lease_id=str(uuid.uuid4()),lease_gen=1,lease_until=ts(now+timedelta(seconds=120)))
    d.update(overrides);return d

def row(store,task_id):
    with store.database.transaction() as c:return c.execute('SELECT * FROM tasks WHERE id=?',(task_id,)).fetchone()

def test_atomic_command_replay_and_outbox(store):
    d=delivery(store,request());a=store.execute(d);b=store.execute(d)
    assert a['task_id']==b['task_id'] and a['result_sha256']==b['result_sha256']
    assert len(store.repository.list_all_tasks())==1 and len(store.outbox())==1
    store.acknowledge_receipts([a['command_id']]);assert not store.outbox()
    store.execute(d);assert len(store.outbox())==1

def test_outbox_failure_rolls_back_task_and_ledger(store):
    with store.database.transaction() as c:c.execute("CREATE TRIGGER fail_outbox BEFORE INSERT ON cloud_receipt_outbox BEGIN SELECT RAISE(ABORT,'injected'); END")
    with pytest.raises(sqlite3.IntegrityError):store.execute(delivery(store,request()))
    assert not store.repository.list_all_tasks()
    with store.database.transaction() as c:assert c.execute('SELECT COUNT(*) FROM local_queue_commands').fetchone()[0]==0

@pytest.mark.parametrize('operation',['complete','reopen','soft_delete','restore','get','update'])
def test_operations_and_revision(store,operation):
    made=store.execute(delivery(store,request()));tid=made['task_id']
    if operation=='reopen':store.repository.complete_task(tid)
    if operation=='restore':store.repository.soft_delete_task(tid)
    r=request(operation,{'task_id':tid},None if operation=='get' else business_revision(row(store,tid)),{'title':'新任务'} if operation=='update' else None)
    receipt=store.execute(delivery(store,r));assert receipt['status']=='applied'
    current=row(store,tid)
    if operation=='soft_delete':assert current['deleted_at']
    if operation=='restore':assert current['deleted_at'] is None
    if operation=='complete':assert current['status']=='completed'
    if operation=='reopen':assert current['status']=='pending'

def test_revision_conflict_and_deleted_protection(store):
    a=store.execute(delivery(store,request()));tid=a['task_id']
    r=request('complete',{'task_id':tid},'0'*64)
    assert store.execute(delivery(store,r))['result_code']=='revision_changed'
    store.repository.soft_delete_task(tid)
    r=request('update',{'task_id':tid},business_revision(row(store,tid)),{'title':'should not write'})
    assert store.execute(delivery(store,r))['result_code']=='task_deleted'

def test_hard_deleted_identity_is_terminal(store):
    a=store.execute(delivery(store,request()));store.repository.delete_task(a['task_id'])
    r=request('get',{'task_id':a['task_id']})
    assert store.execute(delivery(store,r))['result_code']=='purged'
    assert store.snapshot()['items'][0]['lifecycle']=='tombstone'

def test_cloud_cannot_change_mail_baseline(store):
    from app.services.local_queue import LocalTaskQueue
    q=LocalTaskQueue(store.repository,store.database.path.parent.parent)
    fields=request()['fields'];ref='PROJECT:test'
    a=q.execute(dict(version=1,command_id=str(uuid.uuid4()),operation='create',source_reference=ref,fields=fields))
    r=request('update',{'source_reference':ref},business_revision(row(store,a['task']['id'])),{'title':'Assistant edit'})
    assert store.execute(delivery(store,r))['status']=='applied'
    current=row(store,a['task']['id'])
    b=q.execute(dict(version=1,command_id=str(uuid.uuid4()),operation='update',source_reference=ref,fields={'title':'Mail edit'},expected_revision=digest(dict(current))))
    assert b['reason']=='manual_changes_since_queue_write'

def test_wrong_identity_actor_replay_and_fence(store):
    d=delivery(store,request());store.execute(d)
    d['envelope']['actor']['token_id']='b'*16
    with pytest.raises(ValueError,match='reused'):store.execute(d)
    d=delivery(store,request());d['epoch']+=1
    with pytest.raises(ValueError,match='epoch'):store.execute(d)
    store.fence()
    with pytest.raises(sqlite3.IntegrityError,match='fenced'):store.repository.create_task(Task(title='blocked',due_date=date.today()))
    with pytest.raises(ValueError,match='fenced'):store.execute(delivery(store,request()))

def test_all_events_pruned_snapshot_survives(store):
    a=store.execute(delivery(store,request()));before=store.snapshot()
    with store.database.transaction() as c:c.execute('DELETE FROM task_changes')
    after=store.snapshot();assert before==after and after['as_of']>0
    store.repository.complete_task(a['task_id']);assert store.snapshot()['as_of']>before['as_of']

def test_expired_get_reopen_and_old_receipt_stays_redacted(store):
    a=store.execute(delivery(store,request()));tid=a['task_id'];store.repository.complete_task(tid)
    with store.database.transaction() as c:
        c.execute("UPDATE task_lifecycle SET retention_deadline='2000-01-01T00:00:00.000Z' WHERE task_id=?",(tid,))
    g=store.execute(delivery(store,request('get',{'task_id':tid})));assert g['snapshot'] is None
    reopened=store.execute(delivery(store,request('reopen',{'task_id':tid},business_revision(row(store,tid)))))
    assert reopened['status']=='applied'
    assert store.snapshot()['items'][0]['content'] is not None
    old=next(x for x in store.outbox() if x['command_id']==a['command_id']);assert old['snapshot'] is None

@pytest.mark.parametrize('move',[False,True])
def test_m1_write_lock_precedes_validation(store,move):
    repo=store.repository;a=repo.create_task(Task(title='a',due_date=date(2026,10,28)))
    attempted=[]
    def clock():
        c=sqlite3.connect(store.database.path,timeout=0.01)
        try:
            with pytest.raises(sqlite3.OperationalError,match='locked'):c.execute("UPDATE tasks SET deleted_at='deleted' WHERE id=?",(a.id,))
            attempted.append(True)
        finally:c.close()
        return datetime.now().astimezone()
    repo.clock=clock
    if move:repo.move_task_to_date(a.id,date(2026,10,29),[a.id])
    else:repo.reorder_tasks_for_date(date(2026,10,28),[a.id])
    assert attempted and row(store,a.id)['deleted_at'] is None

def test_m1_rowcount_failure_rolls_back_every_write(store):
    repo=store.repository;day=date(2026,10,28)
    a=repo.create_task(Task(title='a',due_date=day));b=repo.create_task(Task(title='b',due_date=day))
    with store.database.transaction() as c:c.execute(f'CREATE TRIGGER skip_sort BEFORE UPDATE ON tasks WHEN OLD.id={b.id} BEGIN SELECT RAISE(IGNORE); END')
    with pytest.raises(ValueError):repo.reorder_tasks_for_date(day,[a.id,b.id])
    assert row(store,a.id)['sort_order'] is None

@pytest.mark.parametrize('url',['http://example.com','https://u:p@example.com','https://example.com/path','https://example.com?secret=1','https://example.com#x','file:///x'])
def test_origin_rejects(url):
    with pytest.raises(ValueError):validate_origin(url)

def test_local_transport_requires_explicit_test_mode():
    with pytest.raises(ValueError):validate_origin('http://127.0.0.1:8787')
    assert validate_origin('http://127.0.0.1:8787',local_test=True)=='http://127.0.0.1:8787'

@pytest.mark.parametrize('raw',[b'{"x":1,"x":2}',b'{"x":1.0}',b'{"x":9007199254740992}',b'{"x":"\\ud800"}'])
def test_strict_wire_rejects(raw):
    with pytest.raises(ValueError):decode(raw)

def test_no_hard_delete_path():
    root=Path(__file__).parents[1]/'app'/'services'
    for path in root.glob('cloud_*.py'):
        assert '.delete_task(' not in path.read_text(encoding='utf-8')
        assert '.purge_deleted_tasks(' not in path.read_text(encoding='utf-8')

def test_cross_language_vectors():
    vectors=json.loads((Path(__file__).parent/'vectors'/'cloud_v1.json').read_text(encoding='utf-8'))
    for case in vectors:
        raw=bytes.fromhex(case['input_hex'])
        if not case['valid']:
            with pytest.raises(ValueError):validate_request(decode(raw))
        else:
            value=validate_request(decode(raw));assert encode(value).hex()==case['canonical_hex'];assert digest(value)==case['sha256']

def test_migration6_failure_rolls_back_and_retries(tmp_path,monkeypatch):
    from app.database import migrations,cloud_schema
    db=Database(tmp_path/'data'/'sitetask.db');all_migrations=migrations.MIGRATIONS
    monkeypatch.setattr(migrations,'MIGRATIONS',all_migrations[:5]);migrations.apply_migrations(db)
    monkeypatch.setattr(migrations,'MIGRATIONS',all_migrations);real=cloud_schema.apply_cloud_schema
    def fail(c):real(c);raise RuntimeError('injected failure')
    monkeypatch.setattr(cloud_schema,'apply_cloud_schema',fail)
    with pytest.raises(RuntimeError):migrations.apply_migrations(db)
    with db.transaction() as c:
        assert c.execute('PRAGMA user_version').fetchone()[0]==5
        assert not c.execute("SELECT 1 FROM sqlite_master WHERE name='task_versions'").fetchone()
    monkeypatch.setattr(cloud_schema,'apply_cloud_schema',real);assert migrations.apply_migrations(db)==(6,)

def test_m5_build_refuses_schema6(store):
    from tests.fixtures import legacy_migrations_v5
    with pytest.raises(legacy_migrations_v5.DatabaseTooNewError):legacy_migrations_v5.apply_migrations(store.database)

def test_reconcile_is_fenced_and_retryable(store):
    a=store.execute(delivery(store,request()));identity=store.identity();rid=str(uuid.uuid4());store.prepare_reconcile(rid)
    response={'reconcile_id':rid,'epoch':identity['epoch']+1,'acked':1000,'max_task_id':500}
    store.apply_reconcile(response);store.apply_reconcile(response)
    with pytest.raises(sqlite3.IntegrityError):store.repository.create_task(Task(title='fenced',due_date=date.today()))
    store.release_fence(response['epoch'],1000,500)
    task=store.repository.create_task(Task(title='new safe id',due_date=date.today()));assert task.id>500

def test_recovery_refuses_a_forked_identity_without_changing_tasks(store):
    a=store.execute(delivery(store,request()));before=dict(row(store,a['task_id']));rid=str(uuid.uuid4());store.prepare_reconcile(rid)
    item=store.snapshot()['items'][0];item['created_at']='2000-01-01T00:00:00+00:00'
    with pytest.raises(ValueError,match='fork'):store.apply_reconcile({'reconcile_id':rid,'epoch':2,'acked':100,'max_task_id':100},[item])
    assert dict(row(store,a['task_id']))==before and store.identity()['epoch']==1

def test_bridge_token_logs_are_redacted():
    import logging
    from app.services.logging_service import RedactingFormatter
    secret='stb_'+'a'*16+'_'+'x'*43
    for message in [secret,'Authorization: Bearer '+secret,'Bearer '+secret]:
        text=RedactingFormatter().format(logging.LogRecord('x',logging.INFO,'',1,message,(),None))
        assert secret not in text and 'x'*43 not in text

def test_local_ui_conflict_mapping_preserves_content_and_clears_reference(store):
    from app.services.local_recovery import conflict_plan,apply_confirmed_mapping
    a=store.execute(delivery(store,request()));original=dict(row(store,a['task_id']));store.fence()
    plan=conflict_plan(store.database,[{'task_id':a['task_id'],'lifecycle':'tombstone'}])
    mapping=apply_confirmed_mapping(store.repository,plan,100)
    assert mapping==[{'old_task_id':a['task_id'],'new_task_id':101}]
    new=row(store,101);assert new['title']==original['title'] and new['source_reference'] is None
    assert row(store,a['task_id']) is None
    with store.database.transaction() as c:
        assert c.execute('SELECT fenced FROM cloud_state').fetchone()[0]==1
        assert c.execute('SELECT 1 FROM task_tombstones WHERE task_id=?',(a['task_id'],)).fetchone()
