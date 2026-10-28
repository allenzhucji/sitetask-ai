"""Main-thread controller and the shared inbox/cloud execution gate."""
import json
import time
import uuid
from copy import deepcopy
from PySide6.QtCore import QObject, Signal, Slot, QThread, Qt, QEventLoop, QTimer
from app.services.cloud_store import CloudStore
from app.services.cloud_network import CloudNetworkWorker,validate_origin
from app.services.cloud_credentials import CloudCredentials
from app.services.local_identity import LocalIdentityService,IdentityStatus
from scripts.task_queue import atomic_json,encode

class CloudBridgeController(QObject):
    request_ready=Signal(int,str,object)
    stop_requested=Signal()
    status_changed=Signal(str)
    def __init__(self,repository,paths,queue,parent=None,credentials=None,*,local_test=False):
        super().__init__(parent);self.paths=paths;self.queue=queue;self.store=CloudStore(repository)
        self.credentials=credentials or CloudCredentials();self.local_test=local_test
        self.identity_service=LocalIdentityService(paths,repository.database)
        self.thread=None;self.worker=None;self.pending=[];self.voided=set();self.serial=0;self.inflight=None
        self.enabled=False;self.stopping=False;self.status='disabled';self.retry_at=0.;self.last_sync=0.;self.synced=-1
        self.instance=None;self.origin=None;self.phase='enroll';self.generation=None;self.snapshot=None;self.chunks=[]
        self.recovery=None;self.recovery_items=[];self.recovery_after=0
        self.in_cycle=False
        self.queue.cloud_enabled=False

    def set_status(self,s):self.status=s;self.status_changed.emit(s)
    def config(self):
        p=self.paths.config_dir/'cloud_bridge.json'
        return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {'enabled':False}

    def startup(self):
        try:
            with self.store.database.transaction() as c:previous=c.execute('SELECT enabled FROM cloud_state').fetchone()[0]
            if previous:self.store.fence()
            cfg=self.config();guard=self.credentials.guard(self.store.database.path)
            if guard or cfg.get('enabled') or previous:
                self.store.fence();self.set_status('waiting_for_identity_check')
            if not cfg.get('enabled'):return
            self.start(cfg['origin'])
        except Exception:
            # Config/credential errors never silently enable a connection.
            self.store.fence()
            self.set_status('credential_or_config_unavailable')

    def configure(self,origin,token):
        origin=validate_origin(origin,local_test=self.local_test)
        self.stop()
        if self.thread and self.thread.isRunning():raise ValueError('bridge_still_stopping')
        self.store.fence();self.credentials.set_guard(self.store.database.path)
        if token:self.credentials.set_token(token)
        if not self.credentials.token():raise ValueError('credential_unavailable')
        atomic_json(self.paths.config_dir/'cloud_bridge.json',{'version':1,'enabled':True,'origin':origin})
        self.start(origin)

    def start(self,origin):
        token=self.credentials.token()
        if not token:raise ValueError('credential_unavailable')
        self.store.fence()
        check=self.identity_service.check()
        if check.status not in (IdentityStatus.NEW,IdentityStatus.PAIRED):
            self.set_status('restore_fenced:'+str(check.status));return
        check=self.identity_service.record(check);self.instance=check.recorded
        self.origin=validate_origin(origin,local_test=self.local_test)
        self.enabled=True;self.stopping=False;self.queue.cloud_enabled=True;self.phase='enroll';self.retry_at=0;self.synced=-1
        self.thread=QThread(self);self.worker=CloudNetworkWorker(self.origin,token,self.local_test)
        self.worker.moveToThread(self.thread)
        self.request_ready.connect(self.worker.request,Qt.ConnectionType.QueuedConnection)
        self.stop_requested.connect(self.worker.stop,Qt.ConnectionType.QueuedConnection)
        self.worker.response.connect(self._response,Qt.ConnectionType.QueuedConnection)
        self.worker.stopped.connect(self.thread.quit,Qt.ConnectionType.DirectConnection)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.start();self.set_status('connecting')

    def recover(self):
        """Explicit local UI action; retries retain the same recovery id across restarts."""
        self.stop()
        if self.thread and self.thread.isRunning():raise ValueError('bridge_still_stopping')
        self.store.fence()
        recorded=self.identity_service._read_record()
        if not recorded or recorded['db_id']!=self.store.identity()['db_id']:raise ValueError('manual_database_reenrollment_required')
        cfg=self.config();token=self.credentials.token()
        if not token:raise ValueError('credential_unavailable')
        with self.store.database.transaction() as c:state=dict(c.execute('SELECT * FROM cloud_state').fetchone())
        rid=state['reconcile_id'] if state['reconcile_phase'] in ('prepared','local_applied') else str(uuid.uuid4())
        self.store.prepare_reconcile(rid);self.recovery={'reconcile_id':rid}
        self.instance=recorded;self.origin=validate_origin(cfg['origin'],local_test=self.local_test)
        self.enabled=True;self.stopping=False;self.queue.cloud_enabled=True;self.phase='reconcile';self.retry_at=0
        self.recovery_items=[];self.recovery_after=0
        self.thread=QThread(self);self.worker=CloudNetworkWorker(self.origin,token,self.local_test);self.worker.moveToThread(self.thread)
        self.request_ready.connect(self.worker.request,Qt.ConnectionType.QueuedConnection)
        self.stop_requested.connect(self.worker.stop,Qt.ConnectionType.QueuedConnection)
        self.worker.response.connect(self._response,Qt.ConnectionType.QueuedConnection)
        self.worker.stopped.connect(self.thread.quit,Qt.ConnectionType.DirectConnection)
        self.thread.finished.connect(self.worker.deleteLater);self.thread.start();self.set_status('reconciling')

    def pause(self):
        self.stop();cfg=self.config();cfg['enabled']=False;atomic_json(self.paths.config_dir/'cloud_bridge.json',cfg)
        self.set_status('paused')

    def _identity(self):
        return {**self.store.identity(),'instance_id':self.instance['instance_id']}

    def _send(self,path,payload):
        self.serial+=1;self.inflight=(self.serial,path);self.request_ready.emit(self.serial,path,deepcopy(payload))

    def _begin_sync(self):
        self.snapshot=self.store.snapshot();self.generation=str(uuid.uuid4());self.chunks=[];chunk=[]
        for item in self.snapshot['items']:
            if chunk and (len(chunk)>=100 or len(encode(chunk+[item]))>120*1024):self.chunks.append(chunk);chunk=[]
            chunk.append(item)
        if chunk:self.chunks.append(chunk)
        self.phase='generation/start'

    def cycle(self):
        if self.in_cycle:return
        self.in_cycle=True
        try:
            with self.store.database.transaction() as c:fenced=c.execute('SELECT enabled AND fenced FROM cloud_state').fetchone()[0]
            self.queue.processed=0
            if not fenced:self.queue.tick()
            if not self.enabled:return
            if not self.queue._initialize() or not self.queue.lock.isLocked():
                self.pending=[];self.set_status('integration_lock_unavailable');return
            if self.queue.busy():
                self._network_cycle();return
            budget=max(0,4-getattr(self.queue,'processed',0))
            while self.pending and budget and not self.queue.busy() and not fenced:
                delivery=self.pending.pop(0)
                result=self.queue.execute_cloud(delivery,self.voided);budget-=1;self.queue.changed()
                self.identity_service.record()
                if result['status']!='applied':self.pending=[];break
            self._network_cycle()
        except Exception as error:
            self.pending=[];self.set_status('retrying:'+type(error).__name__);self.retry_at=time.monotonic()+5
        finally:
            self.in_cycle=False

    def _network_cycle(self):
        if self.inflight or time.monotonic()<self.retry_at:return
        ident=self._identity()
        if self.phase=='reconcile':
            self._send('/v1/bridge/reconcile',{**ident,**self.recovery,'strategy':'preserve-identities'});return
        if self.phase=='reconcile/state':
            self._send('/v1/bridge/reconcile/state',{**ident,'epoch':self.recovery['epoch'],'reconcile_id':self.recovery['reconcile_id'],'after':self.recovery_after});return
        if self.phase=='enroll':
            self._send('/v1/bridge/enroll',{**ident,'install_fingerprint':self.instance['install_fingerprint']});return
        if self.phase=='verify':
            self._send('/v1/bridge/pull',{**ident,'credits':0});return
        if self.phase.startswith('generation/'):
            base={**ident,'generation':self.generation}
            if self.phase.endswith('start'):base.update({k:self.snapshot[k] for k in ('as_of','expected_count','manifest_sha256')})
            elif self.phase.endswith('items'):base['items']=self.chunks[0]
            self._send('/v1/bridge/'+self.phase,base);return
        receipts=self.store.outbox()
        if receipts:self._send('/v1/bridge/receipts',{**ident,'receipts':receipts});return
        if self.pending:
            self._send('/v1/bridge/lease/renew',{**ident,'lease_ids':[x['lease_id'] for x in self.pending]});self.retry_at=time.monotonic()+30;return
        if self.synced!=ident['max_change_seq'] or time.monotonic()-self.last_sync>86400:
            self._begin_sync();self._network_cycle();return
        self._send('/v1/bridge/pull',{**ident,'credits':4});self.retry_at=time.monotonic()+5

    @Slot(int,int,str,object)
    def _response(self,serial,status,error,value):
        if self.stopping or not self.inflight or serial!=self.inflight[0]:return
        path=self.inflight[1];self.inflight=None
        if error or status not in (200,202):
            self.pending=[];code=error or value.get('error','http_error')
            self.set_status(str(code));self.retry_at=time.monotonic()+10
            if path.startswith('/v1/bridge/generation/') and code in ('generation_missing','generation_incomplete','generation_reused','duplicate_item_conflict'):
                self.phase='ready';self.synced=-1;return
            if status in (401,403,409):self.store.fence();self.enabled=False;self.queue.cloud_enabled=False
            return
        try:
            if path.endswith('/reconcile'):
                self.recovery=value;self.phase='reconcile/state'
            elif path.endswith('/reconcile/state'):
                self.recovery_items.extend(value['items']);self.recovery_after=value['next_after']
                if self.recovery_after is None:
                    self.store.apply_reconcile(self.recovery,self.recovery_items)
                    # Atomic outside checkpoint, written only after the durable local recovery commit.
                    identity=self.store.identity()
                    checkpoint={**self.instance,'epoch':identity['epoch'],'last_change_seq_seen':identity['max_change_seq'],'max_task_id_seen':identity['max_task_id']}
                    atomic_json(self.identity_service.identity_file,checkpoint);self.instance=checkpoint
                    self._begin_sync()
            elif path.endswith('/enroll'):self.phase='verify'
            elif path.endswith('/pull'):
                self.store.release_fence(value['epoch'],value['acked'],value['max_task_id'])
                self.voided.update(value.get('voided',[]))
                if self.phase=='verify':self.phase='ready'
                leases=value.get('leases',[])
                if len(leases)>4 or len(encode(leases))>192*1024:raise ValueError('pending_limit')
                # Probe all recent commits before accepting a new batch.
                with self.store.database.transaction() as c:
                    for cid in value.get('recent_applied_ids',[]):
                        if not c.execute("SELECT 1 FROM local_queue_commands WHERE command_id=? AND channel='cloud'",(cid,)).fetchone():raise ValueError('restore_detected')
                self.pending=leases;self.set_status('connected')
            elif path.endswith('/receipts'):self.store.acknowledge_receipts(value['acknowledged'])
            elif path.endswith('/renew'):
                self.voided.update(value.get('voided',[]));renewed={x['command_id']:x['lease_until'] for x in value['renewed']}
                self.pending=[{**x,'lease_until':renewed[x['envelope']['command_id']]} for x in self.pending if x['envelope']['command_id'] in renewed]
            elif path.endswith('/start'):self.phase='generation/items' if self.chunks else 'generation/finalize'
            elif path.endswith('/items'):
                self.chunks.pop(0);self.phase='generation/items' if self.chunks else 'generation/finalize'
            elif path.endswith('/finalize'):
                self.synced=self.snapshot['as_of'];self.last_sync=time.monotonic();self.phase='ready';self.snapshot=None
                self.store.release_fence(value['epoch'],value['acked'],value['max_task_id'])
                with self.store.database.transaction() as c:c.execute("UPDATE cloud_state SET reconcile_phase='complete' WHERE reconcile_id IS NOT NULL")
                self.store.prune(value['acked']);self.identity_service.record();self.set_status('connected')
        except Exception as error:
            self.pending=[];self.store.fence();self.enabled=False
            self.set_status('manual_fork_mapping_required' if str(error)=='manual_fork_mapping_required' else 'restore_or_protocol_fenced')

    def stop(self):
        self.stopping=True;self.enabled=False;self.queue.cloud_enabled=False;self.pending=[];self.serial+=1;self.inflight=None
        if self.thread and self.thread.isRunning():
            self.stop_requested.emit();loop=QEventLoop();self.thread.finished.connect(loop.quit)
            QTimer.singleShot(5000,loop.quit);loop.exec()
            if self.thread.isRunning():self.set_status('waiting_for_network_shutdown');return
        # Keep Python wrappers alive until Qt has delivered deferred deletions.
        # A subsequent connection creates a new worker; old signals auto-disconnect.
