// Local-only test credentials. Never use this script against a remote D1 instance.
import {randomBytes,createHmac} from 'node:crypto';
import {readFileSync,writeFileSync,mkdirSync} from 'node:fs';
import {resolve} from 'node:path';
const dir=resolve(process.argv[2]);mkdirSync(dir,{recursive:true});
const identity=JSON.parse(readFileSync(resolve(dir,'identity.json'),'utf8'));
const pepper=randomBytes(32).toString('hex');
const db={db_id:identity.db_id,epoch:1,acked:0,max_task_id:0,owner:null,generation:0,reconciles:{},fenced:false};
const sql=[`INSERT OR REPLACE INTO databases VALUES('${identity.db_id}','${JSON.stringify(db)}');`];
const credentials={db_id:identity.db_id};
for(const scope of ['bridge','assistant']){
 const id=randomBytes(8).toString('hex'),secret=randomBytes(32).toString('base64url'),hmac=createHmac('sha256',pepper).update(secret).digest('hex');
 credentials[scope]=`${scope==='bridge'?'stb':'stk'}_${id}_${secret}`;
 sql.push(`INSERT INTO api_tokens(token_id,kind,scope,db_id,secret_hmac,label) VALUES('${id}','${scope==='bridge'?'bridge':'submitter'}','${scope}','${identity.db_id}','${hmac}','local-test');`);
}
writeFileSync(resolve(dir,'seed.sql'),sql.join('\n'));
writeFileSync(resolve(dir,'credentials.json'),JSON.stringify(credentials));
writeFileSync('.dev.vars','PEPPER='+pepper+'\n');
console.log('Local test seed created; no credentials printed.');
