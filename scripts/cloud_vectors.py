"""Regenerate the cloud wire vectors from explicit cases; checked into the source."""
import sys,json,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.services.cloud_protocol import decode,validate_request
from scripts.task_queue import encode
r=dict(v=1,command_id='1b4e28ba-2fa1-4d3b-a3f5-ef19b5a7633b',op='create',target=None,base_revision=None,fields=dict(title='确认检查 😀',description='行1\n行2 "引号" é\u2028',due_date='2026-10-21',no_due=False,category='IRF',priority='normal'),reason=None)
cases=[('unicode',encode(r))]
def change(name,key,value):
    x=json.loads(json.dumps(r));x['fields'][key]=value;cases.append((name,encode(x)))
change('title_200','title','😀'*200);change('title_201','title','😀'*201)
change('invalid_date','due_date','2026-02-30');change('year_zero','due_date','0000-01-01')
change('title_control','title','a\tb');change('description_tabs','description','a\tb\nc');change('description_c1','description','a\x85b')
change('null_boolean','no_due',None)
for name,raw in [('duplicate_keys',b'{"v":1,"v":1}'),('float',b'{"v":1.0}'),('overflow',b'{"n":9007199254740992}'),('surrogate',b'{"s":"\\ud800"}')]:cases.append((name,raw))
x={**r,'extra':None};cases.append(('extra_key',encode(x)))
x={k:v for k,v in r.items() if k!='reason'};cases.append(('missing_key',encode(x)))
x={**r,'op':'get','fields':None,'target':{'task_id':2**53-1}};cases.append(('max_integer',encode(x)))
x={**r,'op':'get','fields':None,'target':{'task_id':True}};cases.append(('bool_id',encode(x)))
vectors=[]
for name,raw in cases:
    entry={'name':name,'input_hex':raw.hex(),'valid':False}
    try:
        v=validate_request(decode(raw));canonical=encode(v);entry.update(valid=True,canonical_hex=canonical.hex(),sha256=hashlib.sha256(canonical).hexdigest())
    except ValueError:pass
    vectors.append(entry)
p=Path(__file__).resolve().parents[1]/'tests'/'vectors'/'cloud_v1.json';p.parent.mkdir(exist_ok=True);p.write_text(json.dumps(vectors,ensure_ascii=False,indent=2),encoding='utf-8')
print(f'{len(vectors)} cross-language vectors generated')
