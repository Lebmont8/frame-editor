#!/usr/bin/env python3
"""Frame: owner-only UI adapter; all editing/rendering is FilmCraft."""
import shutil,sys
import argparse,base64,hashlib,hmac,http.client,json,math,mimetypes,os,queue,re,secrets,signal,subprocess,threading,time,uuid
from pathlib import Path
from bridge import Mailbox
from local_media import receive as receive_pc
from pc_render import PCRender,pc_input
from objects import Objects,mapping as object_mapping,original_url
from pc_objects import receive as receive_pc_object
from ai_workflow import WorkflowAI,read_ai,save_ai,fingerprint,quality_filter
from workflow import read_workflow,save_workflow,media_list,derive,clean_audio,correlate
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit,parse_qs,unquote
ROOT=Path(__file__).resolve().parent
FC=Path(os.environ['FRAME_ENGINE'])
TICKS=254016000000
PREFIX='/youtube-hub/frame'
ORIGIN=os.environ['FRAME_LOCAL_ORIGIN']
args=argparse.ArgumentParser()
args.add_argument('--port',type=int,default=58121)
args.add_argument('--data',default=str(ROOT/'data'))
opt=args.parse_args()
DATA=Path(opt.data).resolve();DATA.mkdir(exist_ok=True)
for p in ['projects','uploads','renders']: (DATA/p).mkdir(exist_ok=True)
MAX_UPLOAD=64*1024**2;MAX_SPOOL=8*1024**3
KEY=secrets.token_bytes(32);jobs={};job_lock=threading.Lock()
def spool_size():return sum(p.stat().st_size for p in DATA.rglob('*') if p.is_file())
def capacity(size):
 free=shutil.disk_usage(DATA).free
 if free<size or spool_size()+size>MAX_SPOOL:raise ValueError('Рабочее хранилище заполнено. Нужен перенос проекта в Object Storage.')
def finite(v,lo,hi):
 n=float(v)
 if not math.isfinite(n) or not lo<=n<=hi:raise ValueError('Значение вне допустимого диапазона')
 return n
