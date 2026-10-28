"""Main-thread bridge transactions, durable deduplication and consistent snapshots."""
import json
from datetime import date, datetime, timedelta, timezone
from app.models.task import Task
from app.services.local_queue import _TransactionRepository
from app.services.cloud_protocol import business_revision, validate_envelope, utcnow, stamp
from scripts.task_queue import SUPPRESSED, encode, digest

def sequence(c,name):
    row=c.execute('SELECT seq FROM sqlite_sequence WHERE name=?',(name,)).fetchone()
    return row[0] if row else 0

def task_item(c,row,now):
    task=dict(row)
    life=dict(c.execute('SELECT * FROM task_lifecycle WHERE task_id=?',(row['id'],)).fetchone())
    version=c.execute('SELECT change_seq FROM task_versions WHERE task_id=?',(row['id'],)).fetchone()[0]
    active=row['status']!='completed' and row['deleted_at'] is None
    visible=active or (not life['cloud_excluded'] and life['retention_deadline'] and life['retention_deadline']>now and not life['content_expired_at'])
    return dict(task_id=row['id'],change_seq=version,business_revision=business_revision(row),
        lifecycle='active' if active else 'inactive',status=row['status'],deleted=row['deleted_at'] is not None,
        source_reference=row['source_reference'],created_at=row['created_at'],episode=life['episode'],retention_deadline=life['retention_deadline'],
        inactive_since=life['inactive_since'],content=task if visible else None,
        episode_deadlines={str(x[0]):x[1] for x in c.execute('SELECT episode,deadline FROM cloud_episodes WHERE task_id=?',(row['id'],))})

