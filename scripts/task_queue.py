"""Local queue client and strict wire protocol. Standard library only; never writes SQLite."""
from __future__ import annotations

import argparse
from datetime import date, time
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
import tempfile
import uuid

MAX_BYTES = 32768
FIELDS = {'title', 'description', 'due_date', 'no_due', 'category', 'priority'}
CATEGORIES = {'Site Inspection', 'IRF', 'EFI', 'Drawing', 'Method Statement', 'Material', 'Email', 'Meeting', 'Report', 'Follow-up', 'Personal', 'Other'}
SUPPRESSED = {'PROJECT:T002', 'PROJECT:T003', 'PROJECT:T004', 'PROJECT:T013'}


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(encode(value)).hexdigest()


def revision(row):
    return digest(dict(row))


def command_id(value):
    if type(value) is not str or str(uuid.UUID(value)) != value:
        raise ValueError('command_id must be a lowercase canonical UUID')
    return value


def source_reference(value):
    if type(value) is not str or not re.fullmatch(r'PROJECT:[A-Za-z0-9][A-Za-z0-9:._-]{0,159}', value):
        raise ValueError('source_reference must be in the PROJECT namespace')
    return value


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def decode(raw):
    if len(raw) > MAX_BYTES:
        raise ValueError('request exceeds 32768 bytes')
    return json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_unique_object,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('non-finite JSON number')))


def validate(value):
    if type(value) is not dict:
        raise ValueError('request must be an object')
    op = value.get('operation')
    keys = {'version', 'command_id', 'operation'}
    if op in ('create', 'update', 'get'):
        keys.add('source_reference')
        source_reference(value.get('source_reference'))
    if op in ('create', 'update'):
        keys.add('fields')
    if op == 'update':
        keys.add('expected_revision')
        if type(value.get('expected_revision')) is not str or not re.fullmatch('[0-9a-f]{64}', value['expected_revision']):
            raise ValueError('update requires expected_revision from a task read')
    if op not in ('create', 'update', 'get', 'ping') or set(value) != keys:
        raise ValueError('unsupported operation or fields')
    if type(value['version']) is not int or value['version'] != 1:
        raise ValueError('version must be 1')
    command_id(value['command_id'])
    if op in ('create', 'update'):
        fields = value['fields']
        if type(fields) is not dict or not fields or not set(fields) <= FIELDS:
            raise ValueError('invalid task fields; status, identifiers and timed reminders are not writable')
        if op == 'create' and set(fields) != FIELDS:
            raise ValueError('create requires title, description, due_date, no_due, category, priority')
        for key in ('title', 'description'):
            if key in fields and (type(fields[key]) is not str or len(fields[key]) > (200 if key == 'title' else 6000) or '\x00' in fields[key]):
                raise ValueError('invalid text field')
        if 'title' in fields:
            title = fields['title']
            if title != title.strip() or not title or '\n' in title or '\r' in title or re.match(r'(?i)^\[?PROJECT\b', title):
                raise ValueError('title must be concise, trimmed, and without project prefix')
        if 'category' in fields and (type(fields['category']) is not str or fields['category'] not in CATEGORIES):
            raise ValueError('invalid category')
        if 'priority' in fields and (type(fields['priority']) is not str or fields['priority'] not in {'low', 'normal', 'high', 'urgent'}):
            raise ValueError('invalid priority')
        if 'no_due' in fields or 'due_date' in fields:
            if not {'no_due', 'due_date'} <= set(fields) or type(fields['no_due']) is not bool:
                raise ValueError('supply due_date and boolean no_due together')
            due = fields['due_date']
            if fields['no_due']:
                if due is not None:
                    raise ValueError('No Due requires due_date null')
            elif type(due) is not str or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', due) or date.fromisoformat(due).isoformat() != due:
                raise ValueError('due_date requires YYYY-MM-DD')
    if len(encode(value)) > MAX_BYTES:
        raise ValueError('request exceeds 32768 bytes')
    return value


def safe_path(path):
    """Reject symlinks/junctions in every existing component; do not modify ACLs."""
    path = Path(path).absolute()
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('queue paths cannot contain symlinks or reparse points')
    return path


def atomic_json(path, value, *, exclusive=False):
    path = safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.writing-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(encode(value))
            stream.flush()
            os.fsync(stream.fileno())
        if exclusive:
            os.link(temporary, path)  # Publish a complete file without replacing an existing request.
        else:
            os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def queue_path(root):
    return safe_path(Path(root) / 'data' / 'integration')


def submit(root, value):
    value = validate(value)
    queue = queue_path(root)
    config = safe_path(Path(root) / 'config' / 'local_queue.json')
    if not config.exists() or json.loads(config.read_text(encoding='utf-8-sig')) != {'enabled': True, 'version': 1}:
        raise ValueError('queue is not enabled for this installation')
    request = queue / 'inbox' / (value['command_id'] + '.json')
    receipt = safe_path(queue / 'receipts' / request.name)
    if receipt.exists():
        result = json.loads(receipt.read_text(encoding='utf-8'))
        if result.get('payload_sha256') != digest(value):
            raise ValueError('command_id was already used with another payload')
        return result
    try:
        atomic_json(request, value, exclusive=True)
    except FileExistsError:
        if digest(decode(safe_path(request).read_bytes())) != digest(value):
            raise ValueError('command_id is already queued with another payload')
    return {'command_id': value['command_id'], 'status': 'queued', 'payload_sha256': digest(value)}


def read_tasks(root, ref=None):
    db = safe_path(Path(root) / 'data' / 'sitetask.db')
    connection = sqlite3.connect(db.as_uri() + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute('PRAGMA query_only=ON')
        connection.execute('BEGIN')
        rows = connection.execute('SELECT * FROM tasks WHERE source_reference=? ORDER BY id', (ref,)) if ref else connection.execute('SELECT * FROM tasks ORDER BY id')
        return [{'task': dict(row), 'revision': revision(row)} for row in rows]
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path, help='Formal installation containing SiteTaskAI.exe and data/')
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('submit').add_argument('json_file', type=Path)
    sub.add_parser('status').add_argument('command_id')
    sub.add_parser('read').add_argument('--source-reference')
    sub.add_parser('health')
    sub.add_parser('ping')
    args = parser.parse_args()
    try:
        if args.action == 'submit':
            with args.json_file.open('rb') as stream:
                result = submit(args.root, decode(stream.read(MAX_BYTES + 1)))
        elif args.action == 'read':
            result = read_tasks(args.root, args.source_reference)
        elif args.action == 'ping':
            result = submit(args.root, dict(version=1, command_id=str(uuid.uuid4()), operation='ping'))
        else:
            path = queue_path(args.root) / ('health.json' if args.action == 'health' else 'receipts/' + command_id(args.command_id) + '.json')
            if safe_path(path).exists():
                result = json.loads(path.read_text(encoding='utf-8'))
            else:
                result = {'status': 'no_receipt', 'meaning': 'not confirmed processed'}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, sqlite3.Error) as error:
        print(json.dumps({'status': 'client_error', 'error_type': type(error).__name__, 'message': str(error)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
