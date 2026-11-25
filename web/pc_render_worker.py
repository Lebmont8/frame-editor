"""Fixed native FilmCraft/Real-ESRGAN PC renderer. No downloaded code or arbitrary commands."""
import sys,os,json,time,re,hashlib,base64,zlib,subprocess,threading,queue,urllib.request,msvcrt,shutil,runpy,types,math
from pathlib import Path
R=Path(r'C:\AI\AsyaMedia\Frame');J=R/'render-jobs';E=R/'exports';J.mkdir(exist_ok=True);E.mkdir(exist_ok=True)
FC=R/'tools/filmcraft-0.20.1/filmcraft-cli.exe';ES=R/'tools/realesrgan/realesrgan-ncnn-vulkan.exe'
FF=Path(r'C:\AI\AsyaMedia\VoxCPM2\.venv\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe')
BASE='https://frame.example.invalid/youtube-hub/frame/api/'
CHILDREN=[];JOB={};START=time.time();LAST=0;PHASE='starting';CURRENT=0;TOTAL=0;PAUSED=False
FLAGS=getattr(subprocess,'CREATE_NO_WINDOW',0)
def atomic(p,v):
 t=p.with_suffix('.new');t.write_text(json.dumps(v,ensure_ascii=True));os.replace(t,p)
def emit(v):print('FRAME_RESULT:'+base64.b64encode(zlib.compress(json.dumps(v).encode())).decode(),flush=True)
def sha(p):
 h=hashlib.sha256()
 with p.open('rb')as f:
  while b:=f.read(1048576):h.update(b)
 return h.hexdigest()
def req(url,data=None,extra=None):
 if not url.startswith(BASE):raise ValueError('Invalid fixed return route')
 h={'User-Agent':'Frame-PC-Worker/1.0','X-Frame-Result-Cap':JOB['resultCap'],**(extra or {})}
 return urllib.request.urlopen(urllib.request.Request(url,data=data,headers=h),timeout=90)
def tick(phase=None,frame=None,force=False):
 global LAST,PHASE,CURRENT,PAUSED
 if phase:PHASE=phase
 if frame is not None:CURRENT=frame
 if not force and time.time()-LAST<3:return
 while True:
  elapsed=time.time()-START;speed=CURRENT/max(.01,elapsed)
  with req(JOB['returnUrl'],json.dumps({'phase':PHASE,'frame':CURRENT,'frames':TOTAL,'elapsed':round(elapsed,2),'fps':round(speed,2),'eta':round((TOTAL-CURRENT)/speed,1)if speed else 0,'paused':PAUSED}).encode(),{'X-Frame-Progress':'1','Content-Type':'application/json'})as r:paused=json.load(r).get('paused')is True
  LAST=time.time();PAUSED=paused
  if not paused:break
  time.sleep(2)
def launch(args,**kwargs):
 p=subprocess.Popen([str(x)for x in args],creationflags=FLAGS,**kwargs);CHILDREN.append(p);return p
def run(args,limit=900,strict=False):
 p=launch(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE);result=[]
 def collect():result.append(p.communicate())
 t=threading.Thread(target=collect,daemon=True);t.start();end=time.monotonic()+limit
 while t.is_alive():
  tick();t.join(.3)
  if time.monotonic()>end:raise ValueError('PC phase timeout; no automatic retry')
 out,err=result[0]
 if p.returncode or(strict and err.strip()):raise ValueError(('Native renderer: '+err.decode('utf-8','replace')[-500:]+out.decode('utf-8','replace')[-400:])[:900])
 return out
