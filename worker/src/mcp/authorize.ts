import {AuthorizationError,CimdFetchError} from '@cloudflare/workers-oauth-provider';
import {type McpEnv,SCOPES,allowedRedirect,escapeHtml as esc,pairingHash,boundedText,safeHeaders} from './common.ts';

export async function authorize(req:Request,env:McpEnv):Promise<Response>{
  const oauth=env.OAUTH_PROVIDER;let pairingConsumed=false;
  try {
    if(req.method==='GET'){
      const auth=await oauth.parseAuthRequest(req);
      if(!allowedRedirect(auth.redirectUri))return new Response('Only ChatGPT callbacks are enabled.',{status:400,headers:safeHeaders()});
      if(auth.codeChallengeMethod!=='S256'||!auth.codeChallenge)throw new Error('pkce_required');
      const details=await oauth.describeConsent(auth),consent=await oauth.beginConsent(auth);
      const checks=details.scope.map(s=>`<label><input type="checkbox" name="scope" value="${esc(s)}" checked> ${esc(s==='tasks:read'?'读取任务及同步状态':s==='tasks:write'?'创建、修改、完成、移入回收站和恢复任务':s==='offline_access'?'保持连接（可撤销）':s)}</label>`).join('<br>');
      const page=`<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>连接 SiteTask AI</title><style>body{font:16px system-ui;max-width:560px;margin:48px auto;padding:24px;color:#18212b}label{line-height:2}input[type=password]{width:95%;padding:12px;margin:12px 0}button{padding:12px 20px;margin:12px 8px 0 0}small{color:#566}</style><h1>连接你的 SiteTask AI</h1><p>申请应用：<strong>${esc(details.clientName)}</strong></p><p>${details.clientDomain?'客户端域名：'+esc(details.clientDomain):'应用名称由客户端自行声明，请核对返回地址。'}</p><p>授权完成后返回：<strong>${esc(details.redirectHost)}</strong></p><p>请输入本机生成的一次性连接码，然后确认授权。此页面不需要你的 Google 或 Cloudflare 密码。</p><form method="post" action="/authorize"><input type="hidden" name="handle" value="${esc(consent.handle)}"><label>一次性连接码<input type="password" name="pairing_code" autocomplete="off" maxlength="64"></label>${checks}<p><button name="decision" value="approve">授权连接</button><button name="decision" value="deny">取消</button></p></form><p><small>修改任务需要桌面程序运行并联网。云端删除仅进入回收站，不提供永久删除。</small></p></html>`;
      for(const [k,v] of safeHeaders())consent.headers.set(k,v);
      // HTML form navigations need a non-null Origin for the strict CSRF check.
      consent.headers.set('Referrer-Policy','same-origin');
      // Browsers enforce form-action on the OAuth redirect after POST too.
      // Only the exact callback validated above is allowed.
      consent.headers.set('Content-Security-Policy',safeHeaders().get('Content-Security-Policy')!.replace("form-action 'self'","form-action 'self' "+auth.redirectUri));
      consent.headers.set('Content-Type','text/html; charset=utf-8');return new Response(page,{headers:consent.headers});
    }
    if(req.method!=='POST')return new Response('Method not allowed',{status:405,headers:safeHeaders()});
    if(req.headers.get('Origin')!==env.ORIGIN)return new Response('Invalid origin',{status:403,headers:safeHeaders()});
    if(!req.headers.get('Content-Type')?.startsWith('application/x-www-form-urlencoded'))return new Response('Invalid form',{status:415,headers:safeHeaders()});
    const form=new URLSearchParams(await boundedText(req,8192)),handle=form.get('handle')||'';
    if(form.get('decision')==='deny'){
      const denied=await oauth.denyConsent(req,handle);return new Response(null,{status:302,headers:denied.headers});
    }
    if(form.get('decision')!=='approve')throw new Error('invalid_decision');
    const scopes=form.getAll('scope');if(!scopes.length||scopes.some(s=>!SCOPES.includes(s)))throw new Error('invalid_scope');
    const code=(form.get('pairing_code')||'').trim();if(!/^[A-Za-z0-9_-]{43}$/.test(code))throw new Error('invalid_pairing_code');
    const hash=await pairingHash(code);
    const pair:any=await env.DB.prepare('SELECT db_id FROM mcp_pairings WHERE code_hash=? AND used_at IS NULL AND expires_at>?').bind(hash,Date.now()).first();
    if(!pair||pair.db_id!==env.DATABASE_ID)throw new Error('invalid_pairing_code');
    const approved=await oauth.approveConsent(req,handle,{scope:scopes});
    if(!allowedRedirect(approved.request.redirectUri))throw new Error('invalid_redirect');
    // D1 compare-and-set makes the high-entropy pairing code single-use across all PoPs.
    const used:any=await env.DB.prepare('UPDATE mcp_pairings SET used_at=? WHERE code_hash=? AND used_at IS NULL AND expires_at>? RETURNING db_id').bind(Date.now(),hash,Date.now()).first();
    if(!used||used.db_id!==env.DATABASE_ID)throw new Error('invalid_pairing_code');
    pairingConsumed=true;
    const {redirectTo}=await oauth.completeAuthorization({request:approved.request,userId:env.DATABASE_ID,metadata:{label:'SiteTask AI personal task library'},scope:scopes,props:{db_id:env.DATABASE_ID}});
    approved.headers.set('Location',redirectTo);approved.headers.set('Cache-Control','no-store');return new Response(null,{status:302,headers:approved.headers});
  }catch(error){
    // Never redirect on an untrusted or reconstructed request, and never log form credentials.
    const message=pairingConsumed?'连接码已验证，但授权未能完成。请联系维护者签发新码后重新连接。':error instanceof Error&&error.message==='invalid_pairing_code'?'连接码无效、已使用或已过期，请检查后从 ChatGPT 重新连接。':'授权请求已失效或服务暂时不可用，请从 ChatGPT 重新连接。';
    return new Response(message,{status:400,headers:{...Object.fromEntries(safeHeaders()),'Content-Type':'text/plain; charset=utf-8'}});
  }
}
