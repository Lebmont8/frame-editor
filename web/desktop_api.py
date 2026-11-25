"""Account-authenticated desktop mailbox. No engine/project switching or executable paths."""
import base64,hashlib,json,re,time,threading
from pathlib import Path
from providers import write_private
from bridge import Mailbox
from objects import call
LIMIT=24*1024**2
ID=re.compile(r'[a-f0-9]{32}')
gate=threading.RLock()
def validate(payload,account):
 if not isinstance(payload,dict):raise ValueError('Invalid payload')
 kind=payload.get('kind')
 if kind not in ['structured','transcribe','generate','render','pcOpen','image','perceive','dubFull']:raise ValueError('Unsupported job')
 if set(payload)&{'id','created','expires','returnUrl','resultCap','closed'}:raise ValueError('Reserved fields')
 if 'account'in payload and payload['account']!=account:raise ValueError('Wrong account')
 if kind=='structured':
  if not isinstance(payload.get('prompt'),str)or len(payload['prompt'])>200000 or not isinstance(payload.get('schema'),dict):raise ValueError('Invalid editorial data')
  if len(payload.get('images',[]))>32:raise ValueError('Too many frames')
 if kind=='transcribe'and(payload.get('encoding')!='wav-zlib'or not isinstance(payload.get('audio'),str)or len(payload['audio'])>14000000):raise ValueError('Invalid audio')
 if kind=='generate'and(payload.get('operation')not in ['speech','video','image']or not 0<=int(payload.get('seed',42))<2**31 or payload.get('frames',33)not in [17,33,49]):raise ValueError('Invalid generation')
 if kind=='pcOpen':
  if not ID.fullmatch(str(payload.get('pcJobId',''))):raise ValueError('Invalid PC job')
 if kind in ['generate','render','image','perceive','dubFull']:
  if payload.get('extension')not in ['wav','png','mp4']:raise ValueError('Invalid output')
  payload['account']=account
 if kind=='render':
  if payload.get('mode')=='redeliver':
   if not ID.fullmatch(str(payload.get('sourceJobId',''))):raise ValueError('Invalid prior job')
  else:
   files=payload.get('files')
   if not isinstance(files,dict)or len(files)>100 or not isinstance(payload.get('project'),dict):raise ValueError('Invalid snapshot')
   for key,f in files.items():
    if not ID.fullmatch(key)or not ID.fullmatch(str(f.get('objectId',''))):raise ValueError('Desktop inputs must be account-owned objects')
    o=call('status',{'id':f['objectId']})
    if o.get('status')!='ready'or o['sha256']!=f.get('sha256')or o['bytes']!=f.get('bytes'):raise ValueError('Input SHA/size mismatch')
    if f.get('suffix')not in ['.mp4','.mov','.mkv','.webm','.wav','.mp3','.flac','.png','.jpg','.jpeg','.cube']:raise ValueError('Invalid input type')
    f.pop('relative',None)
   def walk(n):
    if isinstance(n,dict):
     f=n.get('File')
     if isinstance(f,dict)and 'path'in f:
      p=f['path']
      if not isinstance(p,str)or not p.startswith('FRAME_INPUT:')or p[12:]not in files:raise ValueError('Unbound media path')
     text=n.get('Text')
     if isinstance(text,str)and text.endswith('.cube')and not text.startswith('FRAME_LUT:'):raise ValueError('Unbound LUT')
     for v in n.values():walk(v)
    elif isinstance(n,list):
     for v in n:walk(v)
   walk(payload['project'])
 return payload
