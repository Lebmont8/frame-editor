from public_prompts import required_prompt as _prompt
"""Full audio coverage and reviewed multilingual tracks; Asya remains the editor/translator."""
import json,time,math,base64,zlib,subprocess,hashlib
from pathlib import Path
from bridge import Mailbox
from providers import ProviderError,write_private
LANG={'en':'English','es':'Spanish','zh':'Chinese (Mandarin, Simplified)','pt':'Portuguese','de':'German'}
SCHEMA={'type':'object','properties':{'segments':{'type':'array','maxItems':80,'items':{'type':'object','properties':{'start':{'type':'number'},'end':{'type':'number'},'text':{'type':'string'}},'required':['start','end','text'],'additionalProperties':False}}},'required':['segments'],'additionalProperties':False}
def cancelled(j):
 if j.get('cancelRequested'):raise ProviderError('Задание отменено; готовые части сохранены, результат не применяется.')
def remote_progress(data,j,ident):
 j['remoteId']=ident
 if j.get('cancelRequested'):write_private(Path(data)/'bridge'/(ident+'.cancel'),{'at':time.time()})
def sound_analysis(data,source,segments,duration,j,persist):
 allnotes=[];total=math.ceil(duration/30);j.update(total=total,progress=0,phase='audioListening');persist()
 for start in range(0,total,8):
  cancelled(j);clips=[]
  for i in range(start,min(total,start+8)):
   at=i*30;end=min(duration,at+30);r=subprocess.run(['ffmpeg','-v','error','-threads','1','-ss',str(at),'-i',str(source),'-t',str(end-at),'-vn','-ac','1','-ar','16000','-c:a','pcm_s16le','-f','wav','-'],capture_output=True,timeout=120)
   if r.returncode:raise ValueError('Не удалось подготовить звук для оценки исполнения')
   text=' '.join(s['text']for s in segments if s['end']>at and s['start']<end)
   clips.append({'start':at,'end':end,'text':text[:1600],'audio':base64.b64encode(zlib.compress(r.stdout,6)).decode()})
  payload={'kind':'perceive','account':Path(data).name,'extension':'wav','clips':clips}
  result=Mailbox(data).request(payload,timeout=3600,on_created=lambda id:remote_progress(data,j,id))['output'];cancelled(j)
  notes=result.get('notes',[])
  if len(notes)!=len(clips)or any(float(n['start'])!=c['start']or float(n['end'])!=c['end']for n,c in zip(notes,clips)):raise ValueError('Аудионаблюдения не совпали с предоставленными фрагментами')
  allnotes.extend(notes);j['progress']=min(total,start+8);persist()
 return {'notes':allnotes,'coverageSeconds':sum(n['end']-n['start']for n in allnotes),'model':'Local Qwen2-Audio-7B-Instruct NF4','evidence':'Actual audio supplied in <=30s contiguous windows; subjective model observations, not proven stress labels'}
def languages(raw):
 if not isinstance(raw,list)or not 1<=len(raw)<=5 or len(set(raw))!=len(raw)or any(x not in LANG for x in raw):raise ValueError('Выбери от1до5языков: en/es/zh/pt/de')
 return raw
def normalize_segments(raw,duration):
 if not isinstance(raw,list)or not 1<=len(raw)<=10000:raise ValueError('Неверный список перевода')
 rows=[];last=0
 for s in raw:
  a=float(s['start']);b=float(s['end']);text=str(s['text']).strip()
  if not math.isfinite(a+b)or not last-.0001<=a<b<=duration+.0001 or not 1<=len(text)<=1800:raise ValueError('Фразы перевода должны идти без перекрытия и в пределах ролика; до1800символов на фразу')
  rows.append({'start':max(0,a),'end':min(duration,b),'text':text});last=b
 return rows
