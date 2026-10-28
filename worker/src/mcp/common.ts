export interface McpEnv {
  OAUTH_KV: KVNamespace;
  AUTH_LIMITER: RateLimit;
  DB: D1Database;
  BRIDGE: Fetcher;
  OAUTH_PROVIDER: import('@cloudflare/workers-oauth-provider').OAuthHelpers;
  ORIGIN: string;
  BRIDGE_ORIGIN: string;
  DATABASE_ID: string;
  ASSISTANT_TOKEN: string;
}
export const READ='tasks:read', WRITE='tasks:write';
export const SCOPES=[READ,WRITE,'offline_access'];
export function allowedRedirect(value:string){
  try { const u=new URL(value);return u.protocol==='https:'&&u.hostname==='chatgpt.com'&&!u.port&&!u.username&&!u.password&&!u.hash&&(u.pathname==='/connector_platform_oauth_redirect'||/^\/connector\/oauth\/[a-zA-Z0-9_-]+$/.test(u.pathname))&&!u.search; }catch{return false;}
}
export function escapeHtml(value:string){return value.replace(/[&<>"']/g,c=>'&#'+c.charCodeAt(0)+';');}
export async function pairingHash(code:string){return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(code))),x=>x.toString(16).padStart(2,'0')).join('');}
export async function boundedText(req:Request,limit:number){
  const reader=req.body?.getReader();if(!reader)return '';
  const chunks:Uint8Array[]=[];let size=0;
  try{while(true){const {done,value}=await reader.read();if(done)break;size+=value.length;if(size>limit){await reader.cancel();throw new Error('request_too_large');}chunks.push(value);}}finally{reader.releaseLock();}
  const all=new Uint8Array(size);let pos=0;for(const c of chunks){all.set(c,pos);pos+=c.length;}
  return new TextDecoder('utf-8',{fatal:true}).decode(all);
}
export function safeHeaders(){return new Headers({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','X-Frame-Options':'DENY','Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"});}
