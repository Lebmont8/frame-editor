"""Private durable bridge: project jobs remain on Project81; OpenClaw receives data only."""
import base64,json,os,time,uuid,re,threading,zlib,subprocess
from pathlib import Path
from providers import write_private,ProviderError
def validate_output(value,schema,depth=0):
 if depth>12:raise ProviderError('Слишком глубокий ответ Аси')
 t=schema.get('type')
 if t=='object':
  if not isinstance(value,dict)or set(value)!=set(schema.get('required',[])):raise ProviderError('Ответ Аси не соответствует полям задания')
  for k,v in value.items():validate_output(v,schema['properties'][k],depth+1)
 elif t=='array':
  if not isinstance(value,list)or len(value)>schema.get('maxItems',10000):raise ProviderError('Некорректный список в ответе Аси')
  for v in value:validate_output(v,schema['items'],depth+1)
 elif t=='string':
  if not isinstance(value,str)or len(value)>80000:raise ProviderError('Некорректный текст ответа Аси')
 elif t in ['number','integer']:
  import math
  if isinstance(value,bool)or not isinstance(value,(int,float))or not math.isfinite(value)or t=='integer'and not isinstance(value,int):raise ProviderError('Некорректное число в ответе Аси')
 elif t=='boolean'and not isinstance(value,bool):raise ProviderError('Некорректный флаг ответа')
 if 'enum'in schema and value not in schema['enum']:raise ProviderError('Неизвестное значение ответа Аси')
class Mailbox:
 def __init__(self,data):
  self.root=Path(data)/'bridge';self.root.mkdir(exist_ok=True,mode=0o700)
 def request(self,payload,timeout=660,on_created=None):
  if os.environ.get('FRAME_NATIVE_PORT'):
   from remote import remote_request
   return remote_request(self,payload,timeout,on_created)
  ident=uuid.uuid4().hex;path=self.root/(ident+'.request.json');dest=self.root/(ident+'.result.json')
  if payload.get('kind')in ['generate','render','image','perceive','dubFull']:
   payload={**payload,'resultCap':uuid.uuid4().hex+uuid.uuid4().hex,'returnUrl':os.environ.get('FRAME_REMOTE_ORIGIN','https://frame.example.invalid')+'/youtube-hub/frame/api/pc-result/'+payload['account']+'/'+ident+'/'+payload['extension']}
  write_private(path,{'id':ident,'created':time.time(),'expires':time.time()+timeout,**payload})
  if on_created:on_created(ident)
  try:
   end=time.monotonic()+timeout
   while time.monotonic()<end:
    if (self.root/(ident+'.cancel')).exists():raise ProviderError('Задание отменено. Результат не применяется.')
    if dest.exists():
     result=json.loads(dest.read_text())
     if not result.get('ok'):raise ProviderError(str(result.get('error','Сбой обработчика'))[:500])
     return result
    time.sleep(.7)
   raise ProviderError('Нет ответа от Аси или ПК. Автоматического повторного запуска нет.')
  finally:
   write_private(self.root/(ident+'.closed.json'),{'closed':time.time()})
   write_private(path,{'id':ident,'closed':True})
 def cancel_all(self):
  for p in self.root.glob('*.request.json'):
   ident=p.name.split('.')[0]
   if not (self.root/(ident+'.closed.json')).exists():write_private(self.root/(ident+'.cancel'),{'at':time.time()})
 def status(self):
  if os.environ.get('FRAME_NATIVE_PORT'):
   try:
    from remote import request
    return request('/api/desktop/status')['connections']
   except Exception:return {'asya':False,'pc':False,'mode':'desktop-disconnected','textModel':'gpt-6.1-sol'}
  try:d=json.loads((self.root/'heartbeat.json').read_text())
  except (OSError,ValueError):d={}
  return {'asya':time.time()-d.get('time',0)<45,'pc':bool(d.get('pc')) and time.time()-d.get('time',0)<45,'pcOperations':['transcribe','speech','image','video','render','upscale','perceive','dubFull'],'mode':'asya-pc','textModel':'gpt-6.1-sol','imageModel':'Asya / OpenClaw Images','openai':False,'elevenlabs':False}
