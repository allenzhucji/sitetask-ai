import {OAuthProvider} from '@cloudflare/workers-oauth-provider';
import {authorize} from './authorize.ts';
import {mcp} from './tools.ts';
import {type McpEnv,READ,WRITE,SCOPES,allowedRedirect,safeHeaders,boundedText} from './common.ts';

export function provider(env:McpEnv){
 return new OAuthProvider<McpEnv>({
  apiRoute:'/mcp',apiHandler:{fetch:mcp},
  defaultHandler:{async fetch(req,bindings){
   const path=new URL(req.url).pathname;
   if(path==='/authorize')return authorize(req,bindings);
   if(path==='/')return new Response('SiteTask AI — connect this private task service in ChatGPT using /mcp. OAuth authorization is required.',{headers:safeHeaders()});
   return new Response('Not found',{status:404,headers:safeHeaders()});
  }},
  authorizeEndpoint:env.ORIGIN+'/authorize',tokenEndpoint:env.ORIGIN+'/oauth/token',clientRegistrationEndpoint:env.ORIGIN+'/oauth/register',
  scopesSupported:SCOPES,requiredScopes:[READ,WRITE],
  resourceMetadata:{resource:env.ORIGIN+'/mcp',authorization_servers:[env.ORIGIN],resource_name:'SiteTask AI'},
  clientIdMetadataDocumentEnabled:true,
  clientRegistrationTTL:undefined,accessTokenTTL:3600,refreshTokenTTL:2592000,
  clientRegistrationCallback:({clientMetadata})=>{
   const uris=clientMetadata.redirect_uris;
   if(!Array.isArray(uris)||!uris.length||uris.some(u=>typeof u!=='string'||!allowedRedirect(u)))return {code:'invalid_redirect_uri',description:'Only ChatGPT callbacks are enabled.'};
  },
 });
}
export default {
 async fetch(req:Request,env:McpEnv,ctx:ExecutionContext){
  const url=new URL(req.url);
  if(url.origin!==env.ORIGIN)return new Response('Wrong origin',{status:400});
  const origin=req.headers.get('Origin');
  if(origin&&![env.ORIGIN,'https://chatgpt.com'].includes(origin))return new Response('Forbidden origin',{status:403});
  if(Number(req.headers.get('Content-Length')||0)>65536)return new Response('Request too large',{status:413});
  if(url.pathname==='/authorize'||url.pathname.startsWith('/oauth/')){
   const permitted=await env.AUTH_LIMITER.limit({key:req.headers.get('CF-Connecting-IP')||'local'});
   if(!permitted.success)return new Response('Please retry in one minute.',{status:429,headers:{'Retry-After':'60'}});
  }
  if(req.method==='POST'){
   try{const text=await boundedText(req,65536);req=new Request(req,{body:text});}catch{return new Response('Request too large or invalid',{status:413});}
  }
  try{return await provider(env).fetch(req,env,ctx);}catch{return new Response('Service temporarily unavailable',{status:503,headers:safeHeaders()});}
 }
};
