"""Per-project workflow settings and derived source previews. No shared tenant state."""
import json,subprocess,uuid,math,os
os.environ["OPENBLAS_NUM_THREADS"]="1"
from pathlib import Path
from urllib.parse import quote

def read_workflow(path):
 try:return json.loads(path.with_suffix('.frame.json').read_text())
 except (OSError,ValueError):return {'roles':{},'approved':{},'notes':[]}
def save_workflow(path,d):
 if not isinstance(d,dict) or len(json.dumps(d))>48000:raise ValueError('Слишком много заметок')
 allowed={'roles','approved','notes','brief','compression','insertPrompt','language','titleIdeas','coverBrief','audioAccepted','audioCandidates','sync','syncAnalysis','reference','coverReference','selectedTitle','exportProfile','protectedRanges'}
 out={k:v for k,v in d.items() if k in allowed}
 if 'audioCandidates'in out:
  candidates=out['audioCandidates']
  if not isinstance(candidates,dict)or len(candidates)>200:raise ValueError('Слишком много аудиовариантов')
  safe={}
  for key,value in candidates.items():
   if not str(key).isdigit()or int(key)<=0 or not isinstance(value,dict)or not isinstance(value.get('item'),int)or value['item']<=0:raise ValueError('Некорректный аудиовариант')
   safe[str(key)]={'item':value['item'],'accepted':value.get('accepted')is True}
  out['audioCandidates']=safe
 if 'notes'in out:
  if not isinstance(out['notes'],list)or len(out['notes'])>200:raise ValueError('Слишком много заметок')
  notes=[]
  for r in out['notes']:
   at=float(r['seconds'])
   if not math.isfinite(at)or not 0<=at<=7200:raise ValueError('Неверное время заметки')
   notes.append({'seconds':at,'text':str(r.get('text',''))[:3000],'removed':r.get('removed')is True})
  out['notes']=notes
 if 'exportProfile'in out:
  p=out['exportProfile']
  if not isinstance(p,dict):raise ValueError('Неверные настройки изображения')
  side=int(p.get('maxSide',0));sharp=float(p.get('sharpness',0))
  if side not in [0,2048,2560,3840]or not math.isfinite(sharp)or not 0<=sharp<=.6:raise ValueError('Неверные настройки изображения')
  device=p.get('renderDevice','pc');codec=p.get('codec','h264')
  if device not in ['pc','server']or codec not in ['h264','hevc']:raise ValueError('Неверный маршрут/кодек рендера')
  out['exportProfile']={'maxSide':side,'sharpness':sharp,'denoise':p.get('denoise')is True,'aiUpscale':p.get('aiUpscale')is True,'renderDevice':device,'codec':codec}
 if 'protectedRanges'in out:
  ranges=out['protectedRanges']
  if not isinstance(ranges,list)or len(ranges)>50:raise ValueError('Слишком много защищённых интервалов')
  clean=[]
  for r in ranges:
   a=float(r['start']);b=float(r['end'])
   if not math.isfinite(a+b)or not 0<=a<b<=7200:raise ValueError('Неверный защищённый интервал')
   clean.append({'start':a,'end':b,'reason':str(r.get('reason',''))[:500]})
  out['protectedRanges']=clean
 p=path.with_suffix('.frame.json');tmp=p.with_suffix('.new');tmp.write_text(json.dumps(out,ensure_ascii=False));tmp.replace(p)
 return out
def media_list(path,data,prefix):
 try:items=json.loads(path.read_text())['project']['items']
 except (OSError,ValueError,KeyError):return []
 result=[]
 for id,item in items.items():
  m=item.get('kind',{}).get('Media')
  if not m:continue
  p=Path(m.get('media',{}).get('File',{}).get('path','')).resolve()
  if not p.is_file():continue
  rel=p.relative_to(data).as_posix()if p.is_relative_to(data)else None;info=m.get('info',{});cache=data/'renders'/('asset-'+str(id)+'-'+str(p.stat().st_mtime_ns))
  thumb=cache.with_suffix('.png');peaks=cache.with_suffix('.json')
  result.append({'item':int(id),'name':item['name'],'type':{'AudioOnly':'Audio','StillImage':'Still'}.get(info.get('kind'),info.get('kind')),'duration':info.get('duration',0),'path':str(p),'url':prefix+'/files/'+quote(rel)if rel else prefix+'/source/'+str(id),'info':info,'thumb':prefix+'/files/'+thumb.relative_to(data).as_posix() if thumb.exists() else None,'peaks':json.loads(peaks.read_text()) if peaks.exists() else []})
 from objects import mapping
 originals=mapping(data)
 for m in result:
  pp=Path(m['path']);original=originals.get(str(pp))
  if original:m['original']=original;m['name']=original['name']
 return result
