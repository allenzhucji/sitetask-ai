"""Read-only source backup, then migrate and verify ONLY the new rehearsal copy."""
import argparse,json,sqlite3,sys,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.database.connection import Database
from app.database.migrations import apply_migrations
from app.database.task_repository import TaskRepository
from app.services.cloud_store import CloudStore
from tests.fixtures import legacy_migrations_v4,legacy_migrations_v5

def main():
    p=argparse.ArgumentParser();p.add_argument('--database',type=Path,required=True);p.add_argument('--workdir',type=Path,required=True);a=p.parse_args()
    source=a.database.resolve();work=a.workdir.resolve()
    if source==work or source in work.parents or work==source.parent:raise ValueError('source and output must differ')
    work.mkdir(parents=True,exist_ok=False);target=work/'data'/'sitetask.db';target.parent.mkdir()
    fingerprint=hashlib.sha256(source.read_bytes()).hexdigest()
    with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as src,sqlite3.connect(target) as dst:src.backup(dst)
    db=Database(target)
    with db.transaction() as c:before={r['id']:dict(r) for r in c.execute('SELECT * FROM tasks')}
    applied=apply_migrations(db)
    with db.transaction() as c:
        after={r['id']:dict(r) for r in c.execute('SELECT * FROM tasks')}
        identical=set(before)==set(after) and all(all(after[i][k]==v for k,v in row.items()) for i,row in before.items())
        integrity=c.execute('PRAGMA integrity_check').fetchone()[0];version=c.execute('PRAGMA user_version').fetchone()[0]
        versions=c.execute('SELECT COUNT(*) FROM task_versions').fetchone()[0]
    blocked=[]
    for legacy in (legacy_migrations_v4,legacy_migrations_v5):
        try:legacy.apply_migrations(db)
        except Exception:blocked.append(True)
        else:blocked.append(False)
    store=CloudStore(TaskRepository(db));snapshot=store.snapshot()
    with db.transaction() as c:c.execute('DELETE FROM task_changes')
    pruned=store.snapshot();survives=snapshot==pruned
    unchanged=hashlib.sha256(source.read_bytes()).hexdigest()==fingerprint
    report=dict(applied=list(applied),task_count_before=len(before),task_count_after=len(after),all_original_task_fields_identical=identical,
        integrity_check=integrity,schema_version=version,persistent_versions=versions,old_v4_and_v5_rejected=all(blocked),
        full_snapshot_survives_log_pruning=survives,source_file_unchanged=unchanged)
    report['passed']=identical and integrity=='ok' and version==6 and all(blocked) and survives and unchanged
    (work/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report));return 0 if report['passed'] else 1

if __name__=='__main__':sys.exit(main())
