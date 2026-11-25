"""Measured sound cues and multi-anchor clock drift; no claim that text is audio."""
import json,subprocess,math
from pathlib import Path
import numpy as np

def pcm(path,start=0,length=30,rate=2000):
 r=subprocess.run(['ffmpeg','-v','error','-threads','1','-ss',str(max(0,start)),'-i',str(path),'-t',str(length),'-vn','-ac','1','-ar',str(rate),'-f','f32le','-'],capture_output=True,timeout=120)
 if r.returncode:raise ValueError('Не удалось декодировать звук')
 return np.frombuffer(r.stdout,dtype='<f4').copy()
def duration(path):
 r=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','json',str(path)],capture_output=True,text=True,encoding='utf-8',timeout=30)
 return float(json.loads(r.stdout)['format']['duration'])
def envelope(x):
 x=x[:len(x)//40*40].reshape(-1,40);y=np.sqrt(np.mean(x*x,axis=1));y=np.convolve(y,[.25,.5,.25],mode='same');y-=np.convolve(y,np.ones(51)/51,mode='same');return y-y.mean()
def align(x,y,search=10):
 x=envelope(x);y=envelope(y);scores=[];bound=round(search*50)
 for lag in range(-bound,bound+1):
  a=max(0,lag);b=max(0,-lag);n=min(len(x)-a,len(y)-b)
  if n<100:scores.append(-1);continue
  v=x[a:a+n];w=y[b:b+n];den=np.linalg.norm(v)*np.linalg.norm(w);scores.append(float(v@w/den)if den>1e-8 else -1)
 ix=int(np.argmax(scores));s=scores[ix];other=max([v for j,v in enumerate(scores)if abs(j-ix)>25],default=0)
 sub=0.
 if 0<ix<len(scores)-1:
  den=scores[ix-1]-2*scores[ix]+scores[ix+1]
  if abs(den)>1e-9:sub=max(-.5,min(.5,.5*(scores[ix-1]-scores[ix+1])/den))
 return {'seconds':(ix-bound+sub)/50,'score':s,'margin':s-max(0,other)}
def drift(video,audio,base=0):
 vd=duration(video);ad=duration(audio);span=min(vd,ad)
 if span<25:raise ValueError('Для оценки дрейфа нужен фрагмент хотя бы25с; используй обычный сдвиг')
 window=min(30,span*.3);centres=np.linspace(window/2,span-window/2,min(9,max(3,int(span//60)+1)));anchors=[]
 for t in centres:
  start=max(0,float(t)-window/2);astart=max(0,start-float(base));row=align(pcm(video,start,window),pcm(audio,astart,window));row['seconds']+=start-astart;row['at']=float(t)
  if row['score']>=.3 and row['margin']>=.025:anchors.append(row)
 if len(anchors)<3:raise ValueError('Недостаточно надёжных совпадений для дрейфа. Общий звук и ручная проверка обязательны.')
 t=np.array([x['at']for x in anchors]);lag=np.array([x['seconds']for x in anchors]);mask=np.ones(len(t),bool)
 for _ in range(3):
  if mask.sum()<3:raise ValueError('Совпадения не согласуются; автоматическая правка не предложена')
  a,b=np.polyfit(t[mask],lag[mask],1,w=np.array([x['score']for x in anchors])[mask]);res=abs(lag-(a*t+b));mask=res<=max(.06,float(np.median(res))*3)
 if np.ptp(t[mask])<span*.45 or abs(a)>.005 or res[mask].max()>.08:raise ValueError('Дрейф не подтверждён по всей записи; нужна ручная проверка')
 rate=float(1-a);offset=float(b/rate)
 return {'seconds':round(offset,5),'tempo':round(rate,9),'driftPpm':round(float(a)*1e6,2),'endDriftSeconds':round(float(a)*span,3),'duration':span,'anchors':anchors,'acceptedAnchors':int(mask.sum()),'maxResidualSeconds':round(float(res[mask].max()),3),'score':round(float(np.mean([x['score']for x in anchors])),3),'method':'multi-anchor RMS, weighted robust affine clock fit;20ms anchors; pitch-preserving atempo candidate only'}
def cues(path,segments):
 rows=[]
 for s in segments:
  start=float(s['start']);end=float(s['end']);x=pcm(path,start,min(30,end-start),16000)
  if not len(x):continue
  block=x[:len(x)//320*320].reshape(-1,320)
  if not len(block):continue
  rms=np.sqrt(np.mean(block*block,axis=1));threshold=max(.003,float(np.percentile(rms,80))*.15);quiet=rms<threshold;pauses=[];begin=None
  for i,v in enumerate(list(quiet)+[False]):
   if v and begin is None:begin=i
   elif not v and begin is not None:
    if i-begin>=10:pauses.append({'start':round(start+begin*.02,3),'end':round(start+i*.02,3)})
    begin=None
  pitch=[]
  for frame in block[::5]:
   frame=frame-frame.mean()
   if np.sqrt(np.mean(frame*frame))<threshold:continue
   # Autocorrelation only supplies a coarse voicing/pitch cue, not lexical stress truth.
   z=np.correlate(frame,frame,mode='full')[319:];lo,hi=40,250;k=lo+int(np.argmax(z[lo:hi]))
   if z[0]>0 and z[k]/z[0]>.45:pitch.append(16000/k)
  rows.append({'start':start,'end':end,'rmsDbfs':round(float(20*np.log10(max(1e-9,np.sqrt(np.mean(x*x))))),2),'peakDbfs':round(float(20*np.log10(max(1e-9,abs(x).max()))),2),'clippedFraction':round(float(np.mean(abs(x)>=.995)),5),'quietFraction':round(float(quiet.mean()),3),'pauses':pauses,'pitchMedianHz':round(float(np.median(pitch)),1)if pitch else None,'pitchRangeHz':round(float(np.ptp(pitch)),1)if len(pitch)>2 else None})
 return {'segments':rows,'method':'decoded PCM:20ms energy/pause/clip and coarse autocorrelation pitch; NOT lexical-stress verdict'}
