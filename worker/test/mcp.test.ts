import {test} from 'node:test';
import assert from 'node:assert/strict';
import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {InMemoryTransport} from '@modelcontextprotocol/sdk/inMemory.js';
import {createServer} from '../src/mcp/tools.ts';
import {allowedRedirect,escapeHtml,pairingHash,boundedText} from '../src/mcp/common.ts';
async function setup(scopes=['tasks:read','tasks:write']){
 const calls:any[]=[];const server=createServer({ORIGIN:'https://test.example',DATABASE_ID:'personal'},scopes,async(path,body)=>{calls.push({path,body});return {state:'queued',command_id:body?.command_id||null};});
 const client=new Client({name:'test',version:'1'});const [a,b]=InMemoryTransport.createLinkedPair();await server.connect(b);await client.connect(a);return {calls,server,client,close:async()=>{await client.close();await server.close();}};
}
test('MCP advertises only supported task tools and safe annotations',async()=>{
 const x=await setup();try{const {tools}=await x.client.listTools();assert.equal(tools.length,12);assert.ok(tools.every(t=>!t.name.includes('purge')));assert.equal(tools.find(t=>t.name==='soft_delete_task')!.annotations!.destructiveHint,true);assert.equal(tools.find(t=>t.name==='get_task')!.annotations!.readOnlyHint,true);}finally{await x.close();}
});
test('MCP create preserves immutable id and all fields without claiming execution',async()=>{
 const x=await setup();try{const id=crypto.randomUUID();const args={command_id:id,fields:{title:'Task',description:'',due_date:null,no_due:true,category:'Other',priority:'normal'}};const r:any=await x.client.callTool({name:'create_task',arguments:args});assert.equal(r.structuredContent.state,'queued');assert.equal(x.calls[0].body.command_id,id);assert.equal(x.calls[0].body.target,null);assert.equal(x.calls[0].body.base_revision,null);await x.client.callTool({name:'create_task',arguments:args});assert.deepEqual(x.calls[0],x.calls[1]);}finally{await x.close();}
});
test('MCP read-only authorization cannot submit writes or cancel commands',async()=>{
 const x=await setup(['tasks:read']);try{for(const name of ['cancel_queued_command','complete_task']){const args:any={command_id:crypto.randomUUID()};if(name==='complete_task')Object.assign(args,{task_id:1,base_revision:'a'.repeat(64)});const r:any=await x.client.callTool({name,arguments:args});assert.equal(r.isError,true);assert.equal(r.structuredContent.error,'insufficient_scope');}assert.equal(x.calls.length,0);await x.client.callTool({name:'get_connection_status',arguments:{}});assert.equal(x.calls.length,1);}finally{await x.close();}
});
test('MCP schema rejects unknown fields, missing revisions and invalid ids',async()=>{
 const x=await setup();try{for(const [name,args] of [['get_task',{task_id:'1'}],['update_task',{command_id:crypto.randomUUID(),task_id:1,fields:{title:'x'}}],['get_connection_status',{token:'leak'}]]){const r:any=await x.client.callTool({name:String(name),arguments:args as any});assert.equal(r.isError,true);}assert.equal(x.calls.length,0);}finally{await x.close();}
});
test('MCP get is an asynchronous read; update carries revision and content',async()=>{
 const x=await setup();try{await x.client.callTool({name:'read_task_live',arguments:{command_id:crypto.randomUUID(),task_id:7}});assert.equal(x.calls[0].body.op,'get');assert.equal(x.calls[0].body.fields,null);await x.client.callTool({name:'update_task',arguments:{command_id:crypto.randomUUID(),task_id:7,base_revision:'b'.repeat(64),fields:{title:'new'}}});assert.equal(x.calls[1].body.base_revision,'b'.repeat(64));assert.deepEqual(x.calls[1].body.fields,{title:'new'});}finally{await x.close();}
});
test('OAuth callbacks are exact ChatGPT HTTPS destinations, never open redirects',()=>{
 assert.ok(allowedRedirect('https://chatgpt.com/connector_platform_oauth_redirect'));assert.ok(allowedRedirect('https://chatgpt.com/connector/oauth/test_123'));
 for(const u of ['https://chatgpt.com.evil.example/connector_platform_oauth_redirect','http://chatgpt.com/connector_platform_oauth_redirect','https://chatgpt.com@evil.example/connector_platform_oauth_redirect','https://chatgpt.com/connector_platform_oauth_redirect?next=https://evil.example','https://chatgpt.com/other','https://localhost/callback'])assert.equal(allowedRedirect(u),false,u);
});
test('Consent HTML escapes all client supplied strings and pairing hashes are deterministic',async()=>{
 assert.equal(escapeHtml('<script>"&'), '&#60;script&#62;&#34;&#38;');assert.equal((await pairingHash('x')).length,64);assert.equal(await pairingHash('x'),await pairingHash('x'));assert.notEqual(await pairingHash('x'),await pairingHash('y'));
});
test('Request bound applies without trusting Content-Length',async()=>{
 await assert.rejects(()=>boundedText(new Request('https://x',{method:'POST',body:'12345'}),4),/too_large/);assert.equal(await boundedText(new Request('https://x',{method:'POST',body:'1234'}),4),'1234');
});
test('Worker transport rejects redirects without following or disclosing the backend credential',async()=>{
 const {mcp}=await import('../src/mcp/tools.ts');let calls=0;
 const env:any={ORIGIN:'https://test.example',DATABASE_ID:'personal',BRIDGE_ORIGIN:'https://backend.example',ASSISTANT_TOKEN:'synthetic-test-credential',BRIDGE:{async fetch(url:string,options:any){calls++;assert.equal(options.redirect,'manual');assert.equal(options.headers.Authorization,'Bearer synthetic-test-credential');return new Response(null,{status:302,headers:{Location:'https://untrusted.example'}});}}};
 const req=new Request('https://test.example/mcp',{method:'POST',headers:{'Content-Type':'application/json',Accept:'application/json, text/event-stream'},body:JSON.stringify({jsonrpc:'2.0',id:1,method:'tools/call',params:{name:'get_connection_status',arguments:{}}})});
 const response=await mcp(req,env,{props:{db_id:'personal'},auth:{scope:['tasks:read']}});const result:any=await response.json();assert.equal(calls,1);assert.equal(result.result.structuredContent.error,'bridge_redirect_rejected');assert.ok(!JSON.stringify(result).includes(env.ASSISTANT_TOKEN));
});
test('Worker rejects a token for a different database before any tool or backend access',async()=>{
 const {mcp}=await import('../src/mcp/tools.ts');const response=await mcp(new Request('https://test.example/mcp'),{DATABASE_ID:'personal'} as any,{props:{db_id:'other'},auth:{scope:['tasks:read','tasks:write']}});assert.equal(response.status,403);
});
