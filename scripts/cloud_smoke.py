"""Exercise the real Qt controller against wrangler dev on loopback only."""
import sys,json,time,uuid,urllib.request,sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from app.database.connection import Database
from app.database.task_repository import TaskRepository
from app.services.local_queue import LocalTaskQueue
from app.services.cloud_store import CloudStore
from app.services.cloud_bridge import CloudBridgeController
from app.utils.paths import AppPaths

root=Path(sys.argv[2]).resolve();paths=AppPaths(root/'app');paths.ensure_runtime_directories()
app=QApplication.instance() or QApplication([])
repo=TaskRepository(Database(paths.database_file));store=CloudStore(repo)
if sys.argv[1]=='init':
    root.mkdir(parents=True,exist_ok=True);(root/'identity.json').write_text(json.dumps(store.identity()),encoding='utf-8');print('Local synthetic database initialized.');sys.exit(0)
creds=json.loads((root/'credentials.json').read_text())
class Credentials:
    def token(self):return creds['bridge']
    def guard(self,path):return 'paired'
    def set_guard(self,path):pass
queue=LocalTaskQueue(repo,paths.root)
origin=sys.argv[3] if len(sys.argv)>3 else 'http://127.0.0.1:8787'
controller=CloudBridgeController(repo,paths,queue,credentials=Credentials(),local_test=origin.startswith('http://'))
controller.start(origin)
(paths.config_dir/'cloud_bridge.json').write_text(json.dumps({'version':1,'enabled':True,'origin':origin}))
def api(path,payload=None,kind='assistant'):
    req=urllib.request.Request(origin+path,data=json.dumps(payload,ensure_ascii=False).encode() if payload is not None else None,
        headers={'Authorization':'Bearer '+creds[kind],'Content-Type':'application/json','User-Agent':'SiteTaskAI/1.3'})
    with urllib.request.urlopen(req,timeout=10) as response:return json.load(response)
def wait(predicate,timeout=45):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        app.processEvents();controller.cycle()
        if predicate():return
        time.sleep(.04)
    raise AssertionError('Timed out; bridge status='+controller.status+' phase='+controller.phase)
def command(op,target=None,revision=None,fields=None):
    r=dict(v=1,command_id=str(uuid.uuid4()),op=op,target=target,base_revision=revision,fields=fields,reason=None)
    api('/v1/commands',r);answer={}
    def complete():
        nonlocal answer
        answer=api('/v1/commands/'+r['command_id']);return answer['state'] in ('applied','rejected','conflict')
    wait(complete);return r,answer['receipt']
try:
    wait(lambda:controller.status=='connected' and controller.synced>=0)
    probe=dict(v=1,command_id=str(uuid.uuid4()),op='create',target=None,base_revision=None,
        fields=dict(title='Concurrent lease probe',description='Synthetic',due_date=None,no_due=True,category='Other',priority='normal'),reason=None)
    api('/v1/commands',probe)
    pull={**controller._identity(),'credits':4}
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(lambda _:api('/v1/bridge/pull',pull,'bridge'),range(2)))
    leases=[lease for result in responses for lease in result['leases']]
    assert len(leases)==1,'concurrent pulls duplicated a lease'
    queue.execute_cloud(leases[0]);wait(lambda:api('/v1/commands/'+probe['command_id'])['state']=='applied')
    r,a=command('create',fields=dict(title='Local bridge smoke 😀',description='Synthetic test only',due_date='2026-10-28',no_due=False,category='Other',priority='normal'))
    assert a['status']=='applied',a
    tid=a['task_id'];assert repo.get_task(tid).title=='Local bridge smoke 😀'
    # Same immutable request must never create a second task.
    count=len(repo.list_all_tasks());api('/v1/commands',r);assert len(repo.list_all_tasks())==count
    for op in ('complete','reopen','soft_delete','restore'):
        _,a=command(op,{'task_id':tid},a['business_revision']);assert a['status']=='applied',(op,a)
    _,conflict=command('update',{'task_id':tid},'0'*64,{'title':'must not write'})
    assert conflict['status']=='conflict'
    _,a=command('get',{'task_id':tid});assert a['snapshot']['title']=='Local bridge smoke 😀'
    wait(lambda:controller.synced==store.identity()['max_change_seq'])
    mirrored=api('/v1/tasks')['items'];assert any(i['task_id']==tid and i['content']['title']=='Local bridge smoke 😀' for i in mirrored)
    with store.database.transaction() as c:c.execute('DELETE FROM task_changes')
    controller.synced=-1;wait(lambda:controller.synced==store.identity()['max_change_seq'])
    backup=root/'restore-test.db'
    with sqlite3.connect(paths.database_file) as source,sqlite3.connect(backup) as target:source.backup(target)
    _,a=command('complete',{'task_id':tid},a['business_revision']);assert a['status']=='applied'
    wait(lambda:controller.synced==store.identity()['max_change_seq'] and not store.outbox())
    controller.stop()
    with sqlite3.connect(backup) as source,sqlite3.connect(paths.database_file) as target:source.backup(target)
    controller.recover()
    wait(lambda:controller.status=='connected' and controller.phase=='ready' and controller.synced==store.identity()['max_change_seq'])
    assert repo.get_task(tid).status=='completed'
    assert store.identity()['epoch']>=2
    report={'result':'passed','cases':['enroll','Qt outbound HTTP','create','idempotent replay','complete','reopen','soft delete','restore','revision conflict','get','mirror generation','generation after log pruning'],'tasks':len(repo.list_all_tasks())}
    report['cases'].append('backup restore fence and explicit reconcile')
    report['cases'].append('concurrent HTTP pulls issue one lease')
    print(json.dumps(report),flush=True);(root/'smoke-result.json').write_text(json.dumps(report,indent=2))
finally:
    controller.stop();queue.close()
    assert not controller.thread.isRunning(),'network thread did not stop'
    print('Qt network thread stopped cleanly.',flush=True)
