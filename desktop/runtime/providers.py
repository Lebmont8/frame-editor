from public_prompts import required_prompt as _prompt
"""Fixed-host provider clients and per-account encrypted credentials.
No SDK, logging, arbitrary URLs, secret-return routes, automatic POST retries or shared tenant state.
"""
import base64,json,os,secrets,time,re
from pathlib import Path
from urllib.parse import quote
try:import requests
except ImportError:requests=None
try:from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:AESGCM=None
OPENAI='https://api.openai.com/v1'
ELEVEN='https://api.elevenlabs.io/v1'
TEXT_MODEL='gpt-6.1-sol'
IMAGE_MODEL='gpt-image-2.5-sunburst'
class ProviderError(ValueError):pass
def write_private(path,value):
 tmp=path.with_name(path.name+'.new');fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
 with os.fdopen(fd,'w')as f:json.dump(value,f,ensure_ascii=False)
 os.chmod(tmp,0o600);tmp.replace(path)
class Vault:
 def __init__(self,data):self.data=Path(data);self.file=self.data/'providers.enc';self.keyfile=self.data/'providers.key'
 def _key(self,create=False):
  if not self.keyfile.exists():
   if not create:return None
   fd=os.open(self.keyfile,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
   with os.fdopen(fd,'wb')as f:f.write(secrets.token_bytes(32))
  return self.keyfile.read_bytes()
 def read(self):
  if not self.file.exists():return {}
  try:
   raw=self.file.read_bytes();return json.loads(AESGCM(self._key()).decrypt(raw[:12],raw[12:],b'frame-providers-v1'))
  except Exception:raise ProviderError('Не удалось открыть защищённые подключения этого аккаунта')
 def save(self,patch):
  values=self.read()
  for name in ['openai','elevenlabs']:
   v=patch.get(name)
   if v is not None and v!='':
    if not isinstance(v,str)or not 20<=len(v)<=512 or any(ord(c)<33 or ord(c)>126 for c in v):raise ProviderError('Некорректный формат API-ключа')
    values[name]=v
  raw=json.dumps(values).encode();nonce=secrets.token_bytes(12);encrypted=nonce+AESGCM(self._key(True)).encrypt(nonce,raw,b'frame-providers-v1')
  tmp=self.file.with_suffix('.new');fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
  with os.fdopen(fd,'wb')as f:f.write(encrypted)
  tmp.replace(self.file)
 def public(self):
  d=self.read();return {'openai':bool(d.get('openai')),'elevenlabs':bool(d.get('elevenlabs')),'textModel':TEXT_MODEL,'imageModel':IMAGE_MODEL}
class Providers:
 def __init__(self,keys,transport=None):
  self.keys=keys;self.session=transport or requests.Session()
  if hasattr(self.session,'trust_env'):self.session.trust_env=False
  self.calls=0
 def request(self,provider,path,method='POST',payload=None,files=None,data=None,raw=False,timeout=240):
  key=self.keys.get(provider)
  if not key:raise ProviderError('Подключи '+('OpenAI'if provider=='openai'else'ElevenLabs')+' в настройках ИИ этого аккаунта')
  root=OPENAI if provider=='openai'else ELEVEN
  if not path.startswith('/')or '://'in path or '..'in path:raise ProviderError('Некорректный путь провайдера')
  headers={'Authorization':'Bearer '+key}if provider=='openai'else{'xi-api-key':key}
  try:
   self.calls+=1
   r=self.session.request(method,root+path,headers=headers,json=payload,files=files,data=data,timeout=(15,timeout),allow_redirects=False,stream=True)
   if r.status_code<200 or r.status_code>=300:
    code=r.status_code;r.close()
    if code in [401,403]:raise ProviderError('Провайдер отклонил ключ или доступ к функции ('+str(code)+')')
    if code in [402,429]:raise ProviderError('Лимит или недостаток кредитов у провайдера ('+str(code)+'). Автоповтора нет.')
    raise ProviderError('Ошибка API провайдера ('+str(code)+'). Автоповтора нет.')
   chunks=[];size=0
   for b in r.iter_content(65536):
    size+=len(b)
    if size>40*1024**2:raise ProviderError('Ответ провайдера превысил допустимый размер')
    chunks.append(b)
   r.close();body=b''.join(chunks)
   return body if raw else json.loads(body)
  except ProviderError:raise
  except Exception:raise ProviderError('Сбой связи или некорректный ответ провайдера. Автоповтора нет.')
 def structured(self,prompt,schema,images=None,research=False):
  content=[{'type':'input_text','text':prompt}]
  for label,p in images or []:content.extend([{'type':'input_text','text':label},{'type':'input_image','image_url':'data:image/png;base64,'+base64.b64encode(Path(p).read_bytes()).decode(),'detail':'low'}])
  payload={'model':TEXT_MODEL,'reasoning':{'effort':'high'},'store':False,'max_output_tokens':24000,'input':[{'role':'system','content':_prompt('providers.structured.1')},{'role':'user','content':content}],'text':{'format':{'type':'json_schema','name':'frame_result','strict':True,'schema':schema}}}
  if research:payload.update(tools=[{'type':'web_search'}],tool_choice={'type':'web_search'})
  r=self.request('openai','/responses',payload=payload,timeout=600)
  if r.get('status')not in [None,'completed']:raise ProviderError('Модель не завершила ответ. Результат не применён.')
  texts=[];sources=[]
  for output in r.get('output',[]):
   for c in output.get('content',[]):
    if c.get('type')=='refusal':raise ProviderError('Модель отказалась от запроса. Проект не изменён.')
    if c.get('type')=='output_text':
     texts.append(c.get('text',''))
     for a in c.get('annotations',[]):
      u=a.get('url','')
      if a.get('type')=='url_citation'and u.startswith('https://'):sources.append({'url':u,'title':a.get('title','')[:200]})
  try:out=json.loads(''.join(texts))
  except Exception:raise ProviderError('Модель не вернула проверяемый JSON. Проект не изменён.')
  return out,{'model':TEXT_MODEL,'sources':sources[:20],'webSearchUsed':any(x.get('type')=='web_search_call'and x.get('status')=='completed'for x in r.get('output',[])),'usage':r.get('usage',{})}
 def transcribe(self,path):
  with Path(path).open('rb')as f:r=self.request('elevenlabs','/speech-to-text',files={'file':('audio.flac',f,'audio/flac')},data={'model_id':'scribe_v2','timestamps_granularity':'word','tag_audio_events':'true','diarize':'true','num_speakers':'1'},timeout=600)
  return r
 def cover(self,prompt,images):
  opened=[]
  try:
   for p in images:opened.append(Path(p).open('rb'))
   r=self.request('openai','/images/edits',files=[('image[]',('reference-'+str(i)+'.png',f,'image/png'))for i,f in enumerate(opened)],data={'model':IMAGE_MODEL,'prompt':prompt,'size':'1536x864','quality':'medium','output_format':'png','n':'1'},timeout=600)
   try:b=base64.b64decode(r['data'][0]['b64_json'],validate=True)
   except Exception:raise ProviderError('Генератор не вернул изображение')
   if not b.startswith(b'\x89PNG\r\n\x1a\n'):raise ProviderError('Генератор вернул не PNG')
   import struct
   if len(b)>8*1024**2 or struct.unpack('>II',b[16:24])!=(1536,864):raise ProviderError('Генератор вернул неподходящий размер обложки')
   return b
  finally:
   for f in opened:f.close()
 def dub_create(self,path,language):
  if not re.fullmatch('[a-z]{2,3}',language):raise ProviderError('Выбери ISO-код языка, например en, de или es')
  with Path(path).open('rb')as f:r=self.request('elevenlabs','/dubbing',files={'file':('audio.flac',f,'audio/flac')},data={'target_lang':language,'num_speakers':'1','drop_background_audio':'true','disable_voice_cloning':'false','mode':'automatic','name':'Frame private dub'},timeout=180)
  id=r.get('dubbing_id','')
  if not re.fullmatch('[A-Za-z0-9_-]{1,100}',id):raise ProviderError('Провайдер не вернул ID дубляжа')
  return id
 def dub_status(self,id):return self.request('elevenlabs','/dubbing/'+quote(id,safe=''),method='GET')
 def dub_audio(self,id,language):return self.request('elevenlabs','/dubbing/'+quote(id,safe='')+'/audio/'+quote(language,safe=''),method='GET',raw=True)