class Engine:
 def __init__(self,path):
  self.path=path;self.lock=threading.RLock();self.ident=0;self.q=queue.Queue()
  cmd=[str(FC)]
  if path.exists():cmd+=['--project',str(path)]
  self.p=subprocess.Popen(cmd+['mcp'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',bufsize=1,env={**os.environ,'RAYON_NUM_THREADS':'2','FILMCRAFT_DATA_DIR':str(DATA/'config')},start_new_session=(os.name!="nt"))
  self._reader_ended=False
  def reader():
   error=None
   try:
    for line in self.p.stdout:
     try:self.q.put(json.loads(line))
     except ValueError:pass
   except(UnicodeError,OSError)as exc:error=str(exc)
   finally:
    self._reader_ended=True
    self.q.put({'_eof':True,'error':error})
  threading.Thread(target=reader,daemon=True).start()
  self.rpc('initialize',{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'Frame','version':'0.2'}})
  self.p.stdin.write('{"jsonrpc":"2.0","method":"notifications/initialized"}\n');self.p.stdin.flush()
 def rpc(self,method,params):
  with self.lock:
   if self._reader_ended and self.q.empty():raise RuntimeError('Связь с движком завершена; требуется перезапуск Frame')
   self.ident+=1;i=self.ident
   self.p.stdin.write(json.dumps({'jsonrpc':'2.0','id':i,'method':method,'params':params})+'\n');self.p.stdin.flush()
   deadline=time.monotonic()+(21600 if method=='tools/call'and params.get('name')=='command_run'and params.get('arguments',{}).get('id')=='file.exportMedia'else 900)
   while True:
    r=self.q.get(timeout=max(.1,deadline-time.monotonic()))
    if r.get('_eof'):raise RuntimeError('Связь с движком завершена. '+(r.get('error')or'Требуется перезапуск Frame'))
    if r.get('id')!=i:continue
    if 'error'in r:raise ValueError(str(r['error'])[:300])
    return r['result']
 def tool(self,name,params={}):
  r=self.rpc('tools/call',{'name':name,'arguments':params})
  texts=[c.get('text','') for c in r.get('content',[]) if c.get('type')=='text']
  if r.get('isError'):raise ValueError(' '.join(texts)[:500])
  if 'structuredContent'in r:return r['structuredContent']
  if texts:
   try:return json.loads(texts[0])
   except ValueError:return {'text':texts[0]}
  return r
 def command(self,id,params={}):return self.tool('command_run',{'id':id,'params':params})
 def save(self):self.command('file.saveAs',{'path':str(self.path)})
 def state(self):return self.tool('doc_inspect')
 def close(self):
  self.p.terminate()
  try:self.p.wait(timeout=5)
  except subprocess.TimeoutExpired:self.p.kill();self.p.wait()
manager_lock=threading.RLock()
active_path=DATA/'projects/pilot.fcproj'
try:
 last=json.loads((DATA/'active-project.json').read_text())['name']
 if Path(last).name==last and last.endswith('.fcproj') and (DATA/'projects'/last).is_file():active_path=DATA/'projects'/last
except (OSError,ValueError,KeyError):pass
if not active_path.exists():
 active_path=DATA/'projects/untitled.fcproj'
engine=Engine(active_path)
if not active_path.exists():
 engine.command('file.newProject',{'name':'Новый монтаж'})
 engine.command('file.newSequence',{'name':'Монтаж','width':1920,'height':1080,'fps':25,'video':2,'audio':2})
 engine.save()
update_prepared=False
revision=1;snapshot=engine.state();preview=None;frame=None
def refresh(changed=True):
 global snapshot,revision,frame
 if changed:
  engine.save();revision+=1;frame=None
  pointer=DATA/'active-project.new'
  pointer.write_text(json.dumps({'name':engine.path.name}))
  pointer.replace(DATA/'active-project.json')
 snapshot=engine.state()
def getseq():
 return snapshot.get('sequence') or snapshot.get('activeSequence') or {}
def allclips():
 s=getseq()
 return [(kind,t,c) for kind in ['video','audio'] for t in s.get(kind,[]) for c in t.get('items',[]) if 'clip'in c]
def clipby(id):
 for k,t,c in allclips():
  if c['clip']==int(id):return k,t,c
 raise ValueError('Фрагмент не найден')
def nonblocking(j):return j.get('kind')in ['pcExport','pcQualityPreview']or j.get('kind')=='ai:dubFull'and j.get('snapshotReady')is True
def mutate(action,d):
 global engine,active_path,preview,frame,update_prepared
 with manager_lock:
  if action=='desktopUpdateAbort':update_prepared=False;return {'ok':True}
  if update_prepared:raise ValueError('Применяется обновление')
  if action=='desktopUpdatePrepare':
   if any(j.get('status')in ['running','queued','paused']for j in jobs.values()):raise ValueError('Дождись завершения текущих задач перед обновлением')
   engine.save();update_prepared=True;return {'prepared':True,'project':engine.path.name}
  if action=='aiTranslationReview':
   if any(j['status']=='running'and j.get('kind')=='ai:translateTracks'for j in jobs.values()):raise ValueError('Дождись завершения перевода')
   state=read_ai(engine.path);all=state.get('translations',{});language=d['language'];track=all.get('tracks',{}).get(language)
   from ai_workflow import audio_fingerprint
   from audio_workflow import normalize_segments
   if not track or all.get('audioFingerprint')!=audio_fingerprint(getseq()) or all.get('sourceTranscriptHash')!=hashlib.sha256(json.dumps(state.get('transcript',{}).get('segments',[]),sort_keys=True).encode()).hexdigest():raise ValueError('Перевод устарел')
   if 'segments'in d:
    track['segments']=normalize_segments(d['segments'],getseq()['duration']/TICKS);track['version']=hashlib.sha256(json.dumps(track['segments'],sort_keys=True).encode()).hexdigest()
    from ai_workflow import srt
    dest=DATA/'renders'/('translation-edit-'+track['version'][:24]+'.srt');dest.write_text(srt(track['segments']));track['url']=PREFIX+'/files/renders/'+dest.name
   track['approved']=d.get('approved')is True;save_ai(engine.path,state);return state_payload()
  if action=='object':return object_media.action(d['operation'],d)
  if action=='pcRenderControl':
   pc_renderer.control(d['id'],d['control']);return state_payload()
  if action=='aiCancel':
   for j in jobs.values():
    if j['status']=='running':j['cancelRequested']=True
   Mailbox(DATA).cancel_all();return state_payload()
  if any(j['status']=='running'and not nonblocking(j)for j in jobs.values()):raise ValueError('Дождись завершения рендера')
  if action=='desktopImport':
   paths=d.get('paths',[])
   if not isinstance(paths,list)or not 1<=len(paths)<=100:raise ValueError('Выбери файлы')
   for raw in paths:
    p=Path(raw).resolve(strict=True)
    if not p.is_file()or p.suffix.lower()not in ['.mp4','.mov','.mkv','.webm','.wav','.mp3','.flac','.png','.jpg','.jpeg']:raise ValueError('Неподдерживаемый материал')
   result=engine.command('file.import',{'paths':paths})
   if result.get('errors'):raise ValueError(str(result['errors'])[:300])
   refresh();derive(engine.path,DATA,PREFIX);return state_payload()
  if action=='workflow':
   before=read_workflow(engine.path).get('exportProfile',{})
   save_workflow(engine.path,d['workflow'])
   if read_workflow(engine.path).get('exportProfile',{})!=before:refresh()
   return state_payload()
  if action=='providersSave':
   ai.save_settings(d.get('settings',{}));return state_payload()
  if action=='aiJob':
   ai.start(d['kind'],d);return state_payload()
  if action=='aiTranscript':
   ai.manual_transcript(engine.path,getseq(),read_workflow(engine.path).get('exportProfile'),d['segments']);return state_payload()
  if action=='aiDecision':
   ai.decide(engine.path,getseq(),read_workflow(engine.path).get('exportProfile'),d['id'],d['decision'],d.get('kind','analysis'),d.get('start'),d.get('end'));return state_payload()
  if action=='aiSelectCovers':
   state=read_ai(engine.path);gallery=state.get('gallery',{});ids=d.get('ids',[])
   if not isinstance(ids,list)or len(ids)>3:raise ValueError('Выбери не больше трёх обложек')
   if any(id not in [x['id']for x in gallery.get('images',[])]for id in ids):raise ValueError('Обложка не найдена')
   for image in gallery.get('images',[]):image['selected']=image['id']in ids
   save_ai(engine.path,state);return state_payload()
  if action=='aiCoverZip':
   import zipfile
   state=read_ai(engine.path);images=[x for x in state.get('gallery',{}).get('images',[])if x.get('selected')]
   if not images or len(images)>3:raise ValueError('Выбери до трёх обложек')
   paths=[]
   for im in images:
    name=Path(im['url'].split('/files/renders/',1)[-1]).name;p=(DATA/'renders'/name).resolve()
    if not p.is_relative_to(DATA/'renders')or not p.is_file()or p.suffix!='.png':raise ValueError('Обложка недоступна')
    paths.append(p)
   capacity(sum(p.stat().st_size for p in paths)+100000)
   dest=DATA/'renders'/('selected-covers-'+uuid.uuid4().hex[:10]+'.zip')
   with zipfile.ZipFile(dest,'w',zipfile.ZIP_STORED)as z:
    for i,p in enumerate(paths):z.write(p,'cover-'+str(i+1)+'.png')
   return {'url':PREFIX+'/files/renders/'+dest.name}
  if action=='swapInsert':
   item=int(d['item']);start=finite(d.get('seconds',0),0,7200);length=finite(d.get('duration',3),.1,7200)
   if start+length>getseq()['duration']/TICKS+.001:raise ValueError('Вставка выходит за конец монтажа')
   m=next((x for x in media_list(engine.path,DATA,PREFIX)if x['item']==item),None)
   if not m or m['type']not in ['Movie','Still']:raise ValueError('Выбери фото или видео')
   if m['type']=='Movie'and length>m['duration']/TICKS+.001:raise ValueError('Вставка короче выбранного интервала')
   wf=read_workflow(engine.path);wf['roles']={**wf.get('roles',{}),str(item):'insert'};save_workflow(engine.path,wf)
   ai_context()['apply_inserts']([{'item':item,'start':start,'duration':length,'layout':'swap'}]);return state_payload()
  if action=='applyColorMatch':
   state=read_ai(engine.path);match=state.get('colorMatch',{})
   if match.get('fingerprint')!=fingerprint(getseq(),read_workflow(engine.path).get('exportProfile')):raise ValueError('Монтаж изменился. Подбери цвет заново.')
   if match.get('lut'):
    lut=Path(match['lut']).resolve()
    if not lut.is_relative_to(DATA/'renders')or not lut.is_file()or lut.suffix!='.cube':raise ValueError('LUT недоступен')
    _,_,clip=clipby(match['clip'])
    if not any(e.get('effect')=='lumetri'for e in clip.get('effects',[])):engine.command('effects.apply',{'clips':[clip['clip']],'effect':'lumetri'})
    engine.command('effects.setParam',{'clip':clip['clip'],'effect':'lumetri','param':'look_lut','value':str(lut)});engine.command('effects.setParam',{'clip':clip['clip'],'effect':'lumetri','param':'look_intensity','value':100});refresh();return state_payload()
   return mutate('color',{'clip':match['clip'],**{k:v for k,v in match['params'].items()if k in ['exposure','contrast','saturation']}})
  if action in ['clean','syncAnalyze','syncCorrect']:
   return start_processing(action,d)
  seq=getseq();fps=seq.get('settings',{}).get('frame_rate',{'num':25,'den':1});fps=fps['num']/fps['den']
  if action=='new':
   p=DATA/'projects'/('project-'+uuid.uuid4().hex[:10]+'.fcproj')
   engine.command('file.newProject',{'name':'Новый монтаж'})
   engine.command('file.newSequence',{'name':'Монтаж','width':1920,'height':1080,'fps':25,'video':2,'audio':2})
   engine.path=p;active_path=p;preview=None;frame=None
  elif action=='open':
   name=Path(d['name']).name;p=DATA/'projects'/name
   if name!=d['name'] or p.suffix!='.fcproj' or not p.is_file():raise ValueError('Проект не найден')
   engine.close();engine=Engine(p);active_path=p;preview=None;frame=None
   ai.recover(p)
  elif action=='add':
   start=finite(d.get('seconds',0),0,7200)
   om=next((m for m in media_list(engine.path,DATA,PREFIX)if m['item']==int(d['item'])),None)
   original=om.get('original')if om else None
   if original and getseq().get('duration',0)==0 and om.get('type')=='Movie':
    ov=next((v for v in original.get('probe',{}).get('streams',[])if v.get('codec_type')=='video'),None)
    if ov:
     num,den=map(int,ov.get('r_frame_rate','25/1').split('/'));engine.command('sequence.settings',{'width':ov['width'],'height':ov['height'],'fps':num/max(1,den)});refresh(False)
   params={'item':int(d['item']),'track':d.get('track','V1'),'seconds':start,'insert':bool(d.get('insert',False)),'matchSequence':not bool(original)}
   if 'sourceIn'in d:params['sourceIn']={'seconds':finite(d['sourceIn'],0,7200)}
   if 'duration'in d:params['duration']={'seconds':finite(d['duration'],.001,7200)}
   if params['track'] not in ['V1','V2','A1','A2']:raise ValueError('Неизвестная дорожка')
   if params['track'].startswith('A'):params.update(video=False,audio=True)
   if params['track']=='V2':params['audio']=False
   prior={c['clip']for _,_,c in allclips()};engine.command('timeline.place',params)
   if original and om.get('type')=='Movie'and params.get('video',True):
    now=engine.state()['sequence'];settings=now['settings'];info=om.get('info',{}).get('video',{})
    fit=min(settings['width']/max(1,info.get('width',settings['width'])),settings['height']/max(1,info.get('height',settings['height'])))*100
    for track in now.get('video',[]):
     for clip in track.get('items',[]):
      if clip.get('clip')and clip['clip']not in prior:engine.command('effects.setParam',{'clip':clip['clip'],'effect':'motion','param':'scale','value':fit})
  elif action=='track':
   track=d.get('track')
   if track not in ['V1','V2','A1','A2']:raise ValueError('Дорожка не найдена')
   params={'track':track}
   if 'muted'in d and track.startswith('A'):params['muted']=bool(d['muted'])
   if 'enabled'in d and track.startswith('V'):params['enabled']=bool(d['enabled'])
   engine.command('timeline.setTrack',params)
  elif action=='trim':
   _,_,c=clipby(d['clip']);edge=d['edge']
   if edge not in ['in','out']:raise ValueError('Неверная граница')
   delta=round(finite(d['seconds'],-7200,7200)*fps)
   engine.command('timeline.trim',{'clip':c['clip'],'edge':edge,'mode':'regular','deltaFrames':delta,'linked':d.get('linked',True)is True})
  elif action=='move':
   kind,t,c=clipby(d['clip']);track=d.get('track',t['name'])
   if track not in ['V1','V2','A1','A2']:raise ValueError('Неизвестная дорожка')
   engine.command('timeline.move',{'moves':[{'clip':c['clip'],'track':track,'time':{'seconds':finite(d['seconds'],0,7200)}}],'insert':False,'linked':d.get('linked',True)is True})
  elif action=='split':
   engine.command('timeline.razor',{'time':round(finite(d['seconds'],0,7200)*TICKS)})
  elif action=='delete':
   _,_,c=clipby(d['clip'])
   targets=[x['clip'] for _,_,x in allclips() if x['clip']==c['clip'] or d.get('linked',True)is True and c.get('link') is not None and x.get('link')==c['link']]
   engine.command('sequence.linkedSelection',{'on':False})
   try:engine.command('timeline.delete',{'clips':targets,'ripple':bool(d.get('ripple',False))})
   finally:engine.command('sequence.linkedSelection',{'on':True})
  elif action=='gain':
   kind,_,c=clipby(d['clip'])
   if kind!='audio':raise ValueError('Выбери фрагмент на аудиодорожке')
   engine.command('clip.audioGain',{'clips':[c['clip']],'mode':'set','db':finite(d['db'],-60,15)})
  elif action=='color':
   kind,_,c=clipby(d['clip'])
   if kind!='video':raise ValueError('Выбери видеофрагмент')
   values={k:finite(d[k],*r) for k,r in {'exposure':(-5,5),'saturation':(0,200),'contrast':(-100,100)}.items() if k in d}
   if not any(e.get('effect')=='lumetri' for e in c.get('effects',[])):engine.command('effects.apply',{'clips':[c['clip']],'effect':'lumetri'})
   for k,v in values.items():engine.command('effects.setParam',{'clip':c['clip'],'effect':'lumetri','param':k,'value':v})
  elif action=='transform':
   kind,_,c=clipby(d['clip'])
   if kind!='video':raise ValueError('Выбери видеофрагмент')
   engine.command('effects.setParam',{'clip':c['clip'],'effect':'motion','param':'scale','value':finite(d.get('scale',100),1,400)})
   w=seq['settings']['width'];h=seq['settings']['height']
   engine.command('effects.setParam',{'clip':c['clip'],'effect':'motion','param':'position','value':[finite(d.get('x',w/2),-w,w*2),finite(d.get('y',h/2),-h,h*2)]})
  elif action in ['undo','redo']:engine.command('edit.'+action)
  elif action=='save':
   engine.save();refresh(False);return state_payload()
  else:raise ValueError('Неизвестное действие')
  refresh()
  return state_payload()
def enrich_pc_jobs():
 for j in list(jobs.values()):
  if j['status']!='running'or not re.fullmatch('[a-f0-9]{32}',str(j.get('remoteId',''))):continue
  try:j['pcProgress']=json.loads((DATA/'bridge'/(j['remoteId']+'.progress.json')).read_text())
  except (OSError,ValueError):pass
def state_payload():
 pc_renderer.enrich();enrich_pc_jobs()
 storage={'used':spool_size(),'limit':MAX_SPOOL,'available':shutil.disk_usage(DATA).free}
 return {'document':snapshot,'revision':revision,'project':engine.path.name,'projects':[p.name for p in (DATA/'projects').glob('*.fcproj')],'preview':preview,'frame':frame,'jobs':[j for j in jobs.values() if j.get('project')==engine.path.name][-10:],'storage':storage,'engine':'FilmCraft 0.20.1','limitBytes':MAX_UPLOAD,'objectLimitBytes':10*1024**3,'durationLimit':7200,'media':media_list(engine.path,DATA,PREFIX),'workflow':read_workflow(engine.path),'connections':Mailbox(DATA).status(),'ai':ai.state(engine.path,getseq(),read_workflow(engine.path).get('exportProfile'))}
def start_processing(action,d):
 media=media_list(engine.path,DATA,PREFIX)
 def source(id):
  m=next((a for a in media if a['item']==int(id)),None)
  if not m:raise ValueError('Материал не найден')
  return Path(m['path'])
 a=source(d['item']);b=source(d['video'])if action=='syncAnalyze'else None
 from sound import duration as media_duration
 length=media_duration(a)
 capacity(math.ceil(length*200000)+5000000 if action in ['clean','syncCorrect']else 5000000)
 ident=uuid.uuid4().hex[:12];at=revision;project=engine.path
 j={'id':ident,'status':'running','kind':action,'sourceItem':int(d['item']),'videoItem':int(d.get('video',0)),'revision':at,'project':engine.path.name,'started':time.time()};jobs[ident]=j
 def run():
  try:
   if action in ['clean','syncCorrect']:
    om=next(m for m in media if m['item']==int(d['item']));original=om.get('original');src=original_url(original['objectId'])['url']if original else a
    target=DATA/'uploads'/((('clean-'if action=='clean'else'clock-')+ident)+('.flac'if length>600 or action=='syncCorrect'else'.wav'))
    if action=='clean':clean_audio(src,target)
    else:
     prior=jobs.get(str(d.get('analysis','')),{}) or read_workflow(project).get('syncAnalysis',{})
     result=prior.get('result',{})
     if prior.get('kind')!='syncAnalyze'or prior.get('sourceItem')!=int(d['item'])or prior.get('status')!='done'or not .995<=float(result.get('tempo',0))<=1.005:raise ValueError('Сначала выполни проверку дрейфа этой дорожки')
     r=subprocess.run(['ffmpeg','-v','error','-threads','1','-i',str(src),'-vn','-af','atempo='+str(result['tempo']),'-c:a','flac','-y',str(target)],capture_output=True,timeout=1800)
     if r.returncode:raise ValueError('Коррекция часов не завершена; исходник сохранён')
     j['result']=result
    if length>600 or action=='syncCorrect':
     from objects import publish_local,mapping,save_mapping
     obj=publish_local(target,('audioClean'if action=='clean'else'audioClock'));proxy=target.with_suffix('.mp3')
     r=subprocess.run(['ffmpeg','-v','error','-threads','1','-i',str(target),'-c:a','libmp3lame','-b:a','64k','-y',str(proxy)],capture_output=True,timeout=1800)
     if r.returncode:raise ValueError('Полный результат сохранён, но просмотр не собран')
     maps=mapping(DATA);maps[str(proxy.resolve())]={'objectId':obj['id'],'name':target.name,'bytes':obj['bytes'],'sha256':obj['sha256'],'derivedFrom':int(d['item'])};save_mapping(DATA,maps)
     target.unlink();target=proxy
    with manager_lock:
     if engine.path!=project:raise ValueError('Проект изменился во время обработки')
     before={a['item']for a in media}
     engine.command('file.import',{'paths':[str(target)]});refresh();derive(engine.path,DATA,PREFIX)
     added=next(m for m in media_list(engine.path,DATA,PREFIX) if m['item']not in before)
     j.update(item=added['item'],url=added['url'])
     wf=read_workflow(project)
     if action=='clean':wf['audioCandidates']={**wf.get('audioCandidates',{}),str(int(d['item'])):{'item':added['item'],'accepted':False}}
     else:wf['sync']={**wf.get('sync',{}),'item':added['item'],'seconds':j['result']['seconds'],'tempo':j['result']['tempo'],'correctedFrom':int(d['item'])}
     role=wf.get('roles',{}).get(str(int(d['item'])),'audio')
     wf['roles']={**wf.get('roles',{}),str(added['item']):role+('Clean'if action=='clean'else'Clock')};save_workflow(project,wf)
   elif d.get('drift'):
    from sound import drift
    j['result']=drift(b,a,float(d.get('baseOffset',0)))
   else:j['result']=correlate(b,a)
   if action=='syncAnalyze':
    with manager_lock:
     if engine.path!=project:raise ValueError('Проект изменился во время анализа')
     wf=read_workflow(project);wf['syncAnalysis']={**j,'status':'done','videoItem':int(d['video'])};save_workflow(project,wf)
   j.update(status='done',finished=time.time())
  except Exception as e:j.update(status='error',error=str(e)[:400],finished=time.time())
 threading.Thread(target=run,daemon=True).start()
 return state_payload()
def start_export(preview_mode,options=None):
 options=options or {}
 if not preview_mode:
  profile=read_workflow(engine.path).get('exportProfile',{})
  if profile.get('renderDevice','pc')=='pc' or options.get('qualityPreview'):
   with manager_lock:
    engine.save();return pc_renderer.start(engine.path,getseq(),profile,revision,bool(options.get('qualityPreview')),finite(options.get('seconds',0),0,7200),options.get('resume'))
  if any(m.get('original')for m in media_list(engine.path,DATA,PREFIX)):raise ValueError('Полный файл с Object Storage собирается на ПК. Серверный просмотр остаётся облегчённым.')
  if profile.get('aiUpscale'):raise ValueError('ИИ-апскейл доступен только на ПК')
  if profile.get('codec')=='hevc':raise ValueError('HEVC доступен только на ПК')
 with manager_lock:
  if any(j['status']=='running'and not nonblocking(j)for j in jobs.values()):raise ValueError('Рендер уже выполняется')
  seq=getseq();duration=seq.get('duration',0)/TICKS
  if duration<=0:raise ValueError('Добавь видео на таймлайн')
  if duration>7200:raise ValueError('Рабочий предел — 2 часа на проект')
  capacity(math.ceil(duration*(150000 if preview_mode else 1500000))+25_000_000)
  ident=uuid.uuid4().hex[:12];at=revision
  p=DATA/'renders'/(ident+'.mp4')
  j={'id':ident,'status':'running','kind':'preview' if preview_mode else 'export','revision':at,'project':engine.path.name,'started':time.time()}
  jobs[ident]=j
  def run():
   global preview
   try:
    settings=seq['settings'];scale=min(1,640/settings['width']) if preview_mode else 1
    profile=read_workflow(engine.path).get('exportProfile',{})
    filtered=quality_filter(profile,seq['settings']['width'],seq['settings']['height'],preview_mode)
    native=p.with_suffix('.native.mp4')if filtered else p
    result=engine.command('file.exportMedia',{'path':str(native),'format':'h264','scale':scale,'crf':25 if preview_mode else 20,'bitrateKbps':300 if preview_mode else 4000,'hardwareEncoding':'off','wait':True})
    if filtered:
     r=subprocess.run(['ffmpeg','-v','error','-threads','1','-i',str(native),'-vf',filtered,'-c:v','libx264','-preset','veryfast','-b:v','300k'if preview_mode else'8000k','-maxrate','400k'if preview_mode else'8000k','-bufsize','800k'if preview_mode else'16000k','-c:a','copy','-y',str(p)],capture_output=True,timeout=7200)
     if r.returncode:raise ValueError('Финишная обработка не завершена')
     native.unlink()
    if not p.exists() or p.stat().st_size<100:raise RuntimeError('FilmCraft не создал файл')
    check=subprocess.run(['ffmpeg','-v','error','-i',str(p),'-f','null','-'],capture_output=True,timeout=7200)
    if check.returncode or check.stderr:raise RuntimeError('Экспорт не прошёл независимую проверку декодирования')
    j.update(status='done',bytes=p.stat().st_size,url=PREFIX+'/files/renders/'+p.name,result=result,finished=time.time())
    if preview_mode:preview={'url':j['url'],'revision':at}
   except Exception as e:j.update(status='error',error=str(e)[:400],finished=time.time())
  threading.Thread(target=run,daemon=True).start()
  return j
def render_png(seconds,p):
 capacity(6000000)
 raw=engine.rpc('tools/call',{'name':'render_frame','arguments':{'seconds':seconds,'max_side':960}})
 im=next((c for c in raw.get('content',[])if c.get('type')=='image'),None)
 if not im:raise ValueError('FilmCraft не вернул кадр')
 png=base64.b64decode(im['data']);profile=read_workflow(engine.path).get('exportProfile',{})
 filters=quality_filter(profile,getseq()['settings']['width'],getseq()['settings']['height'],True)
 if filters:
  temp=p.with_name(p.stem+'-native.png');temp.write_bytes(png)
  r=subprocess.run(['ffmpeg','-v','error','-threads','1','-i',str(temp),'-vf',filters,'-frames:v','1','-y',str(p)],capture_output=True,timeout=30);temp.unlink()
  if r.returncode:raise ValueError('Не удалось улучшить кадр')
 else:p.write_bytes(png)
def ai_context():
 path=engine.path;seq=getseq();wf=read_workflow(path)
 def export_proxy(p):
  settings=getseq()['settings'];engine.command('file.exportMedia',{'path':str(p),'format':'h264','scale':min(1,640/settings['width']),'crf':25,'bitrateMode':'cbr','bitrateKbps':300,'hardwareEncoding':'off','wait':True})
 def source_frame(m,p,at=None):
  source=Path(m['path'])
  if m.get('original'):source=original_url(m['original']['objectId'])['url']
  total=max(0,m['duration']/TICKS);rate=m.get('info',{}).get('video',{}).get('frame_rate')or{'num':25,'den':1}
  last=max(0,total-rate['den']/max(1,rate['num']))
  seconds=min(last,min(3,total*.25)if at is None else finite(at,0,7200))if m['type']=='Movie'else 0
  r=subprocess.run(['ffmpeg','-v','error','-threads','1','-ss',str(seconds if m['type']=='Movie'else 0),'-i',str(source),'-frames:v','1','-vf','scale=960:960:force_original_aspect_ratio=decrease','-y',str(p)],capture_output=True,timeout=35)
  if r.returncode or not Path(p).is_file():raise ValueError('Не удалось прочитать референс на выбранном времени')
  return p
 def identity_frame(p,at):
  head=next((x for t in seq.get('video',[])[:1]for x in t.get('items',[])if x.get('clip')and x['start']/TICKS<=at<(x['start']+x['duration'])/TICKS),None)
  m=next((m for m in media_list(path,DATA,PREFIX)if head and m['item']==head['item']),None)
  if m and m.get('original'):return source_frame(m,p,head.get('sourceIn',0)/TICKS+(at-head['start']/TICKS)*head.get('speed',1))
  render_png(at,p);return p
 def import_file(p):
  before={m['item']for m in media_list(path,DATA,PREFIX)}
  r=engine.command('file.import',{'paths':[str(p)]})
  if r.get('errors'):raise ValueError('FilmCraft не смог импортировать результат')
  refresh();derive(path,DATA,PREFIX)
  return next(m['item']for m in media_list(path,DATA,PREFIX)if m['item']not in before)
 def transaction(fn):
  global engine,snapshot
  original=path.read_bytes()
  try:fn();refresh()
  except Exception as e:
   engine.close();path.write_bytes(original);engine=Engine(path);refresh();raise ValueError('Исходный монтаж восстановлен: '+str(e)[:240])
 def apply_cuts(rows):
  def run():
   global snapshot
   for cut in rows:
    a=round(float(cut['start'])*TICKS);b=round(float(cut['end'])*TICKS)
    engine.command('timeline.razor',{'time':b})
    if a>0:engine.command('timeline.razor',{'time':a})
    snapshot=engine.state()
    targets=[c['clip']for _,_,c in allclips()if c['start']>=a-1 and c['end']<=b+1]
    if not targets:raise ValueError('В интервале нет фрагментов')
    engine.command('timeline.delete',{'clips':targets,'ripple':True});snapshot=engine.state()
  transaction(run)
 def apply_inserts(rows):
  def run():
   global snapshot
   allowed={m['item']:m for m in media_list(path,DATA,PREFIX)if wf.get('roles',{}).get(str(m['item']))=='insert'}
   for r in rows:
    if r['item']not in allowed:raise ValueError('Неизвестная вставка')
    start=round(float(r['start'])*TICKS);end=round((float(r['start'])+float(r['duration']))*TICKS);swap=r['layout']=='swap'
    if swap:
     v2=getseq().get('video',[{},{}])[1].get('items',[])
     if any(x.get('clip')and x['start']<end and x['end']>start for x in v2):raise ValueError('Для смены компоновки V2 должна быть свободна в этом интервале')
     engine.command('timeline.razor',{'time':end,'track':'V1'})
     if start>0:engine.command('timeline.razor',{'time':start,'track':'V1'})
     snapshot=engine.state()
     heads=[x for x in getseq()['video'][0]['items']if x.get('clip')and x['start']>=start-1 and x['end']<=end+1]
     if not heads or sum(x['duration']for x in heads)<end-start-2:raise ValueError('Под этим интервалом нужен непрерывный видеоряд V1')
     media={m['item']:m for m in media_list(path,DATA,PREFIX)}
     for head in heads:
      engine.command('timeline.move',{'moves':[{'clip':head['clip'],'track':'V2','time':head['start']}],'insert':False,'linked':False})
      settings=getseq()['settings'];info=media.get(head['item'],{}).get('info',{}).get('video',{})
      fit=min(settings['width']/max(1,info.get('width',settings['width'])),settings['height']/max(1,info.get('height',settings['height'])))*100
      engine.command('effects.setParam',{'clip':head['clip'],'effect':'motion','param':'scale','value':fit*.28})
      engine.command('effects.setParam',{'clip':head['clip'],'effect':'motion','param':'position','value':[settings['width']*.8,settings['height']*.2]})
     snapshot=engine.state()
    before={c['clip']for _,_,c in allclips()}
    engine.command('timeline.place',{'item':r['item'],'track':'V1'if swap else'V2','seconds':float(r['start']),'duration':{'seconds':float(r['duration'])},'video':True,'audio':False,'insert':False})
    snapshot=engine.state();added=next(c for kind,t,c in allclips()if kind=='video'and c['clip']not in before)
    settings=getseq()['settings'];info=allowed[r['item']]['info'].get('video',{})
    fit=min(settings['width']/max(1,info.get('width',settings['width'])),settings['height']/max(1,info.get('height',settings['height'])))*100
    pip=r['layout']=='pip';scale=fit*(.35 if pip else 1)
    engine.command('effects.setParam',{'clip':added['clip'],'effect':'motion','param':'scale','value':scale})
    engine.command('effects.setParam',{'clip':added['clip'],'effect':'motion','param':'position','value':[settings['width']*(.78 if pip else .5),settings['height']*(.24 if pip else .5)]})
    snapshot=engine.state()
  transaction(run)
 def color_baseline(p,clipid,at):
  native=json.loads(path.read_text());temp=p.with_suffix('.fcproj')
  for item in native['project']['items'].values():
   sequence=item.get('kind',{}).get('Sequence',{})
   for track in sequence.get('video_tracks',[]):
    track['items']=[x for x in track.get('items',[])if x.get('id')==clipid]
    for clip in track['items']:
     for effect in clip.get('effects',[]):
      if effect.get('effect')=='lumetri':effect.setdefault('params',{}).setdefault('look_lut',{})['value']={'Text':''}
  temp.write_text(json.dumps(native));result=subprocess.run([str(FC),'--project',str(temp),'render','--seconds',str(at),'--out',str(p),'--scale','0.5'],capture_output=True,timeout=90)
  if result.returncode:raise ValueError('Не удалось прочитать чистую основу выбранного клипа')
  return p
 def voice_reference(p,start,end):
  native=p.with_suffix('.native.wav');engine.command('file.exportMedia',{'path':str(native),'format':'wav','range':'custom','startSeconds':start,'endSeconds':end,'wait':True})
  r=subprocess.run(['ffmpeg','-v','error','-threads','1','-i',str(native),'-ar','24000','-ac','1','-c:a','pcm_s16le','-y',str(p)],capture_output=True,timeout=45)
  if r.returncode:raise ValueError('Нет пригодного опорного голоса')
  native.unlink();return p
 return {'path':path,'sequence':seq,'workflow':wf,'profile':wf.get('exportProfile'),'media':media_list(path,DATA,PREFIX),'export_proxy':export_proxy,'frame':render_png,'source_frame':source_frame,'identity_frame':identity_frame,'color_baseline':color_baseline,'voice_reference':voice_reference,'import_file':import_file,'apply_cuts':apply_cuts,'apply_inserts':apply_inserts}
pc_renderer=PCRender(DATA,PREFIX,jobs,manager_lock,capacity)
object_media=Objects(DATA,PREFIX,jobs,manager_lock,capacity,ai_context)
ai=WorkflowAI(DATA,PREFIX,ai_context,jobs,manager_lock,capacity);ai.recover(engine.path)
class Handler(BaseHTTPRequestHandler):
 protocol_version='HTTP/1.1'
 def log_message(self,*args):pass
 def headers_out(self,code,typ,n):
  self.send_response(code);self.send_header('Content-Type',typ);self.send_header('Content-Length',str(n))
  self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
  self.send_header('Referrer-Policy','no-referrer')
  self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
 def reply(self,code,value):
  b=json.dumps(value,ensure_ascii=False).encode();self.headers_out(code,'application/json; charset=utf-8',len(b));self.end_headers();self.wfile.write(b)
 def cookie(self):return self.headers.get('Cookie','')[:8192]
 def authorized(self):
  token=os.environ.get('FRAME_WORKER_TOKEN','')
  return self.headers.get('Host')=='127.0.0.1:'+str(opt.port) and bool(token) and hmac.compare_digest(self.headers.get('X-Frame-Worker-Token',''),token)
 def csrf(self):return hmac.new(KEY,self.cookie().encode(),hashlib.sha256).hexdigest()
 def do_GET(self):
  path=unquote(urlsplit(self.path).path)
  if path==PREFIX+'/health':return self.reply(200,{'status':'ok','engine':'FilmCraft 0.20.1','auth':'private-worker'})
  if path==PREFIX+'/app.css':return self.send_file(ROOT/'app.css')
  if not self.authorized():return self.reply(401,{'error':'Нужен вход Frame'})
  if pc_input(self,DATA,PREFIX):return
  if path.startswith(PREFIX+'/api/pc-result/')and receive_pc(self,DATA,PREFIX,capacity):return
  if path==PREFIX+'/api/state':
   s=state_payload();s['csrf']=self.csrf();return self.reply(200,s)
  if path==PREFIX+'/api/jobs':pc_renderer.enrich();enrich_pc_jobs();return self.reply(200,{'jobs':[j for j in jobs.values() if j.get('project')==engine.path.name][-10:]})
  match=re.fullmatch(re.escape(PREFIX)+r'/api/object-download/([a-f0-9]{32})',path)
  if match:
   try:signed=original_url(match[1])
   except ValueError:return self.reply(404,{'error':'Файл не найден'})
   self.send_response(302);self.send_header('Location',signed['url']);self.send_header('Content-Length','0');self.send_header('Cache-Control','no-store');self.end_headers();return
  if path.startswith(PREFIX+'/source/'):
   ident=path.rsplit('/',1)[-1]
   found=next((m for m in media_list(engine.path,DATA,PREFIX)if str(m['item'])==ident),None)
   if not found:return self.reply(404,{'error':'Источник не найден'})
   return self.send_file(Path(found['path']))
  if path.startswith(PREFIX+'/files/'):
   rel=path.removeprefix(PREFIX+'/files/');p=(DATA/rel).resolve()
   if not p.is_relative_to(DATA) or not p.is_file() or p.suffix.lower() not in ['.mp4','.mov','.mkv','.webm','.png','.jpg','.jpeg','.fcproj','.wav','.mp3','.flac','.srt','.zip','.cube']:return self.reply(404,{'error':'Файл не найден'})
   return self.send_file(p,download=p.suffix=='.fcproj')
  assets={'/':'app.html','/app.js':'app.js','/app.css':'app.css'}
  relative=path.removeprefix(PREFIX)
  if relative in assets:return self.send_file(ROOT/assets[relative])
  self.reply(404,{'error':'Не найдено'})
 def send_file(self,p,download=False):
  size=p.stat().st_size;start=0;end=size-1;status=200
  r=self.headers.get('Range','')
  if r:
   m=re.fullmatch(r'bytes=(\d+)-(\d*)',r)
   if not m:return self.reply(416,{'error':'Недопустимый диапазон'})
   start=int(m[1]);end=min(end,int(m[2])) if m[2] else end
   if start> end:return self.reply(416,{'error':'Диапазон вне файла'})
   status=206
  self.headers_out(status,mimetypes.guess_type(str(p))[0] or 'application/octet-stream',end-start+1)
  self.send_header('Accept-Ranges','bytes')
  if status==206:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
  if download:self.send_header('Content-Disposition','attachment; filename="frame-project.fcproj"')
  self.end_headers()
  with p.open('rb') as f:
   f.seek(start);left=end-start+1
   while left:
    b=f.read(min(left,65536))
    if not b:break
    self.wfile.write(b);left-=len(b)
 def do_POST(self):
  try:
   if not self.authorized():return self.reply(401,{'error':'Нужен вход владельца'})
   if receive_pc_object(self,DATA,PREFIX):return
   if receive_pc(self,DATA,PREFIX,capacity):return
   if self.headers.get('Origin') not in [ORIGIN]:return self.reply(403,{'error':'Недопустимый источник запроса'})
   if not hmac.compare_digest(self.headers.get('X-Frame-CSRF',''),self.csrf()):return self.reply(403,{'error':'Обнови страницу'})
   path=urlsplit(self.path).path
   if update_prepared and path!=PREFIX+'/api/action':self.close_connection=True;return self.reply(409,{'error':'Применяется обновление'})
   size=int(self.headers.get('Content-Length','0'))
   if path==PREFIX+'/api/upload':
    if size<=0 or size>MAX_UPLOAD:return self.reply(413,{'error':'Первый этап: файл до 64 МиБ'})
    name=Path(unquote(self.headers.get('X-File-Name','media.mp4'))).name
    ext=Path(name).suffix.lower()
    if ext not in ['.mp4','.mov','.mkv','.webm','.wav','.mp3','.flac','.png','.jpg','.jpeg']:raise ValueError('Формат файла не поддержан')
    with manager_lock:
     if any(j['status']=='running'and not nonblocking(j)for j in jobs.values()):raise ValueError('Дождись рендера')
     capacity(size+1000000);p=DATA/'uploads'/(uuid.uuid4().hex[:10]+'-'+re.sub(r'[^a-zA-Z0-9а-яА-Я._-]','_',name))
     try:
      with p.open('xb') as f:
       left=size
       while left:
        b=self.rfile.read(min(left,65536))
        if not b:raise ValueError('Загрузка прервана')
        f.write(b);left-=len(b)
      probe=subprocess.run([str(FC),'probe',str(p)],capture_output=True,text=True,encoding='utf-8',timeout=30)
      if probe.returncode:raise ValueError('FilmCraft не смог прочитать этот файл')
      result=engine.command('file.import',{'paths':[str(p)]})
      if result.get('errors'):raise ValueError(str(result['errors'])[:300])
      refresh();derive(engine.path,DATA,PREFIX);return self.reply(200,state_payload())
     except Exception:
      # No deletion of owner uploads: retain failed file and count it in spool.
      raise
   match=re.fullmatch(re.escape(PREFIX)+r'/api/object-part/([a-f0-9]{32})/(\d{1,4})',path)
   if match:
    if not 0<size<=8*1024**2:raise ValueError('Часть загрузки превышает8МиБ')
    from objects import call
    return self.reply(200,call('part',body=self.rfile.read(size),headers={'X-Object-Id':match[1],'X-Part-Number':match[2],'X-Part-SHA256':self.headers.get('X-Part-SHA256','')}))
   if size>2*1024**2:return self.reply(413,{'error':'Слишком большой запрос'})
   d=json.loads(self.rfile.read(size) or b'{}')
   if path==PREFIX+'/api/action':return self.reply(200,mutate(d['action'],d))
   if path==PREFIX+'/api/render':return self.reply(202,start_export(bool(d.get('preview',False)),d))
   if path==PREFIX+'/api/frame':
    global frame
    with manager_lock:
     if any(j['status']=='running'and not nonblocking(j)for j in jobs.values()):raise ValueError('Дождись рендера')
     seconds=finite(d.get('seconds',0),0,7200)
     p=DATA/'renders'/'current.png';render_png(seconds,p)
     frame={'url':PREFIX+'/files/renders/current.png?v='+str(revision)+'&t='+str(seconds),'revision':revision}
     return self.reply(200,frame)
   self.reply(404,{'error':'Не найдено'})
  except (BrokenPipeError,ConnectionResetError):pass
  except Exception as e:self.close_connection=True;self.reply(400,{'error':str(e)[:500]})
 def handle(self):
  try:super().handle()
  except (BrokenPipeError,ConnectionResetError):pass
httpd=ThreadingHTTPServer(('127.0.0.1',opt.port),Handler);httpd.daemon_threads=True
def stop(*_):
 engine.close();os._exit(0)
signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
httpd.serve_forever()