class AsyaProvider:
 def __init__(self,data):self.mailbox=Mailbox(data);self.calls=0;self.keys={}
 def structured(self,prompt,schema,images=None,research=False):
  payload={'kind':'structured','prompt':prompt,'schema':schema,'research':research,'images':[]}
  for label,p in images or []:
   b=Path(p).read_bytes()
   if len(b)>700000:raise ProviderError('Слишком большой кадр для Аси')
   payload['images'].append({'label':label,'content':base64.b64encode(b).decode()})
  if len(json.dumps(payload).encode())>7000000:raise ProviderError('Слишком много данных для одного задания')
  self.calls+=1;r=self.mailbox.request(payload,on_created=self.created)
  validate_output(r['output'],schema)
  return r['output'],r['meta']
 def created(self,ident):
  if getattr(self,'cancelled',lambda:False)():write_private(self.mailbox.root/(ident+'.cancel'),{'at':time.time()})
 def transcribe(self,path):
  probe=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','json',str(path)],capture_output=True,text=True,encoding='utf-8',timeout=30)
  duration=float(json.loads(probe.stdout)['format']['duration']);combined={'segments':[],'words':[],'text':''}
  if not 0<duration<=7200:raise ValueError('ASR range must be<=2h')
  for start in range(0,__import__('math').ceil(duration),240):
   if getattr(self,'cancelled',lambda:False)():raise ProviderError('Расшифровка отменена')
   self.calls+=1;left=max(0,start-2);right=min(duration,start+242)
   r=subprocess.run(['ffmpeg','-v','error','-threads','1','-ss',str(left),'-i',str(path),'-t',str(right-left),'-ac','1','-ar','16000','-c:a','pcm_s16le','-f','wav','-'],capture_output=True,timeout=180)
   if r.returncode or len(r.stdout)>8000000:raise ProviderError('Не удалось подготовить локальный PCM-фрагмент')
   audio=base64.b64encode(zlib.compress(r.stdout,6)).decode()
   if len(audio)>14000000:raise ProviderError('PCM-пакет превышает транспортный лимит')
   out=self.mailbox.request({'kind':'transcribe','audio':audio,'encoding':'wav-zlib'},timeout=1200,on_created=self.created)['output']
   rows=out.get('words') or out.get('segments',[])
   kept=[]
   for row in rows:
    a=float(row['start'])+left;b=min(duration,float(row['end'])+left)
    if start<=(a+b)/2<min(duration+.001,start+240):kept.append({**row,'start':max(0,a),'end':b})
   combined['words'].extend(kept if out.get('words') else [])
   if kept:
    group=[]
    for row in kept:
     group.append(row)
     if row['end']-group[0]['start']>=8 or str(row.get('text',row.get('word',''))).rstrip().endswith(('.', '?', '!')):
      combined['segments'].append({'start':group[0]['start'],'end':group[-1]['end'],'text':' '.join(str(r.get('text',r.get('word','')))for r in group)});group=[]
    if group:combined['segments'].append({'start':group[0]['start'],'end':group[-1]['end'],'text':' '.join(str(r.get('text',r.get('word','')))for r in group)})
   combined['text']+=' '+' '.join(str(r.get('text',r.get('word','')))for r in kept);combined['language_code']=out.get('language_code',out.get('language','auto'))
  return combined
if __name__=='__main__':
 import argparse,sys
 a=argparse.ArgumentParser();a.add_argument('--data',required=True);a.add_argument('action',choices=['claim','finish','heartbeat']);v=a.parse_args();m=Mailbox(v.data)
 if v.action=='heartbeat':
  incoming=json.load(sys.stdin);write_private(m.root/'heartbeat.json',{'time':time.time(),'pc':incoming.get('pc')is True});print('{}')
 elif v.action=='claim':
  found=None
  for p in sorted(m.root.glob('*.request.json'),key=lambda p:p.stat().st_mtime):
   ident=p.name.split('.')[0]
   if any((m.root/(ident+s)).exists()for s in ['.claim.json','.closed.json','.cancel']):continue
   d=json.loads(p.read_text())
   if d.get('expires',0)<time.time():continue
   if d.get('kind')not in ['structured','transcribe','generate','render','pcOpen','image','perceive','dubFull']:continue
   write_private(m.root/(ident+'.claim.json'),{'at':time.time()});found=d;break
  print(json.dumps(found))
 elif v.action=='finish':
  d=json.load(sys.stdin);ident=d.pop('id','')
  if not re.fullmatch('[a-f0-9]{32}',ident):raise ValueError('invalid id')
  p=m.root/(ident+'.request.json')
  if not p.exists():raise ValueError('unknown job')
  request=json.loads(p.read_text())
  if request.get('expires',0)<time.time()or any((m.root/(ident+s)).exists()for s in ['.closed.json','.cancel']):print('{"ignored":true}')
  else:write_private(m.root/(ident+'.result.json'),d);print('{"saved":true}')

