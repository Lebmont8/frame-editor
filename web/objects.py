"""Account worker client; only fixed local Unix socket, no S3 credentials."""
import http.client,socket,json,subprocess,uuid,time,threading,hashlib,re
from pathlib import Path
class Conn(http.client.HTTPConnection):
 def __init__(self):super().__init__('localhost',timeout=45)
 def connect(self):self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);self.sock.settimeout(self.timeout);self.sock.connect('/run/frame-objects/broker.sock')
def call(action,d=None,body=None,headers=None):
 c=Conn()
 try:
  b=json.dumps(d or {}).encode()if body is None else body;c.request('POST','/'+action,body=b,headers={'Content-Type':'application/json','Content-Length':str(len(b)),**(headers or {})});r=c.getresponse();v=json.loads(r.read(65536))
  if r.status!=200:raise ValueError(v.get('error','Object operation failed'))
  return v
 finally:c.close()
def original_url(id):return call('sign',{'id':id})
def mapping(data):
 p=Path(data)/'object-media.json'
 try:return json.loads(p.read_text())
 except (OSError,ValueError):return {}
def save_mapping(data,d):
 from providers import write_private
 write_private(Path(data)/'object-media.json',d)
class Objects:
 def __init__(self,data,prefix,jobs,lock,capacity,context):self.data=Path(data);self.prefix=prefix;self.jobs=jobs;self.lock=lock;self.capacity=capacity;self.context=context
 def action(self,op,d):
  if op in ['init','status','complete']:return call(op,d)
  if op!='import':raise ValueError('Unknown media operation')
  id=d.get('id');info=call('status',{'id':id})
  if info['status']!='ready':raise ValueError('Дождись обратной SHA-проверки исходника')
  existing=next((j for j in self.jobs.values()if j.get('kind')=='objectProxy'and j.get('objectId')==id and j['status']=='running'),None)
  if existing:return existing
  known=next((m for m in self.context().get('media',[])if m.get('original',{}).get('objectId')==id),None)
  if known:return {'id':'existing-'+id[:8],'kind':'objectProxy','status':'done','item':known['item']}
  c=self.context();project=c['path'];ident=uuid.uuid4().hex[:12];j={'id':ident,'kind':'objectProxy','status':'running','objectId':id,'project':project.name,'started':time.time()};self.jobs[ident]=j
  def work():
   try:
    signed=original_url(id);url=signed['url'];ext=Path(info['name']).suffix.lower();is_audio=ext in ['.wav','.mp3','.flac'];is_image=ext in ['.png','.jpg','.jpeg'];target=self.data/'uploads'/('object-'+id+('.mp3'if is_audio else'.png'if is_image else'.mp4'))
    probe=subprocess.run(['ffprobe','-v','error','-show_format','-show_streams','-of','json',url],capture_output=True,text=True,timeout=90)
    if probe.returncode:raise ValueError('Не удалось прочитать метаданные исходника')
    metadata=json.loads(probe.stdout);metadata.get('format',{}).pop('filename',None);duration=float(metadata.get('format',{}).get('duration',0))
    if not is_image and not 0<duration<=7200:raise ValueError('Текущий предел проекта —2часа')
    self.capacity(int(min(500*1024**2,max(8*1024**2,duration*(10000 if is_audio else 48000)))))
    args=['ffmpeg','-v','error','-threads','1','-i',url]
    if is_audio:args+=['-vn','-ar','48000','-ac','2','-c:a','libmp3lame','-b:a','64k']
    elif is_image:args+=['-vf','scale=1920:1920:force_original_aspect_ratio=decrease','-frames:v','1']
    else:args+=['-vf','scale=640:640:force_original_aspect_ratio=decrease','-c:v','libx264','-preset','veryfast','-b:v','240k','-maxrate','300k','-bufsize','600k','-c:a','aac','-b:a','64k','-movflags','+faststart']
    args+=['-y',str(target)];r=subprocess.run(args,capture_output=True,timeout=21600)
    if r.returncode:raise ValueError('Лёгкое представление не собрано; исходник сохранён в Object Storage')
    with self.lock:
     if self.context()['path']!=project:raise ValueError('Проект переключён; исходник и подготовленный просмотр сохранены')
     all=mapping(self.data);all[str(target.resolve())]={'objectId':id,'name':info['name'],'bytes':info['bytes'],'sha256':info['sha256'],'probe':metadata};save_mapping(self.data,all)
     item=c['import_file'](target)
     from workflow import read_workflow,save_workflow
     w=read_workflow(project);w['roles']={**w.get('roles',{}),str(item):info.get('role','video')};save_workflow(project,w)
    j.update(status='done',item=item,finished=time.time())
   except Exception as e:j.update(status='error',error=str(e)[:400]if isinstance(e,ValueError)else'Object media preparation failed; source retained',finished=time.time())
  threading.Thread(target=work,daemon=True).start();return j

def publish_local(path,role='audio',timeout=1800):
 """Owned derived output only: PUT->reverse SHA->durable reader; caller controls cache eviction."""
 p=Path(path);h=hashlib.sha256()
 with p.open('rb')as f:
  while b:=f.read(1024**2):h.update(b)
 digest=h.hexdigest();o=call('init',{'name':p.name,'bytes':p.stat().st_size,'expectedSHA256':digest,'role':role})
 if o['status']!='ready':
  with p.open('rb')as stream:
   for n in range(1,(p.stat().st_size+8*1024**2-1)//(8*1024**2)+1):
    part=stream.read(8*1024**2);call('part',body=part,headers={'X-Object-Id':o['id'],'X-Part-Number':str(n),'X-Part-SHA256':hashlib.sha256(part).hexdigest()})
  o=call('complete',{'id':o['id']});end=time.monotonic()+timeout
  while o['status']=='verifying'and time.monotonic()<end:time.sleep(1);o=call('status',{'id':o['id']})
 if o['status']!='ready'or o['sha256']!=digest:raise ValueError('Derived audio object not verified; local output retained')
 return o
