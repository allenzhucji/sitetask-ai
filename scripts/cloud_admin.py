"""Offline provisioning material generator. Does not call Cloudflare or deploy anything."""
import argparse,getpass,hashlib,hmac,json,secrets,uuid
from pathlib import Path

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db-id',required=True)
    parser.add_argument('--output',required=True,type=Path,help='Private directory OUTSIDE the source tree')
    parser.add_argument('--existing-pepper',action='store_true',help='Prompt for existing PEPPER when rotating credentials')
    args=parser.parse_args();db=str(uuid.UUID(args.db_id))
    root=Path(__file__).resolve().parents[1];out=args.output.resolve()
    if out==root or root in out.parents:parser.error('Credential output must be outside the source tree')
    out.mkdir(parents=True,exist_ok=True)
    if any(out.iterdir()):parser.error('Use an empty private output directory')
    pepper=getpass.getpass('Existing Worker PEPPER: ') if args.existing_pepper else secrets.token_hex(32)
    if len(pepper)<32:parser.error('PEPPER must have at least 32 characters')
    state={'db_id':db,'epoch':1,'acked':0,'max_task_id':0,'owner':None,'generation':0,'reconciles':{},'fenced':False}
    statements=[f"INSERT OR IGNORE INTO databases VALUES ('{db}','{json.dumps(state,separators=(',',':'))}');"]
    credentials={}
    for scope in ('bridge','assistant'):
        token_id=secrets.token_hex(8);secret=secrets.token_urlsafe(32)
        hashed=hmac.new(pepper.encode(),secret.encode(),hashlib.sha256).hexdigest()
        prefix='stb' if scope=='bridge' else 'stk';kind='bridge' if scope=='bridge' else 'submitter'
        credentials[scope]=f'{prefix}_{token_id}_{secret}'
        statements.append(f"INSERT INTO api_tokens(token_id,kind,scope,db_id,secret_hmac,label) VALUES('{token_id}','{kind}','{scope}','{db}','{hashed}','{scope}');")
    (out/'provision.sql').write_text('\n'.join(statements),encoding='utf-8')
    (out/'credentials.json').write_text(json.dumps(credentials,indent=2),encoding='utf-8')
    if not args.existing_pepper:(out/'PEPPER.txt').write_text(pepper,encoding='utf-8')
    (out/'README.txt').write_text('PRIVATE: Do not upload to GitHub or include in a release archive.\n'
        'provision.sql contains HMACs only. Enter PEPPER through wrangler secret put PEPPER.\n'
        'Paste only the bridge credential into the desktop Cloud bridge settings.\n'
        'Keep the assistant credential in the assistant connection secret store.\n'
        'No mail-automation credential is issued. Nothing has been deployed.\n',encoding='utf-8')
    print('Offline provisioning materials created in the requested private directory. Nothing deployed; no credentials printed.')

if __name__=='__main__':main()