def derive(path,data,prefix):
 # Called after import, never on GET. Small bounded assets only.
 for a in media_list(path,data,prefix):
  if a['thumb'] or a['peaks']:continue
  src=Path(a['path'])
  cache=data/'renders'/('asset-'+str(a['item'])+'-'+str(src.stat().st_mtime_ns))
  if a['info'].get('video'):
   subprocess.run(['ffmpeg','-v','error','-threads','1','-ss',str(min(3,max(0,a['duration']/254016000000*.25))),'-i',str(src),'-frames:v','1','-vf','scale=240:135:force_original_aspect_ratio=decrease','-y',str(cache.with_suffix('.png'))],capture_output=True,timeout=25)
  if a['info'].get('audio_streams'):
   import numpy as np
   r=subprocess.run(['ffmpeg','-v','error','-threads','1','-i',str(src),'-vn','-t','7200','-ac','1','-ar','1000','-f','f32le','-'],capture_output=True,timeout=40)
   x=np.frombuffer(r.stdout,dtype='<f4')
   if len(x):
    bins=np.array_split(abs(x),min(220,len(x)));p=[float(v.max()) for v in bins];mx=max(p)or 1
    cache.with_suffix('.json').write_text(json.dumps([round(v/mx,3) for v in p]))
def clean_audio(source,target):
 # Conservative speech chain, no voice re-synthesis. User must listen/accept.
 r=subprocess.run(['ffmpeg','-v','error','-threads','1','-i',str(source),'-vn','-t','7200','-af','highpass=f=65,afftdn=nf=-28:tn=1,acompressor=threshold=0.18:ratio=3:attack=8:release=150:makeup=1,loudnorm=I=-16:TP=-1.5:LRA=9','-ar','48000','-ac','1','-c:a','flac'if Path(target).suffix=='.flac'else'pcm_s16le','-y',str(target)],capture_output=True,timeout=1800)
 if r.returncode:raise ValueError('Не удалось обработать звуковую дорожку')
def correlate(video,audio):
 import numpy as np
 def sound(p):
  r=subprocess.run(['ffmpeg','-v','error','-threads','1','-i',str(p),'-t','120','-vn','-ac','1','-ar','2000','-f','f32le','-'],capture_output=True,timeout=60)
  x=np.frombuffer(r.stdout,dtype='<f4')
  if len(x)<2000:raise ValueError('Для синхронизации нужен записанный звук в обоих файлах')
  # 20ms RMS envelope tolerates different microphones and gain.
  x=x[:len(x)//40*40].reshape(-1,40);x=np.sqrt(np.mean(x*x,axis=1));x=np.diff(x)
  return x-x.mean()
 x,y=sound(video),sound(audio);scores=[]
 for lag in range(-500,501):
  start=max(0,lag);ys=max(0,-lag);n=min(len(x)-start,len(y)-ys)
  if n<100:scores.append(-1);continue
  a=x[start:start+n];b=y[ys:ys+n];den=np.linalg.norm(a)*np.linalg.norm(b)
  scores.append(float(np.dot(a,b)/den) if den>1e-9 else -1)
 k=int(np.argmax(scores));best=scores[k];other=max([s for i,s in enumerate(scores) if abs(i-k)>25],default=0)
 if best<.25 or best-max(other,0)<.04:raise ValueError('Надёжное совпадение не найдено. Укажи сдвиг вручную; поиск ограничен ±10 с и первыми 120 с.')
 return {'seconds':(k-500)/50,'score':round(best,3),'method':'RMS envelope correlation, 20ms; first 120s; ±10s'}

