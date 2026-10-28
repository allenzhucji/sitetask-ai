"""Issue a one-use Dot pairing code. Requires an authenticated Wrangler installation.
The code is stored in Windows Credential Manager and the explicitly requested local file.
No secret is printed, sent to ChatGPT, or placed in the source tree.
"""
import argparse,datetime,hashlib,json,secrets,subprocess,tempfile,uuid
from pathlib import Path
import keyring

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--db-id',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 db=str(uuid.UUID(a.db_id));source=Path(__file__).resolve().parents[1];out=a.output.resolve()
 if out==source or source in out.parents:p.error('Output must be outside the source tree')
 code=secrets.token_urlsafe(32);now=datetime.datetime.now(datetime.timezone.utc);expiry=now+datetime.timedelta(hours=24)
 sql="UPDATE mcp_pairings SET used_at=%d WHERE db_id='%s' AND used_at IS NULL;\nINSERT INTO mcp_pairings VALUES ('%s','%s',%d,NULL);"%(int(now.timestamp()*1000),db,hashlib.sha256(code.encode()).hexdigest(),db,int(expiry.timestamp()*1000))
 worker=source/'worker'
 with tempfile.TemporaryDirectory(prefix='sitetask-dot-') as tmp:
  path=Path(tmp)/'pairing.sql';path.write_text(sql)
  result=subprocess.run(['node',str(worker/'node_modules/wrangler/bin/wrangler.js'),'d1','execute','DB','--remote','--config','wrangler.mcp.toml','--file',str(path),'--yes'],cwd=worker,capture_output=True,text=True)
  if result.returncode:raise RuntimeError('Cloudflare provisioning failed; no code issued. Check Wrangler authentication and connectivity.')
 keyring.set_password('SiteTaskAICloudDeploy',db+':dot-pairing',code)
 out.parent.mkdir(parents=True,exist_ok=True)
 out.write_text('SiteTask AI — Dot 一次性连接码（仅本人使用）\n\n'+code+'\n\n到期时间：'+expiry.isoformat(timespec='seconds')+'（UTC）\n\n仅在你配置的 MCP 服务授权页面输入。不要粘贴到聊天。使用一次即失效。\n',encoding='utf-8')
 print('One-use pairing code issued to the requested local file; expires in 24 hours.')
if __name__=='__main__':main()
