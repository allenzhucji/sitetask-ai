import {Fault,validate,authorize,sha,canonical,bytes,uuid,timestamp,plus} from './protocol.ts';
const DAY=86400000;
export type State={db:any,commands:Record<string,any>,tasks:Record<string,any>,generations:Record<string,any>};
export const initial=(db_id:string):State=>({db:{db_id,epoch:1,acked:0,max_task_id:0,owner:null,generation:0,reconciles:{},fenced:false},commands:{},tasks:{},generations:{}});
export class Engine {
  s:State; now:string;
  constructor(state:State, now=new Date().toISOString()){this.s=state;this.now=now;}
  target(r:any){const t=r.target;if(!t)return undefined;if(t.task_id)return this.s.tasks[t.task_id];const a=Object.values(this.s.tasks).filter((x:any)=>x.source_reference===t.source_reference&&x.lifecycle!=='tombstone');return a.length===1?a[0]:undefined;}
  expire(){
    for(const t of Object.values(this.s.tasks))if(t.lifecycle==='tombstone'||t.lifecycle!=='active'&&(!t.retention_deadline||t.retention_deadline<=this.now)){t.content=null;t.content_expired=true;}
    for(const c of Object.values(this.s.commands)){
      const targets=c.task_id?[this.s.tasks[c.task_id]]:c.target?.task_id?[this.s.tasks[c.target.task_id]]:
        c.target?.source_reference?Object.values(this.s.tasks).filter(t=>t.source_reference===c.target.source_reference):[];
      for(const target of targets.filter(Boolean)){
        for(const d of Object.values(target.episode_deadlines||{}) as string[]){if(!c.accepted_at||d>=c.accepted_at)c.deadline=c.deadline<d?c.deadline:d;}
        if(target.lifecycle==='inactive'&&target.retention_deadline)c.deadline=c.deadline<target.retention_deadline?c.deadline:target.retention_deadline;
        if(target.lifecycle==='tombstone')c.deadline=this.now<c.deadline?this.now:c.deadline;
      }
      if(c.deadline<=this.now||c.content_purged_at){c.envelope=null;if(c.receipt)c.receipt.snapshot=null;c.content_purged_at ||= this.now;}
      if(['queued','leased'].includes(c.state)&&c.execute_before<=this.now)c.state='expired';
    }
    for(const [id,g] of Object.entries(this.s.generations)){
      if(g.expires<=this.now)delete this.s.generations[id];
      else for(const [key,item] of Object.entries(g.items))g.items[key]=this.filteredItem(item);
    }
  }
  async submit(r:any,actor:any){
    validate(r);authorize(r,actor.scope);const hash=await sha(r),old=this.s.commands[r.command_id];
    if(old){if(old.token_id!==actor.token_id)throw new Fault('command_id_unavailable',409);if(old.request_sha256!==hash)throw new Fault('command_id_reused',409);return this.command(old,actor);}
    const target=this.target(r);
    if(target?.lifecycle==='tombstone')throw new Fault('purged',409);
    // Metadata operations may legally revive an expired task. Only reject submitted content.
    if(target?.lifecycle==='inactive'&&(!target.retention_deadline||target.retention_deadline<=this.now)&&(r.fields!==null||r.reason!==null))throw new Fault('target_content_expired',409);
    const envelope={ev:1,db_id:this.s.db.db_id,command_id:r.command_id,request_sha256:hash,request:r,
      actor:{token_id:actor.token_id,scope:actor.scope},assigned_source_reference:r.op==='create'?'CLOUD:'+r.command_id:null,
      accepted_at:this.now,execute_before:plus(this.now,7*DAY)};
    if(bytes(canonical(envelope)).length>32768)throw new Fault('too_large',413);
    this.s.db.command_seq=(this.s.db.command_seq||0)+1;
    const c={seq:this.s.db.command_seq,command_id:r.command_id,token_id:actor.token_id,request_sha256:hash,
      envelope,state:'queued',accepted_at:this.now,execute_before:envelope.execute_before,deadline:plus(this.now,30*DAY),
      task_id:target?.task_id||null,target:r.target,lease_gen:0,leases:[],receipt:null,content_purged_at:null};
    this.s.commands[r.command_id]=c;this.expire();return this.command(c,actor);
  }
  command(c:any,actor:any){if(!c||c.token_id!==actor.token_id)throw new Fault('not_found',404);this.expire();return {command_id:c.command_id,state:c.state,receipt:c.receipt,content_purged_at:c.content_purged_at};}
  cancel(id:string,actor:any){const c=this.s.commands[id];this.command(c,actor);if(c.state!=='queued')throw new Fault('too_late',409);c.state='cancelled';return this.command(c,actor);}
  bind(b:any,actor:any){
    if(b.db_id!==this.s.db.db_id||actor.db_id!==b.db_id||!uuid(b.instance_id)||typeof b.install_fingerprint!=='string'||!/^[0-9a-f]{64}$/.test(b.install_fingerprint))throw new Fault('wrong_database',409);
    const owner={instance_id:b.instance_id,install_fingerprint:b.install_fingerprint};
    if(this.s.db.owner&&canonical(owner)!==canonical(this.s.db.owner))throw new Fault('bridge_owned_elsewhere',409);
    this.s.db.owner=owner;return this.health();
  }
  identity(b:any){
    if(b.db_id!==this.s.db.db_id||b.epoch!==this.s.db.epoch||b.instance_id!==this.s.db.owner?.instance_id)throw new Fault('wrong_database_or_epoch',409);
    this.s.db.last_seen_at=this.now;
  }
  health(){return {db_id:this.s.db.db_id,epoch:this.s.db.epoch,acked:this.s.db.acked,max_task_id:this.s.db.max_task_id,fenced:this.s.db.fenced,last_seen_at:this.s.db.last_seen_at||null,queued:Object.values(this.s.commands).filter(c=>c.state==='queued').length};}
  pull(b:any,revoked:Set<string>){
    this.identity(b);if(!Number.isSafeInteger(b.max_change_seq)||!Number.isSafeInteger(b.max_task_id)||b.max_change_seq<this.s.db.acked||b.max_task_id<this.s.db.max_task_id){this.s.db.fenced=true;throw new Fault('restore_detected',409);}
    if(this.s.db.fenced)throw new Fault('restore_fenced',409);
    this.expire();const list=Object.values(this.s.commands).sort((a,b)=>a.seq-b.seq),voided=[];
    for(const c of list){if(revoked.has(c.token_id)&&['queued','leased'].includes(c.state))c.state='voided';if(c.state==='voided')voided.push(c.command_id);if(c.state==='leased'&&c.lease_until<=this.now)c.state='queued';}
    const result={...this.health(),leases:[] as any[],voided:voided.slice(-100),recent_applied_ids:list.filter(c=>c.state==='applied'&&c.receipt?.epoch===this.s.db.epoch).slice(-50).map(c=>c.command_id)};
    if(list.some(c=>c.state==='leased'))return result;
    const credits=Math.max(0,Math.min(4,Number.isSafeInteger(b.credits)?b.credits:0));let size=0;
    for(const c of list.filter(c=>c.state==='queued')){
      if(!c.envelope){c.state='expired';continue;}const n=bytes(canonical(c.envelope)).length;if(result.leases.length>=credits||size+n>128*1024)break;
      c.state='leased';c.lease_gen++;c.lease_id=crypto.randomUUID();c.lease_until=plus(this.now,120000)<c.execute_before?plus(this.now,120000):c.execute_before;
      c.leases.push({lease_id:c.lease_id,lease_gen:c.lease_gen,start:this.now,until:c.lease_until,epoch:this.s.db.epoch});
      size+=n;result.leases.push({envelope:c.envelope,epoch:this.s.db.epoch,lease_id:c.lease_id,lease_gen:c.lease_gen,lease_until:c.lease_until});
    }return result;
  }
  renew(b:any,revoked:Set<string>){
    this.identity(b);this.expire();const renewed=[],voided=[];
    for(const c of Object.values(this.s.commands))if(c.state==='leased'){
      if(revoked.has(c.token_id)){c.state='voided';voided.push(c.command_id);continue;}
      if((b.lease_ids||[]).includes(c.lease_id)&&c.lease_until>this.now){c.lease_until=plus(this.now,120000)<c.execute_before?plus(this.now,120000):c.execute_before;c.leases[c.leases.length-1].until=c.lease_until;renewed.push({command_id:c.command_id,lease_until:c.lease_until});}
    }return {renewed,voided};
  }
  async receipts(b:any){
    this.identity(b);if(!Array.isArray(b.receipts)||b.receipts.length>4)throw new Fault('invalid_receipts');const ack=[];
    for(const r of b.receipts){
      const allowed='rv db_id epoch command_id request_sha256 lease_id lease_gen processed_at task_id business_revision change_seq snapshot episode record_deadline task_deadline status result_code result_sha256 match_count'.split(' ');
      if(Object.keys(r).some(k=>!allowed.includes(k)))throw new Fault('invalid_receipt_keys');
      const c=this.s.commands[r.command_id];if(!c||r.db_id!==this.s.db.db_id||r.epoch!==this.s.db.epoch||r.request_sha256!==c.request_sha256)throw new Fault('invalid_receipt');
      if(!['applied','conflict','rejected'].includes(r.status)||typeof r.result_code!=='string'||!/^[a-z_]{1,64}$/.test(r.result_code))throw new Fault('invalid_receipt');
      const hash=await sha(Object.fromEntries(['command_id','status','result_code','task_id','business_revision','change_seq'].map(k=>[k,r[k]])));
      if(hash!==r.result_sha256)throw new Fault('invalid_result_hash');
      if(c.receipt){if(c.receipt.result_sha256!==hash)throw new Fault('receipt_conflict',409);ack.push(r.command_id);continue;}
      timestamp(r.processed_at);const lease=c.leases.find(l=>l.lease_id===r.lease_id&&l.lease_gen===r.lease_gen&&l.epoch===r.epoch);
      const expiredRejection=r.status==='rejected'&&r.result_code==='expired_deadline'&&r.processed_at>=c.execute_before;
      if(!lease||r.processed_at<lease.start||(!expiredRejection&&(r.processed_at>=lease.until||r.processed_at>=c.execute_before))||r.processed_at>this.now)throw new Fault('invalid_commit_time',409);
      if(['quarantined','lost_by_restore'].includes(c.state))throw new Fault('stale_history',409);
      c.after_void=c.state==='voided';c.state=r.status;c.task_id=r.task_id;c.receipt={...r};
      c.deadline=[c.deadline,plus(this.now,30*DAY),timestamp(r.record_deadline),...(r.task_deadline?[timestamp(r.task_deadline)]:[])].sort()[0];
      ack.push(r.command_id);
    }
    this.expire();return {acknowledged:ack};
  }
  async checkedItem(item:any,as_of:number){
    if(!Number.isSafeInteger(item.task_id)||item.task_id<1||!Number.isSafeInteger(item.change_seq)||item.change_seq<1||item.change_seq>as_of||!Number.isSafeInteger(item.episode)||item.episode<0||!['active','inactive','tombstone'].includes(item.lifecycle))throw new Fault('invalid_item');
    if(item.retention_deadline!==null)timestamp(item.retention_deadline);
    if(item.lifecycle!=='tombstone'&&(typeof item.business_revision!=='string'||!/^[a-f0-9]{64}$/.test(item.business_revision)))throw new Fault('invalid_revision');
    if(item.content){
      const fields='id title description due_date due_time category priority status no_due source_reference completed_at deleted_at'.split(' ');
      if(item.content.id!==item.task_id||await sha(Object.fromEntries(fields.map(k=>[k,item.content[k]])))!==item.business_revision)throw new Fault('invalid_revision');
    }
    return this.filteredItem(item);
  }
  filteredItem(item:any){const t=structuredClone(item);if(t.source_reference&&!/^(?:CLOUD:|PROJECT:)/.test(t.source_reference))t.source_reference=null;if(t.lifecycle==='tombstone'||t.lifecycle!=='active'&&(!t.retention_deadline||t.retention_deadline<=this.now))t.content=null;return t;}
  apply(item:any){
    const old=this.s.tasks[item.task_id];
    if(old?.lifecycle==='tombstone'&&item.lifecycle!=='tombstone')throw new Fault('terminal_tombstone',409);
    if(old&&old.epoch===this.s.db.epoch&&old.change_seq>item.change_seq)return;
    if(old&&old.epoch===this.s.db.epoch&&old.change_seq===item.change_seq&&(old.business_revision!==item.business_revision||old.lifecycle!==item.lifecycle))throw new Fault('version_collision',409);
    const t=this.filteredItem(item);t.epoch=this.s.db.epoch;t.confirmed_at=this.now;t.episode_deadlines={...old?.episode_deadlines};
    for(const [ep,deadline] of Object.entries(item.episode_deadlines||{})){timestamp(deadline);const prev=t.episode_deadlines[ep];t.episode_deadlines[ep]=prev&&prev<deadline?prev:deadline;}
    if(t.retention_deadline){const prev=t.episode_deadlines[t.episode];t.episode_deadlines[t.episode]=prev&&prev<t.retention_deadline?prev:t.retention_deadline;t.retention_deadline=t.episode_deadlines[t.episode];}
    if(old?.content_expired&&old.episode===t.episode&&t.lifecycle!=='active'){t.content=null;t.content_expired=true;}
    this.s.tasks[t.task_id]=t;this.s.db.max_task_id=Math.max(this.s.db.max_task_id,t.task_id);
  }
  async generation(action:string,b:any){
    this.identity(b);if(!uuid(b.generation))throw new Fault('invalid_generation');
    if(action==='start'){
      if(!Number.isSafeInteger(b.as_of)||b.as_of<this.s.db.acked||!Number.isSafeInteger(b.expected_count)||b.expected_count<0||b.expected_count>10000||!/^[0-9a-f]{64}$/.test(b.manifest_sha256))throw new Fault('invalid_generation');
      const old=this.s.generations[b.generation];if(old){if(old.as_of!==b.as_of||old.manifest!==b.manifest_sha256)throw new Fault('generation_reused',409);return {started:true};}
      // One active full generation per database.
      this.s.generations={[b.generation]:{as_of:b.as_of,count:b.expected_count,manifest:b.manifest_sha256,epoch:b.epoch,items:{},expires:plus(this.now,DAY)}};return {started:true};
    }
    const g=this.s.generations[b.generation];if(!g||g.epoch!==b.epoch||g.expires<=this.now)throw new Fault('generation_missing',409);
    if(action==='abort'){delete this.s.generations[b.generation];return {aborted:true};}
    if(action==='items'){
      if(!Array.isArray(b.items)||b.items.length>100)throw new Fault('invalid_items');
      for(const item of b.items){const checked=await this.checkedItem(item,g.as_of);const old=g.items[item.task_id];if(old&&canonical(old)!==canonical(checked))throw new Fault('duplicate_item_conflict',409);g.items[item.task_id]=checked;}
      if(Object.keys(g.items).length>g.count)throw new Fault('generation_count',409);return {stored:Object.keys(g.items).length};
    }
    if(action!=='finalize')throw new Fault('not_found',404);
    const items=Object.values(g.items).sort((a:any,b:any)=>a.task_id-b.task_id) as any[];
    const hash=await sha(items.map(i=>[i.task_id,i.change_seq,i.business_revision,i.lifecycle]));
    if(items.length!==g.count||hash!==g.manifest||g.as_of<this.s.db.acked)throw new Fault('generation_incomplete',409);
    for(const item of items)this.apply(item);
    for(const [id,t] of Object.entries(this.s.tasks))if(!g.items[id]&&(t.epoch<this.s.db.epoch||t.change_seq<=g.as_of))this.apply({...t,lifecycle:'tombstone',kind:'reconciled_missing',content:null,change_seq:g.as_of});
    this.s.db.acked=g.as_of;this.s.db.fenced=false;this.s.db.generation++;delete this.s.generations[b.generation];this.expire();return {...this.health(),finalized:true};
  }
  async changes(b:any){
    this.identity(b);if(b.from!==this.s.db.acked||!Number.isSafeInteger(b.to)||b.to<b.from||!Array.isArray(b.items)||b.items.length>100)throw new Fault('change_gap',409);
    if(!Array.isArray(b.events)||b.events.length!==b.to-b.from||b.events.length>100)throw new Fault('change_gap',409);
    const latest=new Map();for(let n=0;n<b.events.length;n++){const event=b.events[n];if(event.change_seq!==b.from+n+1||!Number.isSafeInteger(event.task_id)||event.task_id<1)throw new Fault('change_gap',409);latest.set(event.task_id,event.change_seq);}
    if(latest.size!==b.items.length||new Set(b.items.map(i=>i.task_id)).size!==b.items.length)throw new Fault('change_gap',409);
    for(const i of b.items){await this.checkedItem(i,b.to);if(i.change_seq!==latest.get(i.task_id))throw new Fault('change_gap',409);this.apply(i);}
    this.s.db.acked=b.to;this.expire();return this.health();
  }
  reconcile(b:any){
    if(b.db_id!==this.s.db.db_id||b.instance_id!==this.s.db.owner?.instance_id)throw new Fault('wrong_database',409);
    if(!uuid(b.reconcile_id))throw new Fault('invalid_reconcile');
    if(this.s.db.reconciles[b.reconcile_id])return this.s.db.reconciles[b.reconcile_id];
    this.identity(b);
    // A restored fork cannot overwrite cloud identities. Explicit fresh-db recovery is required.
    if(b.strategy!=='preserve-identities')throw new Fault('manual_fork_mapping_required',409);
    const result={reconcile_id:b.reconcile_id,epoch:this.s.db.epoch+1,acked:this.s.db.acked,max_task_id:this.s.db.max_task_id};
    for(const c of Object.values(this.s.commands))if(['queued','leased'].includes(c.state))c.state='quarantined';
    for(const c of Object.values(this.s.commands))if(c.state==='applied'&&c.receipt?.change_seq>b.max_change_seq)c.state='lost_by_restore';
    this.s.db.epoch++;this.s.db.fenced=true;this.s.db.reconciles[b.reconcile_id]=result;return result;
  }
  recoveryState(b:any){
    this.identity(b);if(!this.s.db.reconciles[b.reconcile_id]||!this.s.db.fenced)throw new Fault('reconcile_missing',409);
    this.expire();const all=Object.values(this.s.tasks).filter(t=>t.task_id>(b.after||0)).sort((a,b)=>a.task_id-b.task_id);
    const items=all.slice(0,50).map(t=>{const {content,...meta}=t;return meta;});
    return {items,next_after:items.length<all.length?items.at(-1).task_id:null};
  }
  list(actor:any,include_deleted=false,id?:number){
    this.expire();return Object.values(this.s.tasks).filter(t=>(actor.scope==='assistant'||actor.scope==='mail-automation'&&t.source_reference?.startsWith('PROJECT:'))&&(!id||t.task_id===id)&&(include_deleted||!t.deleted&&t.lifecycle!=='tombstone')).map(t=>({...t,authoritative:false}));
  }
}
