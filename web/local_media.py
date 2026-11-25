"""Account-bound one-use PC result capabilities; no model or auth keys enter the browser."""
import hashlib,hmac,json,re,time,uuid,subprocess,base64,os
from pathlib import Path
from bridge import Mailbox
from providers import ProviderError
MAX_RESULT=32*1024**2
def receive(handler,data,prefix,capacity):
 match=re.fullmatch(re.escape(prefix)+r'/api/pc-result/(cat|code)/([a-f0-9]{32})/(wav|png|mp4)',handler.path)
 if not match:return False
 account,ident,ext=match.groups()
 if Path(data).name!=account:handler.reply(403,{'error':'Wrong account'});return True
 root=Path(data)/'bridge';req=root/(ident+'.request.json')
 try:
  job=json.loads(req.read_text());cap=handler.headers.get('X-Frame-Result-Cap','')
  valid=job.get('kind')in ['generate','render','image','perceive','dubFull'] and job.get('expires',0)>time.time() and not any((root/(ident+s)).exists() for s in ['.closed.json','.cancel'])
  if not valid or not hmac.compare_digest(cap,str(job.get('resultCap','')))or len(cap)!=64:raise ValueError('Result capability rejected')
  if ext!=job['extension']:raise ValueError('Unexpected result type')
  if handler.command=='GET':handler.reply(200,{'ok':True});return True
  if handler.headers.get('X-Frame-Progress')=='1':
   size=int(handler.headers.get('Content-Length','0'))
   if not 0<size<=8192:raise ValueError('Progress too large')
   incoming=json.loads(handler.rfile.read(size));out={'at':time.time()}
   for key in ['phase','frame','frames','elapsed','fps','eta','paused']:
    v=incoming.get(key)
    if isinstance(v,(str,int,float,bool))and len(str(v))<200:out[key]=v
   from providers import write_private
   write_private(root/(ident+'.progress.json'),out)
   try:paused=json.loads((root/(ident+'.pause.json')).read_text()).get('paused')is True
   except (ValueError,OSError):paused=False
   handler.reply(200,{'ok':True,'paused':paused});return True
  size=int(handler.headers.get('Content-Length','0'))
  if not 0<size<=MAX_RESULT or handler.headers.get('Transfer-Encoding'):raise ValueError('Result exceeds 32 MiB')
  digest=handler.headers.get('X-Frame-SHA256','')
  if not re.fullmatch('[a-f0-9]{64}',digest):raise ValueError('Checksum required')
  capacity(size+1_000_000)
  dest=Path(data)/'renders'/('local-'+ident+'.'+ext)
  if dest.exists():raise ValueError('Result already delivered')
  hasher=hashlib.sha256()
  with dest.open('xb')as out:
   while size:
    chunk=handler.rfile.read(min(size,65536))
    if not chunk:raise ValueError('Result upload interrupted')
    out.write(chunk);hasher.update(chunk);size-=len(chunk)
  if not hmac.compare_digest(digest,hasher.hexdigest()):raise ValueError('Result checksum mismatch')
  handler.reply(200,{'ok':True,'name':dest.name,'sha256':digest})
 except Exception as e:handler.reply(400,{'error':str(e)[:150]})
 return True
def generate(data,prefix,operation,prompt='',reference=None,voice=None,seed=42,frames=33):
 if operation not in ['image','video','speech']:raise ValueError('Unknown local operation')
 account=Path(data).name
 if account not in ['cat','code']:raise ValueError('Local delivery requires an isolated live Frame account')
 extension={'image':'png','video':'mp4','speech':'wav'}[operation]
 payload={'kind':'generate','operation':operation,'prompt':str(prompt)[:2000],'seed':int(seed),'frames':int(frames),'extension':extension,'account':account}
 for key,path,limit in [('reference',reference,900000),('voice',voice,2500000)]:
  if path:
   raw=Path(path).read_bytes()
   if len(raw)>limit:raise ValueError('Reference too large')
   payload[key]=base64.b64encode(raw).decode()
 if not 0<=payload['seed']<2**31 or payload['frames']not in [17,33,49]:raise ValueError('Invalid local generation settings')
 result=Mailbox(data).request(payload,timeout=1200)
 out=result['output'];name=out.get('name','')
 if not re.fullmatch(r'local-[a-f0-9]{32}\.'+extension,name):raise ProviderError('Invalid local receipt')
 dest=Path(data)/'renders'/name
 if not dest.is_file()or dest.stat().st_size>MAX_RESULT or hashlib.sha256(dest.read_bytes()).hexdigest()!=out.get('sha256'):raise ProviderError('PC result checksum not confirmed')
 r=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration:stream=codec_type,width,height,sample_rate','-of','json',str(dest)],capture_output=True,text=True,timeout=20)
 if r.returncode:raise ValueError('Generated file cannot be decoded')
 info=json.loads(r.stdout)
 if operation=='speech'and not any(x.get('codec_type')=='audio'for x in info['streams']):raise ValueError('Missing generated speech')
 if operation!='speech'and not any(x.get('codec_type')=='video'for x in info['streams']):raise ValueError('Missing generated picture')
 return dest,{'url':prefix+'/files/renders/'+name,**out,'probe':info,'local':True}


def generate_asya(data,prefix,prompt,identity=None,style=None):
 payload={'kind':'image','prompt':str(prompt)[:5000],'account':Path(data).name,'extension':'png','images':[]}
 for p in [identity,style]:
  if p:
   raw=Path(p).read_bytes()
   if len(raw)>2000000:raise ValueError('Reference too large')
   payload['images'].append(base64.b64encode(raw).decode())
 receipt=Mailbox(data).request(payload,timeout=660)['output'];name=receipt.get('name','')
 if not re.fullmatch(r'local-[a-f0-9]{32}\.png',name):raise ValueError('Invalid Asya image receipt')
 p=Path(data)/'renders'/name
 if not p.exists()or hashlib.sha256(p.read_bytes()).hexdigest()!=receipt.get('sha256'):raise ValueError('Asya image SHA mismatch')
 return p,{'url':prefix+'/files/renders/'+name,**receipt}