def handle(h,data,prefix,capacity):
 path=h.path.split('?',1)[0];base=prefix+'/api/desktop'
 if not path.startswith(base+'/'):return False
 account=Path(data).name
 if account not in ['cat','code']:raise ValueError('Desktop endpoint requires account isolation')
 root=Mailbox(data).root
 def body(limit=LIMIT):
  n=int(h.headers.get('Content-Length','0'))
  if not 0<n<=limit or h.headers.get('Transfer-Encoding'):raise ValueError('Request too large')
  raw=h.rfile.read(n)
  if len(raw)!=n:raise ValueError('Interrupted request')
  return json.loads(raw)
 if h.command=='GET'and path==base+'/updates':
  try:envelope=json.loads(Path(__import__('os').environ.get('FRAME_UPDATE_INDEX','updates.json')).read_text())
  except(FileNotFoundError,ValueError):h.reply(503,{'error':'Обновление временно недоступно'});return True
  h.reply(200,envelope);return True
 if h.command=='GET'and path==base+'/releases':
  try:release=json.loads(Path(__import__('os').environ.get('FRAME_RELEASE_INDEX','releases.json')).read_text())
  except FileNotFoundError:release={}
  h.reply(200,{k:{**{f:v[f]for f in ['name','bytes','sha256']},'download':base+'/downloads/'+k}for k,v in release.items()});return True
 match_download=re.fullmatch(re.escape(base)+r'/downloads/(windows|mac)',path)
 if h.command=='GET'and match_download:
  try:v=call('release',{'platform':match_download[1]})
  except Exception:h.reply(503,{'error':'Загрузка сборок временно недоступна'});return True
  h.send_response(302);h.send_header('Location',v['url']);h.send_header('Content-Length','0');h.send_header('Cache-Control','no-store');h.end_headers();return True
 if h.command=='GET'and path==base+'/status':
  h.reply(200,{'account':account,'connections':Mailbox(data).status(),'protocol':1});return True
 match=re.fullmatch(re.escape(base)+r'/jobs/([a-f0-9]{32})(/(cancel|close|pause|resume))?',path)
 if match:
  ident=match[1];p=root/(ident+'.request.json');binding=root/(ident+'.desktop.json')
  if h.command=='POST'and not match[2]:
   d=body();timeout=d.get('timeout',660)
   if not isinstance(timeout,int)or not 1<=timeout<=259200:raise ValueError('Invalid expiry')
   payload=validate(d.get('payload'),account);digest=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
   with gate:
    if binding.exists():
     prior=json.loads(binding.read_text())
     if prior.get('sha256')!=digest:raise ValueError('Job identity conflict')
     h.reply(200,{'id':ident,'accepted':True,'duplicate':True});return True
    if p.exists():raise ValueError('Job identity collision')
    active=0
    for b in root.glob('*.desktop.json'):
     old=json.loads(b.read_text());i=b.name.split('.')[0]
     if old.get('expires',0)>time.time()and not any((root/(i+s)).exists()for s in ['.closed.json','.cancel','.result.json']):active+=1
    if active>=2:raise ValueError('Desktop queue occupied')
    capacity(len(json.dumps(payload).encode())+1000000)
    if payload['kind']in ['generate','render','image','perceive','dubFull']:
     payload={**payload,'resultCap':__import__('secrets').token_hex(32),'returnUrl':os.environ.get('FRAME_REMOTE_ORIGIN','https://frame.example.invalid')+prefix+'/api/pc-result/'+account+'/'+ident+'/'+payload['extension']}
    expiry=time.time()+timeout
    write_private(binding,{'sha256':digest,'expires':expiry})
    write_private(p,{'id':ident,'created':time.time(),'expires':expiry,**payload})
   h.reply(202,{'id':ident,'accepted':True});return True
  if not binding.exists():h.reply(404,{'error':'Unknown desktop job'});return True
  if h.command=='POST'and match[3]in ['cancel','close','pause','resume']:
   body(1024);action=match[3]
   suffix='.cancel'if action=='cancel'else'.closed.json'if action=='close'else'.pause.json'
   write_private(root/(ident+suffix),{'at':time.time(),'paused':action=='pause'})
   h.reply(200,{'ok':True});return True
  if h.command=='GET'and not match[2]:
   try:progress=json.loads((root/(ident+'.progress.json')).read_text())
   except (OSError,ValueError):progress=None
   result=root/(ident+'.result.json')
   if result.exists():h.reply(200,{'status':'done','result':json.loads(result.read_text()),'progress':progress})
   elif(root/(ident+'.cancel')).exists():h.reply(200,{'status':'cancelled'})
   elif json.loads(binding.read_text())['expires']<time.time():h.reply(200,{'status':'expired','error':'No automatic replay'})
   else:h.reply(200,{'status':'running','progress':progress})
   return True
 if h.command=='POST'and path.startswith(base+'/objects/'):
  action=path.rsplit('/',1)[-1]
  if action not in ['init','status','complete','sign','part']:raise ValueError('Invalid object action')
  if action=='part':
   n=int(h.headers.get('Content-Length','0'))
   if not 0<n<=8*1024**2:raise ValueError('Invalid part')
   capacity(n+1000000)
   result=call('part',body=h.rfile.read(n),headers={k:h.headers.get(k,'')for k in ['X-Object-Id','X-Part-Number','X-Part-SHA256']})
  else:result=call(action,body(8192))
  h.reply(200,result);return True
 h.reply(404,{'error':'Unknown desktop operation'});return True