class Engine:
 def __init__(self,path):
  self.p=launch([FC,'--project',path,'mcp'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',bufsize=1,env={**os.environ,'RAYON_NUM_THREADS':'2','FILMCRAFT_DATA_DIR':str(R/'native-config')});self.i=0;self.q=queue.Queue()
  def reader():
   for l in self.p.stdout:
    try:self.q.put(json.loads(l))
    except ValueError:pass
   self.q.put({'_eof':True})
  threading.Thread(target=reader,daemon=True).start();self.rpc('initialize',{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'Frame-PC','version':'1'}});self.p.stdin.write('{"jsonrpc":"2.0","method":"notifications/initialized"}\n');self.p.stdin.flush()
 def rpc(self,method,params):
  self.i+=1;self.p.stdin.write(json.dumps({'jsonrpc':'2.0','id':self.i,'method':method,'params':params})+'\n');self.p.stdin.flush();end=time.monotonic()+600
  while time.monotonic()<end:
   try:r=self.q.get(timeout=.5)
   except queue.Empty:tick();continue
   if r.get('_eof'):raise ValueError('FilmCraft stopped')
   if r.get('id')!=self.i:continue
   if 'error'in r:raise ValueError(str(r['error'])[:400])
   return r['result']
  raise ValueError('FilmCraft frame timed out')
 def tool(self,n,args):
  r=self.rpc('tools/call',{'name':n,'arguments':args})
  if r.get('isError'):raise ValueError(str(r)[:500])
  return r
 def close(self):
  self.p.terminate();self.p.wait(10)
def capacity(peak):
 # The original owner cap is cumulative usage from the stored baseline, not model weight size.
 volume=json.loads(subprocess.check_output(['powershell.exe','-NoProfile','-Command','Get-Volume -DriveLetter C | Select-Object UniqueId | ConvertTo-Json'],text=True))
 if '990e8693-130e-4818-8db5-548c994ce704'not in volume['UniqueId']:raise ValueError('PC volume identity changed')
 cap=35_000_000_000
 cfg=R/'storage-budget.json'
 if cfg.exists():
  v=json.loads(cfg.read_text());cap=min(45_000_000_000,int(v.get('limitBytes',cap)))
 if cap not in [35_000_000_000,45_000_000_000]:raise ValueError('Invalid storage limit')
 def statvfs(_):
  d=shutil.disk_usage('C:/');return types.SimpleNamespace(f_bavail=d.free,f_frsize=1,f_blocks=d.total,f_favail=d.free//4096)
 os.statvfs=statvfs
 gate=runpy.run_path(r'C:\AI\AsyaMedia\jobs\yue2-pilot-21161\storage-capacity-gate.py')['evaluate']
 r=gate({'reserveBytes':78_228_480_000-cap,'reserveFraction':0,'writes':[{'destination':str(J),'bytes':int(peak),'files':120}]})
 if not r.get('ok',r.get('pass',False)):
  # evaluate uses decision in existing canonical gate versions.
  if r.get('decision')not in ['PASS','pass']:raise ValueError('PC disk budget: required '+str(int(peak))+' bytes; standing limit '+str(cap//10**9)+' GB. No owner files removed.')
 return r
def upload(proxy,meta):
 size=proxy.stat().st_size
 if not 0<size<=32*1024**2:raise ValueError('Preview exceeds signed 32MiB cap; full file stays on PC')
 digest=sha(proxy)
 with req(JOB['returnUrl'],proxy.read_bytes(),{'Content-Type':'application/octet-stream','X-Frame-SHA256':digest})as r:receipt=json.load(r)
 if receipt.get('sha256')!=digest:raise ValueError('Preview checksum not confirmed')
 return {'ok':True,'output':{**receipt,**meta,'previewBytes':size}}
def work(job):
 global JOB,TOTAL,START
 JOB=job;START=time.time();ident=job['id'];folder=J/ident;folder.mkdir(exist_ok=True)
 if job.get('mode')=='redeliver':
  original=str(job.get('sourceJobId',''))
  if not re.fullmatch('[a-f0-9]{32}',original):raise ValueError('Invalid recovery job')
  old=json.loads((J/original/'ready.json').read_text())
  if old.get('account')!=job['account']:raise ValueError('Wrong recovery account')
  full=E/(original+'.mp4');proxy=J/original/'preview.mp4'
  if not full.exists()or sha(full)!=old['meta']['fullSHA256']:raise ValueError('The original full file is unavailable or changed')
  return upload(proxy,old['meta'])
 p=job.get('profile',{});s=job['sequenceSettings'];w=int(s['width']);h=int(s['height']);num=int(s['frame_rate']['num']);den=int(s['frame_rate']['den']);fps=num/den
 if not 16<=w<=4096 or not 16<=h<=4096 or not 1<=fps<=120:raise ValueError('Unsupported native dimensions/rate')
 start=float(job['start']);end=float(job['end']);duration=end-start;TOTAL=round(duration*fps)
 if not 0<duration<=7200 or TOTAL<1:raise ValueError('Invalid render range')
 side=int(p.get('maxSide',0));ai=p.get('aiUpscale')is True;codec=p.get('codec','h264');sharp=float(p.get('sharpness',0));noise=p.get('denoise')is True
 if side not in [0,2048,2560,3840]or codec not in ['h264','hevc']or not 0<=sharp<=.6:raise ValueError('Invalid export profile')
 if ai and not side:side=min(3840,max(w,h)*2)
 scale=side/max(w,h)if side else 1;ow=max(2,round(w*scale/2)*2);oh=max(2,round(h*scale/2)*2)
 files=job.get('files',{});inputbytes=sum(int(x['bytes'])for x in files.values())
 # One/two frame PNGs, audio, inputs, bounded encoder output and compact preview. No frame directory.
 peak=inputbytes+duration*(16_000_000/8+192000)+w*h*(70 if ai else 10)+ow*oh*4+min(32*1024**2,duration*180000)+2_000_000
 capacity(peak);tick('download',force=True)
 for key,info in files.items():
  if not re.fullmatch('[a-f0-9]{32}',key)or info['suffix']not in ['.mp4','.mov','.mkv','.webm','.wav','.mp3','.flac','.png','.jpg','.jpeg','.cube']:raise ValueError('Invalid native input')
  dest=folder/(key+info['suffix']);url=BASE+'pc-input/'+job['account']+'/'+ident+'/'+key
  hasher=hashlib.sha256();count=0
  with req(url)as r,dest.open('xb')as f:
   while b:=r.read(65536):
    count+=len(b)
    if count>int(info['bytes']):raise ValueError('Native input too large')
    f.write(b);hasher.update(b);tick()
  if count!=info['bytes']or hasher.hexdigest()!=info['sha256']:raise ValueError('Native input checksum mismatch')
 native=job['project']
 def walk(x):
  if isinstance(x,dict):
   v=x.get('File')
   if isinstance(v,dict)and isinstance(v.get('path'),str):
    key=v['path'].removeprefix('FRAME_INPUT:')
    if key not in files:raise ValueError('Non-transfer native file path')
    v['path']=str(folder/(key+files[key]['suffix']))
   if isinstance(x.get('Text'),str)and x['Text'].startswith('FRAME_LUT:'):
    key=x['Text'].removeprefix('FRAME_LUT:')
    if key not in files or files[key]['suffix']!='.cube':raise ValueError('Invalid look transfer')
    x['Text']=str(folder/(key+'.cube'))
   for v in x.values():walk(v)
  elif isinstance(x,list):
   for v in x:walk(v)
 walk(native);project=folder/'render.fcproj';project.write_text(json.dumps(native),encoding='utf-8');full=E/(ident+'.mp4')
 # Native relink refreshes codecs/identity. Convert source-pixel motion coordinates to
 # preserve framing from editing proxies; timeline positions/times remain unchanged.
 replacements={}
 for itemid,item in native.get('project',{}).get('items',{}).items():
  media=item.get('kind',{}).get('Media')
  if not media:continue
  name=Path(media.get('media',{}).get('File',{}).get('path','')).name
  key=name.split('.')[0]
  if key not in files or not files[key].get('objectId'):continue
  original=folder/(key+files[key]['suffix']);old=media.get('info',{}).get('video')
  processing=files[key].get('processing',{})
  if processing.get('audioTempo'):
   corrected=folder/(key+'-corrected.flac');rate=float(processing['audioTempo'])
   if not .995<=rate<=1.005:raise ValueError('Invalid clock correction')
   capacity(corrected.stat().st_size if corrected.exists()else duration*100000+2000000)
   run([FF,'-v','error','-threads','2','-i',original,'-vn','-af','atempo='+str(rate),'-c:a','flac','-y',corrected],21600);original=corrected
  run([FC,'--project',project,'--save','exec','media.relink',json.dumps({'item':int(itemid),'path':str(original),'force':True,'relinkOthers':False})],300)
  fresh=json.loads(project.read_text(encoding='utf-8'));new=fresh['project']['items'][str(itemid)]['kind']['Media']['info'].get('video')
  if old and new:
   replacements[int(itemid)]=(old['width']/new['width'],old['height']/new['height'])
 native=json.loads(project.read_text(encoding='utf-8'))
 def rescale(value,ratio,vector=False):
  if isinstance(value,dict):
   if vector and 'Vec2'in value:value['Vec2']['x']/=ratio[0];value['Vec2']['y']/=ratio[1]
   elif not vector and 'Float'in value:value['Float']*=ratio[1]
   else:
    for x in value.values():rescale(x,ratio,vector)
  elif isinstance(value,list):
   for x in value:rescale(x,ratio,vector)
 for item in native.get('project',{}).get('items',{}).values():
  sequence=item.get('kind',{}).get('Sequence',{})
  for track in sequence.get('video_tracks',[]):
   for clip in track.get('items',[]):
    ratio=replacements.get(clip.get('item'))
    if not ratio:continue
    for effect in clip.get('effects',[]):
     if effect.get('effect')!='motion':continue
     params=effect.get('params',{});rescale(params.get('scale',{}),ratio);rescale(params.get('anchor',{}),ratio,True)
     if params.get('uniform_scale',{}).get('value',{}).get('Bool')is False:
      rescale(params.get('scale_width',{}),(ratio[0],ratio[0]))
 project.write_text(json.dumps(native),encoding='utf-8')
 try:
  sys.path.insert(0,str(R.parent));import media_control as control
  control.unload('speech');control.unload('video')
  custom=ai or noise or sharp>0 or bool(side);tick('native-render',force=True)
  if not custom:
   params={'path':str(full),'format':codec,'hardwareEncoding':'auto','bitrateMode':'cbr','bitrateKbps':12000,'range':'custom','startSeconds':start,'endSeconds':end,'wait':True}
   run([FC,'--project',project,'exec','file.exportMedia',json.dumps(params)],21600);method='FilmCraft native export, hardware auto'
  else:
   audio=folder/'audio.wav';run([FC,'--project',project,'exec','file.exportMedia',json.dumps({'path':str(audio),'format':'wav','range':'custom','startSeconds':start,'endSeconds':end,'wait':True})])
   rate=str(num)+'/'+str(den);filters=[]
   if noise:filters.append('hqdn3d=1.2:1.2:3:3')
   if sharp:filters.append('unsharp=5:5:'+str(sharp)+':5:5:0')
   filters.append('scale='+str(ow)+':'+str(oh)+':flags=lanczos')
   log=(folder/'encode.log').open('wb')
   enc=launch([FF,'-v','error','-threads','2','-f','image2pipe','-framerate',rate,'-i','pipe:0','-i',audio,'-vf',','.join(filters),'-c:v','h264_nvenc'if codec=='h264'else'hevc_nvenc','-b:v','12000k','-maxrate','16000k','-bufsize','24000k','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-movflags','+faststart','-y',full],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=log)
   engine=Engine(project)
   try:
    for i in range(TOTAL):
     tick('ai-upscale'if ai else'native-frames',i)
     response=engine.tool('render_frame',{'seconds':start+i/fps,'max_side':max(w,h)})
     im=next((c for c in response.get('content',[])if c.get('type')=='image'),None)
     if not im:raise ValueError('FilmCraft returned no native frame')
     raw=base64.b64decode(im['data'],validate=True)
     if ai:
      src=folder/'frame.png';dst=folder/'upscaled.png';src.write_bytes(raw)
      if dst.exists():dst.unlink() # Owned ephemeral batch frame only.
      run([ES,'-i',src,'-o',dst,'-m',ES.parent/'models','-n','realesrgan-x4plus','-s','4','-t','128','-g','0','-j','1:1:1','-f','png'],300)
      raw=dst.read_bytes()
     enc.stdin.write(raw);enc.stdin.flush()
    enc.stdin.close();endwait=time.monotonic()+120
    while enc.poll()is None:
     tick('encode',TOTAL);time.sleep(.3)
     if time.monotonic()>endwait:raise ValueError('Encoder finalization timeout')
    if enc.returncode:raise ValueError('NVENC failed; see PC encode.log')
   finally:engine.close();log.close()
   method='FilmCraft native frames + '+('Real-ESRGAN x4plus + 'if ai else'')+'NVENC single final encode'
  tick('verify',TOTAL,True);verified=run([FF,'-v','error','-i',full,'-progress','pipe:1','-nostats','-f','null','-'],21600,True).decode()
  decoded=re.findall(r'(?m)^frame=(\d+)',verified)
  if not decoded or int(decoded[-1])!=TOTAL:raise ValueError('Full decode frame count mismatch')
  # Parse actual decoder metadata independently; no ffprobe install needed.
  pinfo=subprocess.run([FF,'-hide_banner','-i',str(full)],capture_output=True,text=True,encoding='utf-8',errors='replace')
  m=re.search(r'Video:.*? (\d{2,5})x(\d{2,5})',pinfo.stderr)
  if not m or full.stat().st_size<100:raise ValueError('Full output metadata missing')
  if (int(m[1]),int(m[2]))!=(ow,oh):raise ValueError('Rendered dimensions differ from requested native profile')
  if not re.search(r'Video: '+('hevc'if codec=='hevc'else'h264')+r'\b',pinfo.stderr):raise ValueError('Actual video codec mismatch')
  actualrate=re.search(r' ([0-9.]+) fps',pinfo.stderr)
  if not actualrate or abs(float(actualrate[1])-fps)>.02:raise ValueError('Actual frame rate mismatch')
  proxy=folder/'preview.mp4';preview_duration=min(duration,120);bitrate=max(160,min(900,int(28_000_000*8/preview_duration/1000)-96))
  vf='scale=640:-2:force_original_aspect_ratio=decrease'
  if job.get('qualityPreview'):
   before=folder/'before.mp4';run([FC,'--project',project,'exec','file.exportMedia',json.dumps({'path':str(before),'format':'h264','hardwareEncoding':'auto','scale':min(1,640/w),'range':'custom','startSeconds':start,'endSeconds':end,'wait':True})])
   run([FF,'-v','error','-i',before,'-i',full,'-filter_complex','[0:v]scale=320:-2:force_original_aspect_ratio=decrease[a];[1:v]scale=320:-2:force_original_aspect_ratio=decrease[b];[a][b]hstack=inputs=2[v]','-map','[v]','-map','1:a?','-c:v','h264_nvenc','-b:v',str(bitrate)+'k','-c:a','aac','-b:a','64k','-y',proxy]);comparison=True
  else:
   run([FF,'-v','error','-i',full,'-t',str(preview_duration),'-vf',vf,'-c:v','h264_nvenc','-b:v',str(bitrate)+'k','-c:a','aac','-b:a','64k','-movflags','+faststart','-y',proxy]);comparison=False
  meta={'pcJobId':ident,'previewDuration':preview_duration,'previewIsExcerpt':duration>preview_duration+.001,'fullPath':str(full),'fullBytes':full.stat().st_size,'fullSHA256':sha(full),'width':ow,'height':oh,'fps':fps,'frames':TOTAL,'codec':codec,'aiModel':'Real-ESRGAN x4plus'if ai else None,'elapsed':round(time.time()-START,2),'method':method,'comparison':comparison}
  atomic(folder/'ready.json',{'account':job['account'],'meta':meta});tick('upload-preview',TOTAL,True);return upload(proxy,meta)
 finally:
  # Only this run's immutable transfer copies and ephemeral processing files; keep full output/proxy/receipt/log.
  for f in folder.iterdir():
   if f.name in ['frame.png','upscaled.png','audio.wav','before.mp4','render.fcproj']or f.name.endswith('-corrected.flac')or re.fullmatch('[a-f0-9]{32}\\.[a-z0-9]+',f.name):
    try:f.unlink()
    except OSError:pass

def validate(job):
 if job.get('kind')not in ['render','pcOpen']or not re.fullmatch('[a-f0-9]{32}',job.get('id','')):raise ValueError('Invalid render job')
 if job['kind']=='render':
  expected=BASE+'pc-result/'+str(job.get('account'))+'/'+job['id']+'/mp4'
  if job.get('account')not in ['cat','code']or job.get('returnUrl')!=expected or not re.fullmatch('[a-f0-9]{64}',str(job.get('resultCap',''))):raise ValueError('Invalid render capability')
def main():
 global JOB,START
 mode=sys.argv[1]
 if mode=='--status':
  ident=sys.argv[2]
  if not re.fullmatch('[a-f0-9]{32}',ident):raise ValueError('Invalid job id')
  p=J/ident/'status.json';return json.loads(p.read_text())if p.exists()else{'pending':True}
 path=Path(sys.argv[2]).resolve()
 if not path.is_relative_to(Path.home()/'.openclaw/tmp')or path.stat().st_size>15_000_000:raise ValueError('Invalid staged request')
 job=json.loads(path.read_text(encoding='utf-8'));validate(job)
 if job['kind']=='pcOpen':
  ident=job.get('pcJobId','')
  if not re.fullmatch('[a-f0-9]{32}',ident)or not(E/(ident+'.mp4')).is_file():raise ValueError('Full file not found')
  ready=json.loads((J/ident/'ready.json').read_text())
  if ready.get('account')!=job.get('account'):raise ValueError('Wrong output account')
  subprocess.Popen(['explorer.exe','/select,'+str(E/(ident+'.mp4'))]);return {'ok':True,'output':{'opened':True}}
 if mode=='--begin':
  folder=J/job['id'];folder.mkdir(exist_ok=True)
  if (folder/'status.json').exists()or(folder/'running.json').exists():raise ValueError('Duplicate native render; check original status')
  atomic(folder/'running.json',{'started':time.time()});launch([sys.executable,'-B',Path(__file__),'--run',path],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  return {'pending':True}
 if mode!='--run':raise ValueError('Invalid worker mode')
 lock=(R/'gpu.lock').open('a+b');lock.seek(0);locked=False
 try:
  JOB=job;START=time.time();deadline=time.monotonic()+259200
  while not locked:
   try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1);locked=True
   except OSError:
    tick('waitingFrameGPU',0,True)
    if time.monotonic()>deadline:raise ValueError('Frame GPU queue timeout')
    time.sleep(2)
  result=work(job)
 except Exception as e:result={'ok':False,'error':str(e)[:600]}
 finally:
  for p in CHILDREN:
   if p.poll()is None:
    try:p.terminate();p.wait(10)
    except Exception:pass
  if locked:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
  lock.close()
  for f in (J/job['id']).iterdir():
   if f.name in ['frame.png','upscaled.png','audio.wav','before.mp4','render.fcproj']or f.name.endswith('-corrected.flac')or re.fullmatch(r'[a-f0-9]{32}\.[a-z0-9]+',f.name):
    try:f.unlink()
    except OSError:pass
 atomic(J/job['id']/'status.json',result);return result
if __name__=='__main__':
 try:emit(main())
 except Exception as e:emit({'ok':False,'error':str(e)[:600]});sys.exit(1)