def translations(provider,data,path,source,chosen,duration,j,persist,read_ai,save_ai,audiofp,fp,srt):
 chosen=languages(chosen);tracks=read_ai(path).get('translations',{}).get('tracks',{})
 if read_ai(path).get('translations',{}).get('audioFingerprint')!=audiofp:tracks={}
 total=len(chosen)*math.ceil(len(source)/80);j.update(total=total,progress=0,phase='translateTracks');persist()
 for language in chosen:
  output=[];metas=[]
  for n in range(0,len(source),80):
   cancelled(j);part=source[n:n+80];prompt='Translate the complete supplied spoken passage into '+LANG[language]+_prompt('audio_workflow.translations.1')+json.dumps(part,ensure_ascii=False)
   out,meta=provider.structured(prompt,SCHEMA);rows=out['segments']
   if len(rows)!=len(part)or any(abs(float(s['start'])-p['start'])>.001 or abs(float(s['end'])-p['end'])>.001 for s,p in zip(rows,part)):raise ValueError('Ася вернула другие таймкоды перевода; результат не применяется')
   output.extend(rows);metas.append(meta);j['progress']+=1;persist()
  output=normalize_segments(output,duration);dest=Path(data)/'renders'/('translation-'+hashlib.sha256((str(path)+language+audiofp+json.dumps(output,sort_keys=True)).encode()).hexdigest()[:24]+'.srt');dest.write_text(srt(output))
  tracks[language]={'language':language,'languageName':LANG[language],'segments':output,'approved':False,'url':'/youtube-hub/frame/files/renders/'+dest.name,'version':hashlib.sha256(json.dumps(output,sort_keys=True).encode()).hexdigest(),'meta':metas}
  state=read_ai(path);state['translations']={'fingerprint':fp,'audioFingerprint':audiofp,'sourceTranscriptHash':hashlib.sha256(json.dumps(source,sort_keys=True).encode()).hexdigest(),'tracks':tracks};save_ai(path,state)
 return tracks

def full_dub(data,prefix,path,state,chosen,source,reference,reftext,duration,j,persist,audiofp,fp):
 chosen=languages(chosen);available=state.get('translations',{})
 if available.get('audioFingerprint')!=audiofp or available.get('sourceTranscriptHash')!=hashlib.sha256(json.dumps(state.get('transcript',{}).get('segments',[]),sort_keys=True).encode()).hexdigest():raise ValueError('Сначала обнови переводы текущего монтажа')
 tracks=[]
 for lang in chosen:
  track=available.get('tracks',{}).get(lang,{})
  if track.get('approved')is not True:raise ValueError('Сначала просмотри и прими перевод: '+LANG[lang])
  tracks.append({'language':lang,'segments':normalize_segments(track['segments'],duration)})
 j.update(total=sum(len(t['segments'])for t in tracks),progress=0,phase='dubFull',snapshotReady=True);persist()
 payload={'kind':'dubFull','account':Path(data).name,'extension':'wav','tracks':tracks,'duration':duration,'voiceConsent':True,'reference':base64.b64encode(Path(reference).read_bytes()).decode(),'refText':reftext}
 result=Mailbox(data).request(payload,timeout=86400,on_created=lambda id:remote_progress(data,j,id))['output'];cancelled(j)
 name=result.get('name','')
 import re
 if not re.fullmatch(r'local-[a-f0-9]{32}\.wav',name):raise ValueError('Некорректная квитанция дубляжа')
 preview=Path(data)/'renders'/name
 if not preview.exists()or hashlib.sha256(preview.read_bytes()).hexdigest()!=result.get('sha256'):raise ValueError('Превью дубляжа не прошло SHA-проверку')
 import wave
 with wave.open(str(preview),'rb')as w:preview_duration=w.getnframes()/w.getframerate()
 regions=result.get('previewRegions',[])
 if regions and(len(regions)!=len(chosen)or len({r['language']for r in regions})!=len(chosen)or any(r['language']not in chosen or not 0<=float(r['start'])<float(r['end'])<=preview_duration+.001 or float(r['end'])-float(r['start'])>20.001 for r in regions)):raise ValueError('Некорректные пробы языковых дорожек')
 out=[]
 for t in result.get('tracks',[]):
  if t.get('language')not in chosen or not re.fullmatch('[a-f0-9]{32}',str(t.get('objectId',''))):raise ValueError('Неизвестная дорожка дубляжа')
  from objects import call
  obj=call('status',{'id':t['objectId']})
  if obj.get('status')!='ready'or obj.get('sha256')!=t.get('sha256')or obj.get('bytes')!=t.get('bytes'):raise ValueError('Полная дорожка не прошла обратную SHA-проверку')
  out.append({**t,'translationVersion':available['tracks'][t['language']].get('version'),'download':prefix+'/api/object-download/'+t['objectId'],'subtitle':available['tracks'][t['language']]['url']})
 if len(out)!=len(chosen):raise ValueError('Получены не все выбранные языки')
 j.update(progress=j['total'],previewOnly=True)
 return {'fingerprint':fp,'audioFingerprint':audiofp,'tracks':out,'preview':prefix+'/files/renders/'+name,'previewRegions':result.get('previewRegions',[]),'timing':result.get('timing'),'model':result.get('model'),'duration':duration,'elapsed':result.get('elapsed')}
