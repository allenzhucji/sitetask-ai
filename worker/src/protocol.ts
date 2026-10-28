export class Fault extends Error {
  status: number;
  constructor(code: string, status=400) { super(code); this.status=status; }
}
export const bytes = (s:string) => new TextEncoder().encode(s);
export const canonical = (v:any):string => {
  if(v===null || typeof v==='boolean') return JSON.stringify(v);
  if(typeof v==='number' && Number.isSafeInteger(v)) return JSON.stringify(v);
  if(typeof v==='string' && v.isWellFormed()) return JSON.stringify(v);
  if(Array.isArray(v)) return '['+v.map(canonical).join(',')+']';
  if(v && typeof v==='object') return '{'+Object.keys(v).sort().map(k=>{
    if(!/^[\x00-\x7f]*$/.test(k)) throw new Fault('invalid_json_type');
    return JSON.stringify(k)+':'+canonical(v[k]);
  }).join(',')+'}';
  throw new Fault('invalid_json_type');
};
export async function sha(v:any) {
  const b=await crypto.subtle.digest('SHA-256',bytes(canonical(v)));
  return Array.from(new Uint8Array(b),x=>x.toString(16).padStart(2,'0')).join('');
}
export function parse(raw:string,limit=32768):any {
  if(bytes(raw).length>limit) throw new Fault('too_large',413);
  raw=raw.replace(/^\uFEFF/,''); let p=0;
  const ws=()=>{while(/[\x20\t\r\n]/.test(raw[p]||'!'))p++;};
  function value(depth=0):any {
    if(depth>64) throw new Fault('too_deep'); ws(); const ch=raw[p];
    if(ch==='"') {
      const start=p++; let escaped=false;
      while(p<raw.length){ const c=raw[p++]; if(c==='"'&&!escaped){const s=JSON.parse(raw.slice(start,p)); if(!s.isWellFormed())throw new Fault('invalid_unicode');return s;} if(c==='\\'&&!escaped)escaped=true;else escaped=false; }
      throw new Fault('invalid_json');
    }
    if(ch==='{') {
      p++; ws(); const o=Object.create(null); if(raw[p]==='}'){p++;return o;}
      while(true){ws();if(raw[p]!=='"')throw new Fault('invalid_json');const k=value(depth+1);if(Object.hasOwn(o,k))throw new Fault('duplicate_key');ws();if(raw[p++]!==':')throw new Fault('invalid_json');o[k]=value(depth+1);ws();const sep=raw[p++];if(sep==='}')return o;if(sep!==',')throw new Fault('invalid_json');}
    }
    if(ch==='['){p++;ws();const a=[];if(raw[p]===']'){p++;return a;}while(true){a.push(value(depth+1));ws();const sep=raw[p++];if(sep===']')return a;if(sep!==',')throw new Fault('invalid_json');}}
    for(const [literal,v] of [['true',true],['false',false],['null',null]] as const){if(raw.slice(p,p+literal.length)===literal){p+=literal.length;return v;}}
    const m=/^-?(?:0|[1-9][0-9]*)/.exec(raw.slice(p)); if(!m)throw new Fault('invalid_json');p+=m[0].length;
    if(/[.eE]/.test(raw[p]||'!'))throw new Fault('float_not_allowed');const n=Number(m[0]);if(!Number.isSafeInteger(n))throw new Fault('invalid_json_type');return n;
  }
  const v=value();ws();if(p!==raw.length)throw new Fault('invalid_json');canonical(v);return v;
}
const keys=(v:any,w:string[])=>v && typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).sort().join('|')===w.sort().join('|');
export const uuid=(s:any)=>typeof s==='string'&&/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(s);
export const ops=['create','update','get','complete','reopen','soft_delete','restore'];
const categories=['Site Inspection','IRF','EFI','Drawing','Method Statement','Material','Email','Meeting','Report','Follow-up','Personal','Other'];
export function validate(r:any) {
  if(!keys(r,['v','command_id','op','target','base_revision','fields','reason']))throw new Fault('invalid_keys');
  if(r.v!==1 || !ops.includes(r.op)||!uuid(r.command_id))throw new Fault('invalid_operation');
  if(r.op==='create'){if(r.target!==null||r.base_revision!==null)throw new Fault('invalid_create');}
  else{
    const t=r.target;
    if(keys(t,['task_id'])){if(!Number.isSafeInteger(t.task_id)||t.task_id<=0)throw new Fault('invalid_target');}
    else if(keys(t,['source_reference'])){if(typeof t.source_reference!=='string'||!(t.source_reference.startsWith('CLOUD:')?uuid(t.source_reference.slice(6)):/^PROJECT:[A-Za-z0-9][A-Za-z0-9:._-]{0,159}$/.test(t.source_reference)))throw new Fault('invalid_target');}
    else throw new Fault('invalid_target');
    if(r.op==='get'?r.base_revision!==null:typeof r.base_revision!=='string'||!/^[0-9a-f]{64}$/.test(r.base_revision))throw new Fault('invalid_revision');
  }
  if(['create','update'].includes(r.op)){
    const f=r.fields, allowed=['title','description','due_date','no_due','category','priority'];
    if(!f||typeof f!=='object'||Array.isArray(f)||!Object.keys(f).length||Object.keys(f).some(k=>!allowed.includes(k))||r.op==='create'&&!keys(f,allowed))throw new Fault('invalid_fields');
    for(const k of ['title','description'])if(k in f){const s=f[k];if(typeof s!=='string'||[...s].length>(k==='title'?200:6000)||[...s].some(ch=>{const n=ch.codePointAt(0)!;return(n<32||n>=127&&n<=159)&&!(k==='description'&&['\n','\t'].includes(ch));}))throw new Fault('invalid_text');}
    if('title'in f&&(!f.title||f.title.trim()!==f.title||/^\[?PROJECT\b/i.test(f.title)))throw new Fault('invalid_text');
    if('category'in f&&!categories.includes(f.category)||'priority'in f&&!['low','normal','high','urgent'].includes(f.priority))throw new Fault('invalid_enum');
    if('due_date'in f||'no_due'in f){if(typeof f.no_due!=='boolean'||!('due_date'in f))throw new Fault('invalid_date');if(f.no_due?f.due_date!==null:typeof f.due_date!=='string'||!/^\d{4}-\d\d-\d\d$/.test(f.due_date)||!Number.isFinite(Date.parse(f.due_date))||new Date(f.due_date).toISOString().slice(0,10)!==f.due_date||f.due_date.startsWith('0000'))throw new Fault('invalid_date');}
  }else if(r.fields!==null)throw new Fault('invalid_fields');
  if(r.reason!==null&&(typeof r.reason!=='string'||[...r.reason].length>200))throw new Fault('invalid_reason');
  if(bytes(canonical(r)).length>32768)throw new Fault('too_large');return r;
}
export function authorize(r:any,scope:string){
  if(scope==='assistant')return;
  if(scope!=='mail-automation'||!['update','get'].includes(r.op)||!r.target?.source_reference?.startsWith('PROJECT:'))throw new Fault('forbidden_scope',403);
}
export function timestamp(s:any){if(typeof s!=='string'||!/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/.test(s)||new Date(s).toISOString()!==s)throw new Fault('invalid_timestamp');return s;}
export const plus=(s:string,ms:number)=>new Date(Date.parse(s)+ms).toISOString();
