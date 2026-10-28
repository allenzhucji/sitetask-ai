"""Bridge schema, installed by migration 6 in the migration's write transaction."""
def apply_cloud_schema(c):
    c.execute('CREATE TABLE task_versions(task_id INTEGER PRIMARY KEY, change_seq INTEGER NOT NULL)')
    c.execute('INSERT INTO task_versions SELECT task_id, MAX(change_seq) FROM task_changes GROUP BY task_id')
    # Legacy tombstones and already-pruned identities need a real initial version.
    for row in c.execute('''SELECT id FROM tasks WHERE id NOT IN (SELECT task_id FROM task_versions)
                         UNION SELECT task_id FROM task_tombstones WHERE task_id NOT IN (SELECT task_id FROM task_versions)''').fetchall():
        c.execute("INSERT INTO task_changes(task_id,kind,changed_at) VALUES (?,'baseline',strftime('%Y-%m-%dT%H:%M:%fZ','now'))", (row[0],))
        seq = c.execute("SELECT seq FROM sqlite_sequence WHERE name='task_changes'").fetchone()[0]
        c.execute('INSERT INTO task_versions VALUES (?,?)', (row[0], seq))
    c.execute('UPDATE task_tombstones SET change_seq=(SELECT change_seq FROM task_versions WHERE task_id=task_tombstones.task_id) WHERE change_seq IS NULL')
    c.execute('''CREATE TRIGGER cloud_version AFTER INSERT ON task_changes BEGIN
        INSERT INTO task_versions VALUES (NEW.task_id,NEW.change_seq)
        ON CONFLICT(task_id) DO UPDATE SET change_seq=excluded.change_seq; END''')
    c.execute("CREATE UNIQUE INDEX ux_tasks_cloud_ref ON tasks(source_reference) WHERE source_reference GLOB 'CLOUD:*'")
    c.execute('''CREATE TABLE cloud_state(singleton INTEGER PRIMARY KEY CHECK(singleton=1),
        enabled INTEGER NOT NULL DEFAULT 0, fenced INTEGER NOT NULL DEFAULT 0,
        acked INTEGER NOT NULL DEFAULT 0, reconcile_id TEXT, reconcile_phase TEXT)''')
    c.execute('INSERT INTO cloud_state(singleton) VALUES (1)')
    c.execute('''CREATE TABLE cloud_receipt_outbox(command_id TEXT PRIMARY KEY,
        receipt_json TEXT NOT NULL, created_at TEXT NOT NULL)''')
    c.execute('''CREATE TABLE cloud_episodes(task_id INTEGER NOT NULL, episode INTEGER NOT NULL,
        deadline TEXT NOT NULL, PRIMARY KEY(task_id,episode))''')
    c.execute('''INSERT INTO cloud_episodes SELECT task_id,episode,retention_deadline FROM task_lifecycle
        WHERE retention_deadline IS NOT NULL''')
    # The task trigger records lifecycle updates; preserve deadlines after reactivation.
    c.execute('''CREATE TRIGGER cloud_episode AFTER UPDATE ON task_lifecycle
        WHEN NEW.retention_deadline IS NOT NULL BEGIN
        INSERT INTO cloud_episodes VALUES(NEW.task_id,NEW.episode,NEW.retention_deadline)
        ON CONFLICT(task_id,episode) DO UPDATE SET deadline=MIN(deadline,excluded.deadline); END''')
    c.execute('''CREATE TRIGGER cloud_create_fence BEFORE INSERT ON tasks
        WHEN (SELECT enabled=1 AND fenced=1 FROM cloud_state WHERE singleton=1)
        BEGIN SELECT RAISE(ABORT,'cloud_restore_fenced'); END''')
    c.execute("UPDATE local_identity SET schema_marker='sitetask-schema-6'")
