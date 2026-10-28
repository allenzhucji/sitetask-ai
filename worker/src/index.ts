import {Engine, initial, type State} from './engine.ts';
import {Fault,parse,canonical,bytes} from './protocol.ts';
type Env={DB:D1Database,COORDINATOR:DurableObjectNamespace,PEPPER:string};
export async function hmac(secret:string,pepper:string){
  const k=await crypto.subtle.importKey('raw',bytes(pepper),{name:'HMAC',hash:'SHA-256'},false,['sign']);
  const b=await crypto.subtle.sign('HMAC',k,bytes(secret));return Array.from(new Uint8Array(b),x=>x.toString(16).padStart(2,'0')).join('');
}
export function equal(a:string,b:string){let diff=a.length^b.length;for(let i=0;i<64;i++)diff|=(a.charCodeAt(i)||0)^(b.charCodeAt(i)||0);return diff===0;}
async function auth(req:Request,env:Env){
  const match=/^Bearer (st[kb])_([0-9a-f]{16})_([A-Za-z0-9_-]{43})$/.exec(req.headers.get('Authorization')||'');
  if(!match||!env.PEPPER)throw new Fault('unauthorized',401);
  const row:any=await env.DB.prepare('SELECT * FROM api_tokens WHERE token_id=?').bind(match[2]).first();
  const hash=await hmac(match[3],env.PEPPER);
  if(!row||!equal(row.secret_hmac,hash)||row.revoked_at||match[1]!== (row.kind==='bridge'?'stb':'stk'))throw new Fault('unauthorized',401);
  const bridge=new URL(req.url).pathname.startsWith('/v1/bridge/');if(bridge!== (row.kind==='bridge'))throw new Fault('forbidden_route',403);
  return row;
}
async function body(req:Request){
  const reader=req.body?.getReader();if(!reader)return {};
  let raw=new Uint8Array(0);try{while(true){const {value,done}=await reader.read();if(done)break;if(raw.length+value.length>256*1024)throw new Fault('too_large',413);const n=new Uint8Array(raw.length+value.length);n.set(raw);n.set(value,raw.length);raw=n;}}finally{reader.releaseLock();}
  try{return parse(new TextDecoder('utf-8',{fatal:true}).decode(raw),256*1024);}catch(e){if(e instanceof Fault)throw e;throw new Fault('invalid_json');}
}
const response=(v:any,status=200)=>new Response(canonical(v),{status,headers:{'Content-Type':'application/json','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}});
const failure=(e:any)=>response({error:e instanceof Fault?e.message:'internal_error'},e instanceof Fault?e.status:500);
export class DbCoordinator {
  env:Env; tail:Promise<any>=Promise.resolve();
  constructor(_ctx:DurableObjectState,env:Env){this.env=env;}
  fetch(req:Request):Promise<Response>{
    // Serialize every request across all awaits, including commands and cleanup.
    const job=this.tail.then(()=>this.handle(req));this.tail=job.catch(()=>{});return job;
  }
  async load(id:string):Promise<State>{
    const row:any=await this.env.DB.prepare('SELECT body FROM databases WHERE db_id=?').bind(id).first();
    if(!row)throw new Fault('database_not_enrolled',404);
    const s=initial(id);s.db=JSON.parse(row.body);
    for(const [key,table] of [['commands','commands'],['tasks','task_mirror'],['generations','generations']]){
      const result=await this.env.DB.prepare(`SELECT id,body FROM ${table} WHERE db_id=?`).bind(id).all();
      s[key]=Object.fromEntries(result.results.map((r:any)=>[r.id,JSON.parse(r.body)]));
    }return s;
  }
  async save(before:State,after:State){
    const id=after.db.db_id,sql=[this.env.DB.prepare('UPDATE databases SET body=? WHERE db_id=?').bind(canonical(after.db),id)];
    for(const [key,table] of [['commands','commands'],['tasks','task_mirror'],['generations','generations']]){
      for(const [k,v] of Object.entries(after[key]))if(!before[key][k]||canonical(v)!==canonical(before[key][k]))sql.push(this.env.DB.prepare(`INSERT INTO ${table}(db_id,id,body) VALUES(?,?,?) ON CONFLICT(db_id,id) DO UPDATE SET body=excluded.body`).bind(id,k,canonical(v)));
      for(const k of Object.keys(before[key]))if(!after[key][k])sql.push(this.env.DB.prepare(`DELETE FROM ${table} WHERE db_id=? AND id=?`).bind(id,k));
    }
    // D1 batch is atomic; no state is cached across failed commits.
    await this.env.DB.batch(sql);
  }
  async handle(req:Request){
    try{
      const url=new URL(req.url),path=url.pathname;
      // Cron enters the same serialization barrier, never mutates D1 directly.
      if(path==='/internal/expire'){
        const id=url.searchParams.get('db_id')!,before=await this.load(id),s=structuredClone(before);new Engine(s).expire();await this.save(before,s);return response({ok:true});
      }
      const actor=await auth(req,this.env),before=await this.load(actor.db_id),s=structuredClone(before),engine=new Engine(s);
      const b=req.method==='POST'?await body(req):{};
      let result:any;
      if(path==='/v1/commands'&&req.method==='POST')result=await engine.submit(b,actor);
      else if(/^\/v1\/commands\/[^/]+$/.test(path)&&req.method==='GET')result=engine.command(s.commands[path.split('/')[3]],actor);
      else if(/^\/v1\/commands\/[^/]+\/cancel$/.test(path)&&req.method==='POST')result=engine.cancel(path.split('/')[3],actor);
      else if(path==='/v1/health'&&req.method==='GET')result=engine.health();
      else if((path==='/v1/tasks'||/^\/v1\/tasks\/[1-9][0-9]*$/.test(path))&&req.method==='GET'){
        const id=path==='/v1/tasks'?undefined:Number(path.split('/')[3]);const cursor=Number(url.searchParams.get('after')||0);
        const all=engine.list(actor,url.searchParams.get('include_deleted')==='true',id).filter(t=>t.task_id>cursor).sort((a,b)=>a.task_id-b.task_id);
        const items=[];let size=0;for(const t of all){const n=bytes(canonical(t)).length;if(items.length>=50||size+n>192*1024)break;items.push(t);size+=n;}
        result={items,authoritative:false,next_after:items.length<all.length?items.at(-1)?.task_id||null:null};
      }
      else if(req.method==='POST'&&path.startsWith('/v1/bridge/')){
        const rows=await this.env.DB.prepare('SELECT token_id FROM api_tokens WHERE db_id=? AND revoked_at IS NOT NULL').bind(actor.db_id).all();
        const revoked=new Set(rows.results.map((r:any)=>r.token_id as string));
        if(path==='/v1/bridge/enroll')result=engine.bind(b,actor);
        else if(path==='/v1/bridge/pull')result=engine.pull(b,revoked);
        else if(path==='/v1/bridge/lease/renew')result=engine.renew(b,revoked);
        else if(path==='/v1/bridge/receipts')result=await engine.receipts(b);
        else if(path==='/v1/bridge/changes')result=await engine.changes(b);
        else if(path.startsWith('/v1/bridge/generation/'))result=await engine.generation(path.split('/').at(-1)!,b);
        else if(path==='/v1/bridge/reconcile')result=engine.reconcile(b);
        else if(path==='/v1/bridge/reconcile/state')result=engine.recoveryState(b);
        else throw new Fault('not_found',404);
      }else throw new Fault('not_found',404);
      engine.expire();const raw=canonical(result);if(bytes(raw).length>256*1024)throw new Fault('response_too_large',413);
      await this.save(before,s);return response(result,path==='/v1/commands'&&!before.commands[b.command_id]?202:200);
    }catch(e){return failure(e);}
  }
}
export default {
  async fetch(req:Request,env:Env){try{
    if(!new URL(req.url).pathname.startsWith('/v1/'))throw new Fault('not_found',404);
    const actor=await auth(req,env);return env.COORDINATOR.get(env.COORDINATOR.idFromName(actor.db_id)).fetch(req);
  }catch(e){return failure(e);}},
  async scheduled(_event:ScheduledEvent,env:Env){
    const rows=await env.DB.prepare('SELECT db_id FROM databases').all();
    for(const row of rows.results){await env.COORDINATOR.get(env.COORDINATOR.idFromName(String(row.db_id))).fetch('https://internal/internal/expire?db_id='+encodeURIComponent(String(row.db_id)));}
  }
};
