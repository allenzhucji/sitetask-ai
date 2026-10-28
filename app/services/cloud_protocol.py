"""Strict cloud-only wire validation. Inbox acceptance rules remain unchanged."""
from datetime import datetime, timezone
import json
import re
from scripts.task_queue import encode, digest, command_id, validate, _unique_object

OPS = {'create','update','get','complete','reopen','soft_delete','restore'}
BUSINESS_FIELDS = 'id title description due_date due_time category priority status no_due source_reference completed_at deleted_at'.split()

def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')

def stamp(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z',value):
        raise ValueError('invalid_timestamp')
    datetime.fromisoformat(value.replace('Z','+00:00'))
    return value

def json_value(value):
    if value is None or type(value) is bool:
        return
    if type(value) is int and abs(value) <= 2**53-1:
        return
    if type(value) is str:
        if any(0xD800<=ord(c)<=0xDFFF for c in value):
            raise ValueError('invalid_unicode')
        return
    if type(value) is list:
        for v in value: json_value(v)
        return
    if type(value) is dict and all(type(k) is str and k.isascii() for k in value):
        for v in value.values(): json_value(v)
        return
    raise ValueError('invalid_json_type')

def decode(raw, limit=32768):
    if len(raw)>limit: raise ValueError('too_large')
    value=json.loads(raw.decode('utf-8-sig'),object_pairs_hook=_unique_object,
        parse_float=lambda _: (_ for _ in ()).throw(ValueError('float_not_allowed')),
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('invalid_number')))
    json_value(value)
    return value

def business_revision(row):
    return digest({k:row[k] for k in BUSINESS_FIELDS})

def validate_request(r):
    json_value(r)
    if type(r) is not dict or set(r)!= {'v','command_id','op','target','base_revision','fields','reason'}:
        raise ValueError('invalid_keys')
    if type(r['v']) is not int or r['v']!=1 or r['op'] not in OPS: raise ValueError('invalid_operation')
    command_id(r['command_id'])
    op=r['op']
    if op=='create':
        if r['target'] is not None or r['base_revision'] is not None: raise ValueError('invalid_create')
    else:
        t=r['target']
        if type(t) is not dict or len(t)!=1: raise ValueError('invalid_target')
        if 'task_id' in t:
            if type(t['task_id']) is not int or t['task_id']<=0: raise ValueError('invalid_target')
        elif 'source_reference' in t:
            ref=t['source_reference']
            if type(ref) is not str: raise ValueError('invalid_target')
            if ref.startswith('CLOUD:'): command_id(ref[6:])
            elif not re.fullmatch(r'PROJECT:[A-Za-z0-9][A-Za-z0-9:._-]{0,159}',ref): raise ValueError('invalid_target')
        else: raise ValueError('invalid_target')
        if op=='get':
            if r['base_revision'] is not None: raise ValueError('invalid_revision')
        elif type(r['base_revision']) is not str or not re.fullmatch('[0-9a-f]{64}',r['base_revision']):
            raise ValueError('invalid_revision')
    if op in ('create','update'):
        # Reuse the existing field validator without widening inbox semantics.
        payload=dict(version=1,command_id=r['command_id'],operation=op,
                     source_reference='PROJECT:cloud-validation',fields=r['fields'])
        if op=='update': payload['expected_revision']=r['base_revision']
        validate(payload)
        for key in ('title','description'):
            for ch in r['fields'].get(key,''):
                if (ord(ch)<32 or 127<=ord(ch)<=159) and not(key=='description' and ch in '\n\t'):
                    raise ValueError('control_character')
    elif r['fields'] is not None: raise ValueError('invalid_fields')
    if r['reason'] is not None and (type(r['reason']) is not str or len(r['reason'])>200):
        raise ValueError('invalid_reason')
    if len(encode(r))>32768: raise ValueError('too_large')
    return r

def authorize(request,scope):
    if scope=='assistant': return
    # v1 never issues mail cloud credentials; fail closed rather than widening inbox.
    if scope!='mail-automation' or request['op'] not in ('update','get'):
        raise ValueError('forbidden_scope')
    target=request['target'] or {}
    if not str(target.get('source_reference','')).startswith('PROJECT:'):
        raise ValueError('forbidden_scope')

def validate_envelope(e):
    if type(e) is not dict or set(e)!= {'ev','db_id','command_id','request_sha256','request','actor','assigned_source_reference','accepted_at','execute_before'}:
        raise ValueError('invalid_envelope')
    if type(e['ev']) is not int or e['ev']!=1: raise ValueError('invalid_envelope')
    command_id(e['db_id']); validate_request(e['request'])
    if e['command_id']!=e['request']['command_id'] or e['request_sha256']!=digest(e['request']): raise ValueError('invalid_hash')
    if type(e['actor']) is not dict or set(e['actor'])!={'token_id','scope'} or not re.fullmatch('[0-9a-f]{16}',e['actor']['token_id']): raise ValueError('invalid_actor')
    authorize(e['request'],e['actor']['scope'])
    expected='CLOUD:'+e['command_id'] if e['request']['op']=='create' else None
    if e['assigned_source_reference']!=expected: raise ValueError('invalid_reference')
    start=datetime.fromisoformat(stamp(e['accepted_at']).replace('Z','+00:00'))
    end=datetime.fromisoformat(stamp(e['execute_before']).replace('Z','+00:00'))
    if (end-start).total_seconds()!=7*86400: raise ValueError('invalid_deadline')
    return e
