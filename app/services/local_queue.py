"""App-owned local task queue: bounded main-thread polling, durable atomic receipts."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
import itertools
import json
import logging
import os
from pathlib import Path
import sqlite3

from PySide6.QtCore import QLockFile
from app.database.task_repository import TaskRepository
from app.models.task import Task
from scripts.task_queue import (MAX_BYTES, SUPPRESSED, atomic_json, command_id, decode,
                               digest, encode, queue_path, revision, safe_path, validate)

LOGGER = logging.getLogger(__name__)


class _TransactionDatabase:
    def __init__(self, connection):
        self.connection = connection

    @contextmanager
    def transaction(self):
        # Existing repository methods participate in the queue's outer transaction.
        yield self.connection


class _TransactionRepository(TaskRepository):
    def __init__(self, connection, clock):
        self.database = _TransactionDatabase(connection)
        self.clock = clock


def _task_result(row):
    return {'task': dict(row), 'revision': revision(row)}


class LocalTaskQueue:
    def __init__(self, repository, root, *, busy=lambda: False, changed=lambda: None):
        self.repository = repository
        self.root = Path(root)
        self.directory = queue_path(root)
        self.busy = busy
        self.changed = changed
        self.lock = None
        self.in_tick = False

    def enabled(self):
        path = safe_path(self.root / 'config' / 'local_queue.json')
        return path.exists() and decode(path.read_bytes()) == {'enabled': True, 'version': 1}

    def close(self):
        if self.lock is not None:
            self.lock.unlock()
            self.lock = None

    def _initialize(self):
        if self.repository.database.path.resolve() != (self.root / 'data' / 'sitetask.db').resolve():
            raise ValueError('queue root and application database do not match')
        for name in ('inbox', 'receipts', 'archive', 'rejected'):
            safe_path(self.directory / name).mkdir(parents=True, exist_ok=True)
        if self.lock is None:
            lock = QLockFile(str(safe_path(self.directory / 'consumer.lock')))
            lock.setStaleLockTime(0)  # Live PID is never stolen just because its timer paused.
            if not lock.tryLock(0):
                return False
            self.lock = lock
        return True

    def _health(self, state):
        atomic_json(self.directory / 'health.json', {
            'version': 1, 'state': state, 'pid': os.getpid(),
            'checked_at': datetime.now().astimezone().isoformat(),
            'database': str(self.repository.database.path.resolve()),
            'queue': str(self.directory), 'poll_interval_ms': 1000,
        })

    def tick(self):
        if self.in_tick:
            return
        self.in_tick = True
        changed = False
        try:
            if not self.enabled():
                if self.lock is not None:
                    self._health('disabled')
                    self.close()
                return
            if not self._initialize():
                return
            if self.busy():
                self._health('paused_for_user_interaction')
                return
            state = 'ready'
            # No unbounded scan/sort; process at most four small requests per tick.
            with os.scandir(self.directory / 'inbox') as entries:
                pending = list(itertools.islice((Path(e.path) for e in entries if e.name.endswith('.json')), 4))
            for path in pending:
                try:
                    changed = self._consume(path) or changed
                except (OSError, sqlite3.Error):
                    state = 'retrying_io'
                    # Keep the original request; ledger + task writes share one transaction.
                    LOGGER.warning('Local task queue I/O deferred')
                except Exception as error:
                    state = 'retrying_error'
                    LOGGER.warning('Local task queue deferred (%s)', type(error).__name__)
            self._health(state)
        except Exception as error:
            LOGGER.warning('Local task queue unavailable (%s)', type(error).__name__)
        finally:
            self.in_tick = False
            if changed:
                self.changed()

    def _consume(self, path):
        try:
            cid = command_id(path.stem)
        except ValueError:
            # Invalid names cannot become receipt paths. Quarantine the entry itself.
            destination = safe_path(self.directory / 'rejected' / (digest(path.name) + '.invalid-name'))
            os.replace(path, destination)
            return False
        payload = None
        try:
            safe_path(path)
            if not path.is_file():
                raise ValueError('request must be a regular file')
            with path.open('rb') as stream:
                payload = decode(stream.read(MAX_BYTES + 1))
            validate(payload)
            if payload['command_id'] != cid:
                raise ValueError('filename and command_id differ')
        except (ValueError, UnicodeError, RecursionError):
            result = {'command_id': cid, 'status': 'invalid', 'reason': 'invalid_request',
                      'payload_sha256': None, 'processed_at': datetime.now().astimezone().isoformat()}
            atomic_json(self.directory / 'receipts' / (cid + '.json'), result)
            os.replace(path, safe_path(self.directory / 'rejected' / (cid + '.json')))
            return False
        result = self.execute(payload)
        # A failure here deliberately leaves inbox file for crash-safe ledger replay.
        atomic_json(self.directory / 'receipts' / (cid + '.json'), result)
        destination = safe_path(self.directory / 'archive' / (cid + '-' + digest(payload) + '.json'))
        os.replace(path, destination)
        return result['status'] in ('created', 'updated')

    def execute(self, payload):
        validate(payload)
        cid, fingerprint = payload['command_id'], digest(payload)
        with self.repository.database.transaction() as connection:
            connection.execute('PRAGMA busy_timeout=50')
            connection.execute('BEGIN IMMEDIATE')
            old = connection.execute('SELECT * FROM local_queue_commands WHERE command_id=?', (cid,)).fetchone()
            if old is not None:
                if old['payload_sha256'] == fingerprint:
                    return json.loads(old['result_json'])
                return {'command_id': cid, 'payload_sha256': fingerprint, 'status': 'conflict', 'reason': 'command_id_reused'}
            result = self._apply(connection, payload)
            result.update(command_id=cid, payload_sha256=fingerprint,
                          processed_at=self.repository.clock().isoformat())
            connection.execute('INSERT INTO local_queue_commands VALUES (?, ?, ?, ?)',
                               (cid, fingerprint, encode(result).decode('utf-8'), result['processed_at']))
            return result

    def _apply(self, connection, payload):
        operation = payload['operation']
        if operation == 'ping':
            return {'status': 'ok', 'protocol_version': 1, 'database': str(self.repository.database.path.resolve())}
        ref = payload['source_reference']
        rows = connection.execute('SELECT * FROM tasks WHERE source_reference=? ORDER BY id', (ref,)).fetchall()
        if len(rows) > 1:
            return {'status': 'conflict', 'reason': 'ambiguous_source_reference', 'task_ids': [r['id'] for r in rows]}
        row = rows[0] if rows else None
        if operation == 'get':
            return {'status': 'found', **_task_result(row)} if row else {'status': 'not_found'}
        if ref in SUPPRESSED:
            return {'status': 'protected', 'reason': 'previously_completed_excluded'}
        tracked = connection.execute('SELECT * FROM local_queue_sources WHERE source_reference=?', (ref,)).fetchone()
        if tracked and (tracked['deleted'] or row is None or tracked['task_id'] != row['id']):
            return {'status': 'protected', 'reason': 'deleted_or_identity_changed'}
        if row and row['status'] != 'pending':
            return {'status': 'protected', 'reason': 'task_closed', **_task_result(row)}
        if operation == 'create' and row:
            return {'status': 'existing', 'reason': 'source_reference_exists_no_changes', **_task_result(row)}
        if operation == 'update':
            if row is None:
                return {'status': 'not_found'}
            current_revision = revision(row)
            if payload['expected_revision'] != current_revision:
                return {'status': 'conflict', 'reason': 'revision_changed', **_task_result(row)}
            if tracked and tracked['last_revision'] and tracked['last_revision'] != current_revision:
                return {'status': 'conflict', 'reason': 'manual_changes_since_queue_write', **_task_result(row)}

        fields = dict(payload['fields'])
        if 'due_date' in fields:
            fields['due_date'] = date(2000, 1, 1) if fields['no_due'] else date.fromisoformat(fields['due_date'])
            fields['due_time'] = None  # V1 deliberately cannot introduce timed reminders.
        repository = _TransactionRepository(connection, self.repository.clock)
        if operation == 'create':
            now = self.repository.clock()
            task = repository.create_task(Task(**fields, source_reference=ref, created_at=now, updated_at=now))
        else:
            task = Task.model_validate({**dict(row), **fields})
            task = repository.update_task(task)
        current = connection.execute('SELECT * FROM tasks WHERE id=?', (task.id,)).fetchone()
        connection.execute('''INSERT INTO local_queue_sources (source_reference, task_id, last_revision)
            VALUES (?, ?, ?) ON CONFLICT(source_reference) DO UPDATE SET last_revision=excluded.last_revision''',
                           (ref, task.id, revision(current)))
        return {'status': 'created' if operation == 'create' else 'updated', **_task_result(current)}
