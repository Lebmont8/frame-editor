"""Frame local STT. No web calls/downloads; no arbitrary commands."""
import sys,json,base64,zlib,io,os,re,time,wave
from pathlib import Path
def emit(value):
 print('FRAME_RESULT:'+base64.b64encode(zlib.compress(json.dumps(value,ensure_ascii=False).encode(),9)).decode(),flush=True)
try:
 p=Path(sys.argv[1]).resolve();root=Path.home()/'.openclaw'/'tmp'
 if not p.is_relative_to(root)or p.stat().st_size>22000000:raise ValueError('Input must be a bounded native transfer')
 job=json.loads(p.read_text(encoding='utf-8'))
 if not re.fullmatch('[a-f0-9]{32}',job.get('id',''))or job.get('kind')!='transcribe':raise ValueError('Unsupported local job')
 audio=base64.b64decode(job['audio'],validate=True)
 if job.get('encoding')!='wav-zlib':raise ValueError('Expected compressed PCM WAV')
 audio=zlib.decompress(audio,bufsize=20000000)
 if len(audio)>20000000:raise ValueError('Audio input too large')
 from faster_whisper import WhisperModel
 cache=Path.home()/'.cache'/'huggingface'/'hub'/'models--Systran--faster-whisper-small'/'snapshots'
 paths=[q for q in cache.glob('*')if(q/'model.bin').is_file()]
 if not paths:raise ValueError('Local Whisper small cache is not complete; no download attempted')
 model=WhisperModel(str(paths[0]),device='cpu',compute_type='int8',cpu_threads=4,num_workers=1,local_files_only=True)
 import numpy as np
 with wave.open(io.BytesIO(audio),'rb')as wav:
  if wav.getnchannels()!=1 or wav.getframerate()!=16000 or wav.getsampwidth()!=2:raise ValueError('Expected mono 16k PCM16')
  samples=np.frombuffer(wav.readframes(16000*601),dtype=np.int16).astype(np.float32)/32768.0
 segments,info=model.transcribe(samples,beam_size=5,word_timestamps=True,vad_filter=True,condition_on_previous_text=False)
 words=[];text=[]
 for s in segments:
  if s.end>601:raise ValueError('Maximum 10 minutes')
  text.append(s.text)
  for w in s.words or []:words.append({'start':round(w.start,3),'end':round(w.end,3),'text':w.word.strip(),'type':'word'})
 if not words:raise ValueError('No recognised speech')
 emit({'ok':True,'output':{'text':' '.join(text).strip(),'language_code':info.language,'words':words},'meta':{'model':'faster-whisper-small','device':'cpu/int8','localOnly':True}})
except Exception as e:emit({'ok':False,'error':str(e)[:300]});sys.exit(1)