class CloudStore:
    def __init__(self,repository):
        self.repository=repository
        self.database=repository.database

    def identity(self):
        with self.database.transaction() as c:
            c.execute('BEGIN')
            row=dict(c.execute('SELECT * FROM local_identity WHERE singleton=1').fetchone())
            return dict(db_id=row['db_id'],epoch=row['epoch'],max_change_seq=sequence(c,'task_changes'),max_task_id=sequence(c,'tasks'))

    def fence(self, enabled=True):
        with self.database.transaction() as c:
            c.execute('UPDATE cloud_state SET enabled=?,fenced=? WHERE singleton=1',(int(enabled),int(enabled)))

    def release_fence(self,epoch,acked,max_task_id):
        with self.database.transaction() as c:
            c.execute('BEGIN IMMEDIATE')
            current=c.execute('SELECT epoch FROM local_identity WHERE singleton=1').fetchone()[0]
            if epoch!=current or acked>sequence(c,'task_changes') or max_task_id>sequence(c,'tasks'):
                raise ValueError('restore_detected')
            c.execute('UPDATE cloud_state SET fenced=0 WHERE singleton=1')

    def execute(self,delivery,voided=()):
        e=validate_envelope(delivery['envelope'])
        r=e['request']; cid=e['command_id']; now=utcnow()
        with self.database.transaction() as c:
            c.execute('BEGIN IMMEDIATE')
            identity=c.execute('SELECT * FROM local_identity WHERE singleton=1').fetchone()
            if e['db_id']!=identity['db_id'] or delivery['epoch']!=identity['epoch']: raise ValueError('wrong_database_or_epoch')
            if c.execute('SELECT fenced FROM cloud_state').fetchone()[0]: raise ValueError('restore_fenced')
            old=c.execute('SELECT * FROM local_queue_commands WHERE command_id=?',(cid,)).fetchone()
            if old:
                if old['channel']!='cloud' or old['actor_token_id']!=e['actor']['token_id'] or old['request_sha256']!=e['request_sha256']:
                    raise ValueError('command_id_reused')
                receipt=json.loads(old['result_json'])
                receipt=self._redact(c,receipt,now)
                c.execute('INSERT OR IGNORE INTO cloud_receipt_outbox VALUES (?,?,?)',(cid,encode(receipt).decode(),now))
                return receipt
            reason=None
            if cid in voided: reason='voided'
            elif now>=stamp(e['execute_before']): reason='expired_deadline'
            elif now>=stamp(delivery['lease_until']): raise ValueError('lease_expired')
            if reason: result=dict(status='rejected',result_code=reason)
            else: result=self._apply(c,e,now)
            receipt=dict(rv=1,db_id=identity['db_id'],epoch=identity['epoch'],command_id=cid,
                request_sha256=e['request_sha256'],lease_id=delivery['lease_id'],lease_gen=delivery['lease_gen'],
                processed_at=now,task_id=None,business_revision=None,change_seq=None,snapshot=None,
                episode=None,record_deadline=(datetime.fromisoformat(now.replace('Z','+00:00'))+timedelta(days=30)).isoformat(timespec='milliseconds').replace('+00:00','Z'),**{})
            receipt.update(result)
            receipt['result_sha256']=digest({k:receipt[k] for k in ('command_id','status','result_code','task_id','business_revision','change_seq')})
            receipt=self._redact(c,receipt,now)
            # Never persist task content twice: ledger holds only immutable metadata;
            # the expiring outbox contains the one temporary snapshot copy.
            metadata={**receipt,'snapshot':None}
            c.execute('''INSERT INTO local_queue_commands(command_id,payload_sha256,result_json,processed_at,channel,actor_token_id,request_sha256)
                VALUES(?,?,?,?,'cloud',?,?)''',(cid,e['request_sha256'],encode(metadata).decode(),now,e['actor']['token_id'],e['request_sha256']))
            c.execute('INSERT INTO cloud_receipt_outbox VALUES (?,?,?)',(cid,encode(receipt).decode(),now))
            return receipt

    def _apply(self,c,e,now):
        r=e['request']; op=r['op']; target=r['target']
        ref=e['assigned_source_reference'] if op=='create' else (target.get('source_reference') if target else None)
        rows=c.execute('SELECT * FROM tasks WHERE source_reference=?' if ref else 'SELECT * FROM tasks WHERE id=?',
                       (ref or target['task_id'],)).fetchall()
        if len(rows)>1: return dict(status='conflict',result_code='ambiguous_source_reference',match_count=len(rows))
        row=rows[0] if rows else None
        if ref in SUPPRESSED or (row and row['source_reference'] in SUPPRESSED):
            return dict(status='rejected',result_code='protected_reference')
        if row is None:
            tomb=c.execute('SELECT 1 FROM task_tombstones WHERE source_reference=?' if ref else 'SELECT 1 FROM task_tombstones WHERE task_id=?',
                           (ref or target['task_id'],)).fetchone()
            if tomb: return dict(status='rejected',result_code='purged')
            if op!='create': return dict(status='rejected',result_code='not_found')
        repo=_TransactionRepository(c,self.repository.clock)
        status='applied'; code='found'
        if row and op not in ('get','create'):
            if op in ('update','complete','reopen') and row['deleted_at'] is not None: status,code='rejected','task_deleted'
            elif op in ('update','complete','reopen') and row['status']=='cancelled': status,code='rejected','task_cancelled'
            elif business_revision(row)!=r['base_revision']: status,code='conflict','revision_changed'
        if status=='applied':
            if op in ('create','update'):
                if op=='create' and row: code='existing'
                elif op=='update' and row['status']!='pending': status,code='rejected','task_closed'
                else:
                    fields=dict(r['fields'])
                    if 'due_date' in fields:
                        fields['due_date']=date(2000,1,1) if fields['no_due'] else date.fromisoformat(fields['due_date'])
                        fields['due_time']=None
                    if op=='create':
                        task=repo.create_task(Task(**fields,source_reference=ref,created_at=self.repository.clock(),updated_at=self.repository.clock()))
                    else: task=repo.update_task(Task.model_validate({**dict(row),**fields}))
                    row=c.execute('SELECT * FROM tasks WHERE id=?',(task.id,)).fetchone()
                    code='created' if op=='create' else 'updated'
            elif op=='complete':
                if row['status']=='completed': code='noop_completed'
                else: repo.complete_task(row['id']); code='completed'
            elif op=='reopen':
                if row['status']=='pending': code='noop_pending'
                else: repo.restore_task(row['id']); code='reopened'
            elif op=='soft_delete':
                if row['deleted_at']: code='noop_deleted'
                else: repo.soft_delete_task(row['id'],e['actor']['token_id']); code='soft_deleted'
            elif op=='restore':
                if not row['deleted_at']: code='noop_restored'
                else: repo.undelete_task(row['id']); code='restored'
        item=task_item(c,c.execute('SELECT * FROM tasks WHERE id=?',(row['id'],)).fetchone(),now)
        return dict(status=status,result_code=code,task_id=item['task_id'],business_revision=item['business_revision'],
            change_seq=item['change_seq'],snapshot=item['content'],episode=item['episode'],
            task_deadline=item['retention_deadline'])

    @staticmethod
    def _redact(c,receipt,now):
        receipt=dict(receipt)
        limits=[receipt['record_deadline']]
        if receipt.get('task_deadline'): limits.append(receipt['task_deadline'])
        if receipt.get('task_id') is not None:
            # A copy made while active belongs to the next inactive episode too.
            rows=c.execute('SELECT deadline FROM cloud_episodes WHERE task_id=? AND episode>=?',
                           (receipt['task_id'],receipt.get('episode') or 0)).fetchall()
            limits.extend(row[0] for row in rows)
            if c.execute('SELECT 1 FROM task_tombstones WHERE task_id=?',(receipt['task_id'],)).fetchone():
                receipt['snapshot']=None
        receipt['record_deadline']=min(limits)
        if now>=receipt['record_deadline']: receipt['snapshot']=None
        return receipt

    def outbox(self):
        now=utcnow()
        with self.database.transaction() as c:
            receipts=[self._redact(c,json.loads(row[0]),now) for row in c.execute('SELECT receipt_json FROM cloud_receipt_outbox ORDER BY created_at LIMIT 4')]
            for r in receipts: c.execute('UPDATE cloud_receipt_outbox SET receipt_json=? WHERE command_id=?',(encode(r).decode(),r['command_id']))
            return receipts

    def acknowledge_receipts(self,ids):
        with self.database.transaction() as c:
            c.executemany('DELETE FROM cloud_receipt_outbox WHERE command_id=?',((i,) for i in ids))

    def snapshot(self):
        now=utcnow()
        with self.database.transaction() as c:
            c.execute('BEGIN')
            identity=dict(c.execute('SELECT * FROM local_identity').fetchone())
            items=[task_item(c,row,now) for row in c.execute('SELECT * FROM tasks ORDER BY id')]
            for row in c.execute('SELECT * FROM task_tombstones ORDER BY task_id'):
                items.append(dict(task_id=row['task_id'],change_seq=row['change_seq'],business_revision=None,lifecycle='tombstone',
                    kind=row['kind'],source_reference=row['source_reference'],episode=row['episode'] or 0,
                    retention_deadline=row['retention_deadline'],inactive_since=row['inactive_since'],content=None))
            items.sort(key=lambda i:i['task_id'])
            manifest=[[i[k] for k in ('task_id','change_seq','business_revision','lifecycle')] for i in items]
            return dict(db_id=identity['db_id'],epoch=identity['epoch'],as_of=sequence(c,'task_changes'),
                expected_count=len(items),manifest_sha256=digest(manifest),items=items,max_task_id=sequence(c,'tasks'))

    def prune(self,acked):
        cutoff=(datetime.now(timezone.utc)-timedelta(days=30)).isoformat(timespec='milliseconds').replace('+00:00','Z')
        with self.database.transaction() as c:
            c.execute('DELETE FROM task_changes WHERE change_seq<=? AND changed_at<?',(acked,cutoff))
            c.execute('DELETE FROM task_state_events WHERE at<?',(cutoff,))

    def prepare_reconcile(self,request_id):
        with self.database.transaction() as c:
            c.execute("UPDATE cloud_state SET enabled=1,fenced=1,reconcile_id=?,reconcile_phase='prepared'",(request_id,))

    def apply_reconcile(self,response,metadata=()):
        with self.database.transaction() as c:
            c.execute('BEGIN IMMEDIATE')
            state=c.execute('SELECT * FROM cloud_state').fetchone()
            if not state['fenced'] or response['reconcile_id']!=state['reconcile_id']: raise ValueError('reconcile_mismatch')
            for item in metadata:
                local=c.execute('SELECT * FROM tasks WHERE id=?',(item['task_id'],)).fetchone()
                if not local:continue
                if item['lifecycle']=='tombstone' or not item.get('created_at') or item['created_at']!=local['created_at']:
                    raise ValueError('manual_fork_mapping_required')
                # A restored backup cannot undo cloud-known completion/deletion or reset an episode.
                if item['lifecycle']=='inactive':
                    deleted=local['deleted_at'] or item.get('inactive_since') or utcnow() if item.get('deleted') else local['deleted_at']
                    status='completed' if item.get('status')=='completed' else local['status']
                    c.execute('UPDATE tasks SET status=?,deleted_at=? WHERE id=?',(status,deleted,item['task_id']))
                life=c.execute('SELECT * FROM task_lifecycle WHERE task_id=?',(item['task_id'],)).fetchone()
                deadlines=[d for d in (life['retention_deadline'],item.get('retention_deadline')) if d]
                inactive=[d for d in (life['inactive_since'],item.get('inactive_since')) if d]
                if item['lifecycle']=='inactive':
                    c.execute('UPDATE task_lifecycle SET inactive_since=? WHERE task_id=?',(min(inactive) if inactive else None,item['task_id']))
                c.execute('UPDATE task_lifecycle SET episode=MAX(episode,?),retention_deadline=?,cloud_excluded=MAX(cloud_excluded,?),content_expired_at=COALESCE(content_expired_at,?) WHERE task_id=?',
                    (item['episode'],min(deadlines) if deadlines else None,int(item.get('content_expired',False)),utcnow() if item.get('content_expired') else None,item['task_id']))
                for ep,deadline in item.get('episode_deadlines',{}).items():
                    c.execute('INSERT INTO cloud_episodes VALUES(?,?,?) ON CONFLICT(task_id,episode) DO UPDATE SET deadline=MIN(deadline,excluded.deadline)',(item['task_id'],int(ep),deadline))
            for table,upper in [('tasks',response['max_task_id']),('task_changes',response['acked'])]:
                if not c.execute('SELECT 1 FROM sqlite_sequence WHERE name=?',(table,)).fetchone():
                    c.execute('INSERT INTO sqlite_sequence VALUES (?,?)',(table,upper))
                else: c.execute('UPDATE sqlite_sequence SET seq=MAX(seq,?) WHERE name=?',(upper,table))
            c.execute('UPDATE local_identity SET epoch=?',(response['epoch'],))
            c.execute('DELETE FROM cloud_receipt_outbox')
            # Rebaseline every identity above the recovered watermark, preserving versions after pruning.
            for row in c.execute('SELECT id FROM tasks').fetchall():
                c.execute("INSERT INTO task_changes(task_id,kind,changed_at) VALUES (?,'baseline',?)",(row[0],utcnow()))
            c.execute("UPDATE cloud_state SET reconcile_phase='local_applied',acked=0")
            # Fence stays set until checkpoint + generation are acknowledged.
