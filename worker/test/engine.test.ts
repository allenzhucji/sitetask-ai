import {test} from 'node:test';
import assert from 'node:assert/strict';
import {Engine,initial} from '../src/engine.ts';
import {parse,validate,sha,canonical} from '../src/protocol.ts';
import {readFileSync} from 'node:fs';
test('shared Python and TypeScript wire vectors',async()=>{
 const cases=JSON.parse(readFileSync(new URL('../../tests/vectors/cloud_v1.json',import.meta.url),'utf8'));
 for(const c of cases){const raw=Buffer.from(c.input_hex,'hex').toString('utf8');
   if(!c.valid)assert.throws(()=>validate(parse(raw)),undefined,c.name);
   else {const v=validate(parse(raw));assert.equal(Buffer.from(canonical(v)).toString('hex'),c.canonical_hex,c.name);assert.equal(await sha(v),c.sha256,c.name);}
 }
});
const db='11111111-1111-4111-8111-111111111111',instance='22222222-2222-4222-8222-222222222222';
const actor={token_id:'a'.repeat(16),scope:'assistant',db_id:db};
const req=(op='create',target:any=null,base:any=null)=>({v:1,command_id:crypto.randomUUID(),op,target,base_revision:base,fields:op==='create'?{title:'中文 😀',description:'line\n2',due_date:'2026-10-28',no_due:false,category:'IRF',priority:'normal'}:null,reason:null});
function engine(now='2026-10-28T08:00:00.000Z'){const e=new Engine(initial(db),now);e.bind({db_id:db,instance_id:instance,install_fingerprint:'f'.repeat(64)},actor);return e;}
const identity=(e:Engine)=>({db_id:db,instance_id:instance,epoch:e.s.db.epoch,max_change_seq:100,max_task_id:100,credits:4});
test('strict parser rejects duplicate keys, floats, overflow and surrogate',()=>{
 for(const raw of ['{"a":1,"a":2}','{"a":1.0}','{"a":9007199254740992}','{"a":"\\ud800"}'])assert.throws(()=>parse(raw));
 assert.equal(canonical(parse('{"z":"😀","a":1}')),'{"a":1,"z":"😀"}');
});
test('validation rejects invalid dates and unsupported destructive operation',()=>{
 const r=req();r.fields!.due_date='2026-02-30';assert.throws(()=>validate(r));
 assert.throws(()=>validate(req('purge',{task_id:1},'0'.repeat(64))));
});
test('ownership precedes replay and mailbox isolation',async()=>{
 const e=engine(),r=req();await e.submit(r,actor);await assert.rejects(()=>e.submit(r,{...actor,token_id:'b'.repeat(16)}),/unavailable/);
 assert.throws(()=>e.command(e.s.commands[r.command_id],{...actor,token_id:'b'.repeat(16)}),/not_found/);
 await assert.rejects(()=>e.submit(req('get',{task_id:1}),{...actor,scope:'mail-automation'}),/forbidden/);
});
test('ordered leases, one outstanding batch, expiry, revocation',async()=>{
 const e=engine();for(let i=0;i<6;i++)await e.submit(req(),actor);
 const first=e.pull(identity(e),new Set());assert.equal(first.leases.length,4);
 assert.equal(e.pull(identity(e),new Set()).leases.length,0);
 e.now='2026-10-28T08:02:01.000Z';assert.equal(e.pull(identity(e),new Set()).leases.length,4);
 assert.equal(e.pull(identity(e),new Set([actor.token_id])).leases.length,0);
 assert.ok(Object.values(e.s.commands).every(c=>c.state==='voided'));
});
test('late receipt accepted against historical lease, never updates mirror',async()=>{
 const e=engine(),r=req();await e.submit(r,actor);const l=e.pull(identity(e),new Set()).leases[0];
 const receipt:any={rv:1,db_id:db,epoch:1,command_id:r.command_id,request_sha256:l.envelope.request_sha256,lease_id:l.lease_id,lease_gen:l.lease_gen,
  status:'applied',result_code:'created',task_id:1,business_revision:'0'.repeat(64),change_seq:1,snapshot:{title:'old'},processed_at:'2026-10-28T08:00:01.000Z',record_deadline:'2026-11-27T08:00:01.000Z'};
 receipt.result_sha256=await sha(Object.fromEntries(['command_id','status','result_code','task_id','business_revision','change_seq'].map(k=>[k,receipt[k]])));
 e.now='2026-10-29T08:00:00.000Z';const b={...identity(e),receipts:[receipt]};assert.deepEqual((await e.receipts(b)).acknowledged,[r.command_id]);
 assert.equal(Object.keys(e.s.tasks).length,0);await e.receipts(b);
 const bad={...receipt,result_code:'updated'};bad.result_sha256=await sha(Object.fromEntries(['command_id','status','result_code','task_id','business_revision','change_seq'].map(k=>[k,bad[k]])));
 await assert.rejects(()=>e.receipts({...identity(e),receipts:[bad]}),/receipt_conflict/);
});
test('expired content allows metadata get and reopen, rejects submitted content',async()=>{
 const e=engine();e.s.tasks[1]={task_id:1,change_seq:1,business_revision:'0'.repeat(64),lifecycle:'inactive',retention_deadline:'2026-10-01T00:00:00.000Z',content:{title:'old'}};
 await e.submit(req('get',{task_id:1}),actor);await e.submit(req('reopen',{task_id:1},'0'.repeat(64)),actor);
 const r=req('update',{task_id:1},'0'.repeat(64));r.fields={title:'replacement'} as any;await assert.rejects(()=>e.submit(r,actor),/expired/);
 assert.equal(e.list(actor)[0].content,null);
});
test('reopen before cron cannot revive historical content',async()=>{
 const e=engine('2026-10-30T08:00:00.000Z'),r=req('get',{task_id:1});
 e.s.tasks[1]={task_id:1,change_seq:1,epoch:1,business_revision:'0'.repeat(64),lifecycle:'inactive',episode:1,retention_deadline:'2026-10-31T00:00:00.000Z',episode_deadlines:{1:'2026-10-31T00:00:00.000Z'}};
 await e.submit(r,actor);e.now='2026-10-31T00:01:00.000Z';
 e.apply({...e.s.tasks[1],change_seq:2,lifecycle:'active',retention_deadline:null,content:{title:'current'}});e.expire();
 assert.equal(e.s.commands[r.command_id].envelope,null);assert.ok(e.s.tasks[1].content);
});
test('full generation verifies manifest and preserves newer increment',async()=>{
 const e=engine(),g=crypto.randomUUID();const item={task_id:1,change_seq:10,business_revision:'0'.repeat(64),lifecycle:'active',episode:0,retention_deadline:null,content:null};
 const manifest=await sha([[1,10,item.business_revision,'active']]);
 await e.generation('start',{...identity(e),generation:g,as_of:10,expected_count:1,manifest_sha256:manifest});
 await assert.rejects(()=>e.generation('finalize',{...identity(e),generation:g}),/incomplete/);
 await e.generation('items',{...identity(e),generation:g,items:[item]});
 // An increment newer than as_of stays present when absent from the full snapshot.
 e.apply({...item,task_id:2,change_seq:11});
 await e.generation('finalize',{...identity(e),generation:g});assert.equal(e.s.tasks[2].lifecycle,'active');assert.equal(e.s.db.acked,10);
});
test('permanent tombstones refuse resurrection and recovery fences commands',async()=>{
 const e=engine();e.apply({task_id:1,change_seq:1,lifecycle:'tombstone',episode:1,retention_deadline:null,content:null});
 assert.throws(()=>e.apply({task_id:1,change_seq:2,lifecycle:'active',episode:1,retention_deadline:null}),/terminal/);
 await e.submit(req(),actor);const result=e.reconcile({...identity(e),reconcile_id:crypto.randomUUID(),strategy:'preserve-identities'});
 assert.equal(result.epoch,2);assert.ok(Object.values(e.s.commands).every(c=>c.state==='quarantined'));
 assert.throws(()=>e.pull(identity(e),new Set()),/fenced/);
});
