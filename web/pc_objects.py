"""PC multipart output capability facade. Browser sessions never see object presigns."""
import re,json,time,hmac
from pathlib import Path
from providers import write_private
from objects import call

def receive(handler,data,prefix):
 match=re.fullmatch(re.escape(prefix)+r'/api/pc-object/(cat|code)/([a-f0-9]{32})/(init|part-url|part-done|complete|status)',handler.path)
 if not match:return False
 account,ident,op=match.groups()
 try:
  root=Path(data)/'bridge';job=json.loads((root/(ident+'.request.json')).read_text());cap=handler.headers.get('X-Frame-Result-Cap','')
  if Path(data).name!=account or job.get('kind')!='dubFull'or job.get('expires',0)<time.time()or len(cap)!=64 or not hmac.compare_digest(cap,job.get('resultCap',''))or any((root/(ident+s)).exists()for s in ['.closed.json','.cancel']):raise ValueError('Invalid PC object capability')
  size=int(handler.headers.get('Content-Length','0'))
  if not 0<size<=8192:raise ValueError('Invalid operation body')
  d=json.loads(handler.rfile.read(size));state=root/(ident+'.objects.json')
  try:ids=json.loads(state.read_text())
  except (OSError,ValueError):ids=[]
  if op=='init':
   if len(ids)>=5:raise ValueError('At most5 language objects per job')
   if not re.fullmatch(r'dub-(en|es|zh|pt|de|ru|fr|it|ja|ko)\.wav',str(d.get('name','')))or not 44<int(d.get('bytes',0))<=7200*48000*2+4096 or not re.fullmatch('[a-f0-9]{64}',str(d.get('sha256',''))):raise ValueError('Invalid alternate audio object')
   out=call('init',{**d,'expectedSHA256':d['sha256']});ids.append(out['id']);write_private(state,ids)
  else:
   id=d.get('objectId')
   if id not in ids:raise ValueError('Object belongs to another ticket')
   out=call(op,{'id':id,**{k:v for k,v in d.items()if k in ['part','sha256','etag','bytes']}})
  handler.reply(200,out)
 except Exception:handler.reply(403,{'error':'PC object capability/state rejected; no automatic retry'})
 return True
