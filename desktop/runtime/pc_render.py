"""Project81 PC-render orchestration. Fixed-file capabilities, immutable native snapshot."""
import json,hashlib,uuid,time,threading,re,os,subprocess
from pathlib import Path
from urllib.parse import quote
from bridge import Mailbox
from providers import write_private,ProviderError
def file_sha(p):
 h=hashlib.sha256()
 with p.open('rb')as f:
  while b:=f.read(1024**2):h.update(b)
 return h.hexdigest()
T=254016000000
class PCRender:
 def __init__(self,data,prefix,jobs,lock,capacity):
  self.data=Path(data);self.prefix=prefix;self.jobs=jobs;self.lock=lock;self.capacity=capacity;self.store=self.data/'bridge'/'render-jobs';self.store.mkdir(parents=True,exist_ok=True)
  for p in self.store.glob('*.json'):
   try:j=json.loads(p.read_text())
   except (ValueError,OSError):continue
   if j.get('status')=='running':
    if re.fullmatch('[a-f0-9]{32}',j.get('remoteId','')):write_private(self.data/'bridge'/(j['remoteId']+'.cancel'),{'cancelled':time.time()})
    j.update(status='error',error='Рендер прерван перезапуском. Автоповтора нет. Можно проверить прежний файл на ПК.',finished=time.time());write_private(p,j)
   self.jobs[j['id']]=j
 def persist(self,j):write_private(self.store/(j['id']+'.json'),j)
 def enrich(self):
  for j in list(self.jobs.values()):
   if j.get('kind')not in ['pcExport','pcQualityPreview']or j['status']!='running':continue
   try:p=json.loads((self.data/'bridge'/(j['remoteId']+'.progress.json')).read_text())
   except (KeyError,ValueError,OSError):continue
   j['pcProgress']=p
 def control(self,ident,action):
  j=self.jobs.get(str(ident))
  if not j or j.get('kind')not in ['pcExport','pcQualityPreview']:raise ValueError('Рендер не найден')
  remote=j.get('remoteId','')
  if action in ['cancel','pause','resume']:
   if j['status']!='running':raise ValueError('Рендер уже завершён')
   if action=='cancel':
    j['cancelRequested']=True
    if remote:write_private(self.data/'bridge'/(remote+'.cancel'),{'cancelled':time.time()})
   else:
    paused=action=='pause';j['pauseRequested']=paused
    if remote:write_private(self.data/'bridge'/(remote+'.pause.json'),{'paused':paused})
   self.persist(j);return
  if action=='open':
   pcid=j.get('full',{}).get('pcJobId')
   if not re.fullmatch('[a-f0-9]{32}',str(pcid)):raise ValueError('Нет готового полного файла на ПК')
   Mailbox(self.data).request({'kind':'pcOpen','pcJobId':pcid,'account':self.data.name},timeout=45);return
  raise ValueError('Неизвестное действие рендера')
 def start(self,path,seq,profile,revision,quality_preview=False,seconds=0,resume=None):
  with self.lock:
   if any(j['status']=='running'and j.get('kind')in ['pcExport','pcQualityPreview']for j in self.jobs.values()):raise ValueError('Один PC-рендер уже в работе')
   if not Mailbox(self.data).status()['pc']:raise ValueError('Нет свежего соединения с ПК. Серверный рендер можно выбрать явно.')
   duration=seq.get('duration',0)/T
   if not 0<duration<=7200:raise ValueError('Для рендера нужен монтаж длительностью до2ч')
   self.capacity(34*1024**2+1000000)
   native_snapshot=path.read_text();seq=json.loads(json.dumps(seq));profile=json.loads(json.dumps(profile));ident=uuid.uuid4().hex[:12];j={'id':ident,'status':'running','kind':'pcQualityPreview'if quality_preview else'pcExport','project':path.name,'revision':revision,'started':time.time(),'device':'PC'}
   self.jobs[ident]=j;self.persist(j)
   def run():
    try:
     settings=seq['settings'];fps=settings['frame_rate']['num']/settings['frame_rate']['den']
     start=max(0,min(float(seconds),max(0,duration-1/fps)))if quality_preview else 0
     start=round(start*fps)/fps;end=min(duration,start+2)if quality_preview else duration
     payload={'kind':'render','account':self.data.name,'extension':'mp4','profile':profile or {},'sequenceSettings':settings,'start':start,'end':end,'qualityPreview':bool(quality_preview),'files':{},'projectName':path.stem}
     if resume:
      old=self.jobs.get(str(resume),{})
      original=old.get('full',{}).get('pcJobId')or old.get('remoteId')
      if not old or old.get('project')!=path.name or not re.fullmatch('[a-f0-9]{32}',str(original)):raise ValueError('Нет прежнего PC-рендера этого проекта')
      payload.update(mode='redeliver',sourceJobId=original)
     else:
      native=json.loads(native_snapshot);files={}
      from objects import mapping
      originals=mapping(self.data)
      def walk(node):
       if isinstance(node,dict):
        item=node.get('File')
        if isinstance(item,dict)and isinstance(item.get('path'),str):
         p=Path(item['path']).resolve()
         if not p.is_file():raise ValueError('Проект содержит недоступный/чужой материал')
         if p.stat().st_size>10*1024**3 and str(p)not in originals:raise ValueError('Один материал превышает текущий64МиБ лимит')
         if str(p)not in files:
          key=uuid.uuid4().hex;files[str(p)]=key;payload['files'][key]={'desktopPath':str(p),'bytes':p.stat().st_size,'sha256':originals[str(p)]['sha256'] if str(p)in originals else file_sha(p),'suffix':p.suffix.lower()}
          if str(p)in originals:
           v=originals[str(p)];payload['files'][key].update(objectId=v['objectId'],bytes=v['bytes'],sha256=v['sha256'],suffix=Path(v['name']).suffix.lower(),processing=v.get('processing',{}))
         item['path']='FRAME_INPUT:'+files[str(p)]
        text=node.get('Text')
        if isinstance(text,str)and text.endswith('.cube')and Path(text).is_absolute():
         p=Path(text).resolve()
         if not p.is_relative_to(self.data)or not p.is_file()or p.stat().st_size>1000000:raise ValueError('Чужой/недоступный LUT')
         if str(p)not in files:
          key=uuid.uuid4().hex;files[str(p)]=key;payload['files'][key]={'desktopPath':str(p),'bytes':p.stat().st_size,'sha256':file_sha(p),'suffix':'.cube'}
         node['Text']='FRAME_LUT:'+files[str(p)]
        for value in node.values():walk(value)
       elif isinstance(node,list):
        for value in node:walk(value)
      walk(native)
      if len(payload['files'])>100 or sum(f['bytes']for f in payload['files'].values())>100*1024**3:raise ValueError('Слишком большой набор материалов для локального рендера')
      payload['project']=native
     def created(remote):
      j['remoteId']=remote
      if j.get('cancelRequested'):write_private(self.data/'bridge'/(remote+'.cancel'),{'cancelled':time.time()})
      if j.get('pauseRequested'):write_private(self.data/'bridge'/(remote+'.pause.json'),{'paused':True})
      self.persist(j)
     receipt=Mailbox(self.data).request(payload,timeout=259200,on_created=created)['output']
     name=receipt.get('name','')
     if not re.fullmatch(r'local-[a-f0-9]{32}\.mp4',name):raise ValueError('Некорректная квитанция PC-рендера')
     proxy=self.data/'renders'/name
     if not proxy.is_file()or hashlib.sha256(proxy.read_bytes()).hexdigest()!=receipt.get('sha256'):raise ValueError('Превью не прошло SHA-проверку')
     r=subprocess.run(['ffmpeg','-v','error','-threads','1','-i',str(proxy),'-f','null','-'],capture_output=True,timeout=180)
     if r.returncode or r.stderr:raise ValueError('Превью не декодируется полностью')
     full={k:receipt.get(k)for k in ['pcJobId','fullPath','fullBytes','fullSHA256','width','height','fps','frames','codec','aiModel','elapsed','method','previewDuration','previewIsExcerpt']}
     if not re.fullmatch('[a-f0-9]{32}',str(full['pcJobId']))or not re.fullmatch('[a-f0-9]{64}',str(full['fullSHA256'])):raise ValueError('Полный файл не подтверждён на ПК')
     j.update(status='done',finished=time.time(),url=self.prefix+'/files/renders/'+name,bytes=proxy.stat().st_size,full=full)
    except Exception as e:
     j.update(status='error',error=str(e)[:400]if isinstance(e,(ValueError,ProviderError))else'Локальный рендер не завершён; автоповтора нет.',finished=time.time())
    self.persist(j)
   threading.Thread(target=run,daemon=True).start();return j

