"""Explicit LOCAL UI recovery mapping. Never called by cloud execution/transport."""
from app.models.task import Task
from app.services.local_queue import _TransactionRepository
from app.services.cloud_protocol import business_revision

def conflict_plan(database,metadata):
    plan=[]
    with database.transaction() as c:
        for item in metadata:
            row=c.execute('SELECT * FROM tasks WHERE id=?',(item['task_id'],)).fetchone()
            if row and (item['lifecycle']=='tombstone' or not item.get('created_at') or item['created_at']!=row['created_at']):
                plan.append({'task_id':row['id'],'title':row['title'],'revision':business_revision(row)})
    return plan

def apply_confirmed_mapping(repository,plan,cloud_max_task_id):
    """Preserve local contents under fresh IDs; retain tombstones for old identities.

    The caller is the local confirmation dialog. All state changes roll back
    together. Clearing managed references keeps the inbox's old baseline protected.
    """
    if not plan:raise ValueError('empty_mapping')
    mapping=[]
    with repository.database.transaction() as c:
        c.execute('BEGIN IMMEDIATE')
        if not c.execute('SELECT enabled AND fenced FROM cloud_state').fetchone()[0]:raise ValueError('recovery_not_fenced')
        originals=[]
        for p in plan:
            row=c.execute('SELECT * FROM tasks WHERE id=?',(p['task_id'],)).fetchone()
            if not row or business_revision(row)!=p['revision']:raise ValueError('mapping_changed_review_again')
            originals.append(row)
        c.execute("UPDATE sqlite_sequence SET seq=MAX(seq,?) WHERE name='tasks'",(cloud_max_task_id,))
        c.execute('UPDATE cloud_state SET fenced=0')
        repo=_TransactionRepository(c,repository.clock)
        for row in originals:
            values=dict(row);old_id=values.pop('id');deleted=values.pop('deleted_at');values.pop('deleted_by',None)
            if (values.get('source_reference') or '').startswith(('CLOUD:','PROJECT:')):values['source_reference']=None
            values['created_at']=repository.clock();values['updated_at']=repository.clock()
            new=repo.create_task(Task.model_validate(values))
            if deleted:repo.soft_delete_task(new.id,'local-recovery')
            # Preserve already-used reminder identities under the mapped local task.
            c.execute('UPDATE notification_log SET task_id=? WHERE task_id=?',(new.id,old_id))
            repo.delete_task(old_id)
            mapping.append({'old_task_id':old_id,'new_task_id':new.id})
        c.execute('UPDATE cloud_state SET fenced=1')
    return mapping
