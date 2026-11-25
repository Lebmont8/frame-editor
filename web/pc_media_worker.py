"""Frame PC media adapter. Fixed installed models, one GPU operation, bounded signed return."""
import sys,json,base64,zlib,re,time,os,hashlib,urllib.request,urllib.parse,msvcrt
from pathlib import Path
ROOT=Path(r'C:\AI\AsyaMedia');sys.path.insert(0,str(ROOT))
def emit(v):print('FRAME_RESULT:'+base64.b64encode(zlib.compress(json.dumps(v).encode())).decode(),flush=True)
def main():
 p=Path(sys.argv[1]).resolve()
 if not p.is_relative_to(Path.home()/'.openclaw'/'tmp')or p.stat().st_size>8_000_000:raise ValueError('Invalid transfer')
 job=json.loads(p.read_text(encoding='utf-8'))
 if job.get('kind')!='generate'or not re.fullmatch('[a-f0-9]{32}',job.get('id','')):raise ValueError('Invalid job')
 ident=job['id'];op=job.get('operation');ext={'speech':'wav','image':'png','video':'mp4'}.get(op)
 if not ext:raise ValueError('Invalid operation')
 expected=os.environ.get('FRAME_REMOTE_ORIGIN','https://frame.example.invalid')+'/youtube-hub/frame/api/pc-result/'+job.get('account','')+'/'+ident+'/'+ext
 if job.get('returnUrl')!=expected or job.get('account')not in ['cat','code']or not re.fullmatch('[a-f0-9]{64}',job.get('resultCap','')):raise ValueError('Invalid return capability')
 seed=int(job['seed']);frames=int(job.get('frames',33))
 if not 0<=seed<2**31 or frames not in [17,33,49]:raise ValueError('Invalid settings')
 if __import__('shutil').disk_usage(ROOT).free<500_000_000:raise ValueError('PC free space below bounded 500MB operation peak')
 lock=(ROOT/'Frame'/'gpu.lock').open('a+b');lock.seek(0)
 try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
 except OSError:raise ValueError('Another Frame GPU job is active; no automatic retry')
 try:
  import media_control as c
  started=time.time();pid=None
  if op=='speech':
   text=str(job.get('prompt','')).strip()
   if not 1<=len(text)<=1800:raise ValueError('Speech text: 1..1800 characters')
   c.unload('video');c.start('speech');voice=None
   if job.get('voice'):
    raw=base64.b64decode(job['voice'],validate=True)
    if len(raw)>2_500_000:raise ValueError('Voice reference too large')
    voice='frame_'+ident;ref=ROOT/'VoxCPM2'/'voices'/(voice+'.wav')
    with ref.open('xb')as out:out.write(raw)
   info=c.api('speech','/generate',{'text':text,'voice':voice,'seed':seed,'steps':10},timeout=max(1,490-(time.time()-started)))
   output=Path(info['path']).resolve()
   if not output.is_relative_to(ROOT/'output'/'audio'):raise ValueError('Unexpected speech result')
   model='VoxCPM2';dimensions={}
  else:
   raw=base64.b64decode(job.get('reference',''),validate=True)
   if not 100<len(raw)<=900000:raise ValueError('Image reference required')
   c.unload('speech');c.start('video')
   queue=c.api('video','/queue')
   if queue.get('queue_running')or queue.get('queue_pending'):raise ValueError('ComfyUI queue is occupied; no job submitted')
   ref=c.COMFY/'input'/('frame_'+ident+'.png')
   with ref.open('xb')as out:out.write(raw)
   length=17 if op=='image'else frames
   graph=c.graph(ref.name,str(job.get('prompt',''))[:2000],'flicker, morphing, distorted anatomy, text, watermark, extra limbs',512,288,length,seed,True)
   if op=='image':
    graph.pop('16',None);graph['18']={'class_type':'ImageFromBatch','inputs':{'image':['15',0],'batch_index':length-1,'length':1}}
    graph['17']={'class_type':'SaveImage','inputs':{'images':['18',0],'filename_prefix':'Frame/'+ident}}
   else:graph['17']['inputs']['filename_prefix']='Frame/'+ident
   request=c.api('video','/prompt',{'prompt':graph,'client_id':'frame-'+ident});pid=request.get('prompt_id')
   if not pid:raise ValueError('ComfyUI did not accept the graph')
   deadline=time.monotonic()+max(1,490-(time.time()-started))
   while time.monotonic()<deadline:
    history=c.api('video','/history/'+pid).get(pid,{})
    if history.get('status',{}).get('status_str')=='error':raise ValueError('ComfyUI generation failed; original job retained in history')
    outputs=history.get('outputs',{})
    found=[]
    for row in outputs.values():
     for value in row.values():
      if isinstance(value,list):
       found.extend(x for x in value if isinstance(x,dict)and str(x.get('filename','')).lower().endswith('.'+ext))
    if found:break
    time.sleep(3)
   else:raise ValueError('Generation still running in ComfyUI; no automatic resubmission. Check original history before retry.')
   item=found[-1];output=(c.COMFY/'output'/item.get('subfolder','')/item['filename']).resolve()
   if not output.is_relative_to(c.COMFY/'output'):raise ValueError('Unexpected ComfyUI output')
   model='Wan2.2-I2V-A14B GGUF Q4 + LightX2V';dimensions={'width':512,'height':288,'frames':length,'mode':'last generated frame from I2V'if op=='image'else'image-to-video','fps':16}
  size=output.stat().st_size
  if not 0<size<=32*1024**2:raise ValueError('Result exceeds 32MiB transfer cap')
  digest=hashlib.sha256(output.read_bytes()).hexdigest()
  req=urllib.request.Request(expected,data=output.read_bytes(),headers={'User-Agent':'Frame-PC-Worker/1.0','Content-Type':'application/octet-stream','X-Frame-Result-Cap':job['resultCap'],'X-Frame-SHA256':digest},method='POST')
  with urllib.request.urlopen(req,timeout=90)as response:receipt=json.load(response)
  if receipt.get('sha256')!=digest:raise ValueError('Return checksum not confirmed')
  return {'ok':True,'output':{**receipt,**dimensions,'model':model,'seed':seed,'elapsed':round(time.time()-started,2),'bytes':size,'operation':op}}
 finally:
  try:
   if 'c'in locals():
    if 'pid'in locals()and pid:
     queue=c.api('video','/queue')
     if any(row[1]==pid for row in queue.get('queue_running',[])):c.api('video','/interrupt',{})
     if any(row[1]==pid for row in queue.get('queue_pending',[])):c.api('video','/queue',{'delete':[pid]})
    c.unload('speech'if op=='speech'else'video')
  except Exception:pass
  lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1);lock.close()
try:emit(main())
except Exception as e:emit({'ok':False,'error':str(e)[:350]});sys.exit(1)