def pc_input(handler,data,prefix):
 match=re.fullmatch(re.escape(prefix)+r'/api/pc-input/(cat|code)/([a-f0-9]{32})/([a-f0-9]{32})',handler.path)
 if not match:return False
 account,ident,key=match.groups()
 try:
  if Path(data).name!=account:raise ValueError('Wrong account')
  root=Path(data)/'bridge';job=json.loads((root/(ident+'.request.json')).read_text())
  import hmac
  cap=handler.headers.get('X-Frame-Result-Cap','')
  if job.get('kind')!='render'or job.get('expires',0)<time.time()or len(cap)!=64 or not hmac.compare_digest(cap,job.get('resultCap',''))or any((root/(ident+s)).exists()for s in ['.closed.json','.cancel']):raise ValueError('Invalid input capability')
  info=job.get('files',{}).get(key)
  if not info:raise ValueError('Unknown input')
  if info.get('objectId'):
   from objects import original_url
   import urllib.request
   signed=original_url(info['objectId'])
   if signed['sha256']!=info['sha256']or signed['bytes']!=info['bytes']:raise ValueError('Original object changed')
   with urllib.request.urlopen(signed['url'],timeout=90)as r:
    handler.headers_out(200,'application/octet-stream',signed['bytes']);handler.end_headers()
    while b:=r.read(65536):handler.wfile.write(b)
   return True
  p=(Path(data)/info['relative']).resolve()
  if not p.is_relative_to(Path(data))or not p.is_file()or p.stat().st_size!=info['bytes']:raise ValueError('Input changed')
  handler.send_file(p)
 except Exception as e:handler.reply(403,{'error':str(e)[:100]})
 return True

