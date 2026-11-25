"""Private native transport; OS cookies stay in Electron, never in renderer or project."""
import json,os,urllib.request,urllib.error,hashlib,re,time
from pathlib import Path
def request(path,body=None,headers=None,raw=False):
 port=int(os.environ['FRAME_NATIVE_PORT']);token=os.environ['FRAME_NATIVE_TOKEN']
 if not(path.startswith('/api/desktop/')or re.fullmatch(r'/files/renders/local-[a-f0-9]{32}\.(mp4|png|wav)',path)):raise ValueError('Invalid remote route')
 h={'X-Native-Token':token,**(headers or {})}
 b=body if isinstance(body,bytes)else json.dumps(body).encode()if body is not None else None
 if b is not None:h['Content-Type']=h.get('Content-Type','application/json')
 req=urllib.request.Request('http://127.0.0.1:'+str(port)+path,data=b,headers=h)
 try:
  with urllib.request.urlopen(req,timeout=90)as r:out=r.read(34*1024**2)
 except urllib.error.HTTPError as e:
  try:msg=json.loads(e.read(2048)).get('error','Remote error')
  except Exception:msg='Remote connection failed'
  raise ValueError(msg)from None
 return out if raw else json.loads(out)
def remote_request(mailbox,payload,timeout=660,on_created=None):
 import uuid
 from providers import write_private
 ident=uuid.uuid4().hex;root=mailbox.root
 payload=json.loads(json.dumps(payload))
 account=request('/api/desktop/status')['account']
 if 'account'in payload:payload['account']=account
 if payload.get('kind')=='render':
  from objects import mapping,publish_local
  localdata=root.parent;originals=mapping(localdata)
  for f in payload.get('files',{}).values():
   if not f.get('objectId'):
    p=Path(f.get('desktopPath')or localdata/f['relative']).resolve()
    if not p.is_file():raise ValueError('Unavailable local input')
    o=publish_local(p,'reference'if p.suffix=='.cube'else'video')
    f.update(objectId=o['id'],bytes=o['bytes'],sha256=o['sha256'])
   f.pop('relative',None);f.pop('desktopPath',None)
 # POST is sent once; timeout/outcome unknown is not retried.
 request('/api/desktop/jobs/'+ident,{'payload':payload,'timeout':timeout})
 write_private(root/(ident+'.request.json'),{'id':ident,'kind':payload['kind'],'expires':time.time()+timeout})
 if on_created:on_created(ident)
 end=time.monotonic()+timeout;pause=None
 try:
  while time.monotonic()<end:
   if(root/(ident+'.cancel')).exists():
    request('/api/desktop/jobs/'+ident+'/cancel',{});raise ValueError('Задание отменено. Результат не применяется.')
   try:p=json.loads((root/(ident+'.pause.json')).read_text()).get('paused')
   except (OSError,ValueError):p=None
   if p is not None and p!=pause:request('/api/desktop/jobs/'+ident+('/pause'if p else'/resume'),{});pause=p
   r=request('/api/desktop/jobs/'+ident)
   if r.get('progress'):write_private(root/(ident+'.progress.json'),r['progress'])
   if r['status']=='done':
    result=r['result']
    if not result.get('ok'):raise ValueError(str(result.get('error','Сбой Аси / ПК'))[:500])
    out=result.get('output',{});name=out.get('name')
    if name:
     if not re.fullmatch(r'local-[a-f0-9]{32}\.(wav|png|mp4)',name):raise ValueError('Invalid output receipt')
     raw=request('/files/renders/'+name,raw=True)
     if hashlib.sha256(raw).hexdigest()!=out.get('sha256'):raise ValueError('Output SHA mismatch')
     dest=root.parent/'renders'/name
     if not dest.exists():
      tmp=dest.with_suffix(dest.suffix+'.part');tmp.write_bytes(raw);tmp.replace(dest)
    request('/api/desktop/jobs/'+ident+'/close',{})
    return result
   if r['status']in ['cancelled','expired']:raise ValueError('Задание не завершено; автоматического повтора нет.')
   time.sleep(1)
  request('/api/desktop/jobs/'+ident+'/cancel',{})
  raise ValueError('Истекло время ожидания Аси / ПК. Автоповтора нет.')
 finally:write_private(root/(ident+'.closed.json'),{'closed':time.time()})
