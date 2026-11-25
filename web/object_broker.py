#!/usr/bin/python3
"""Fixed Frame object namespace; root-held S3 credentials never enter account workers."""
import fcntl
import os,json,time,uuid,re,pwd,socket,struct,threading,hashlib,configparser,http.server,socketserver,math
from pathlib import Path
import boto3
from botocore.config import Config
ROOT=Path(os.environ.get('FRAME_ROOT',str(Path(__file__).resolve().parent)));CAT=ROOT/'object-catalog';SOCKET=os.environ.get('FRAME_OBJECT_SOCKET','/run/frame-objects/broker.sock');PART=8*1024**2;MAX=10*1024**3
LOCKS={};SEM=threading.BoundedSemaphore(2)
def atomic(p,v):
 p.parent.mkdir(parents=True,exist_ok=True,mode=0o700);t=p.with_suffix('.new');t.write_text(json.dumps(v,ensure_ascii=False));t.chmod(0o600);os.replace(t,p)
def client():
 region=os.environ["AWS_DEFAULT_REGION"]
 s=boto3.client("s3",endpoint_url=os.environ["FRAME_S3_ENDPOINT"],region_name=region,config=Config(signature_version="s3v4",retries={"max_attempts":2,"mode":"standard"},connect_timeout=15,read_timeout=90))
 return s,os.environ["FRAME_S3_BUCKET"]
S3=None;BUCKET=None
def desktop_release(platform):
 if platform not in ['windows','mac']:raise ValueError('Unknown release platform')
 v=json.loads(Path(os.environ['FRAME_RELEASE_INDEX']).read_text())[platform]
 if not v['key'].startswith('frame/desktop/releases/')or not re.fullmatch('[a-f0-9]{64}',v['sha256']):raise ValueError('Invalid release index')
 return {'url':S3.generate_presigned_url('get_object',Params={'Bucket':BUCKET,'Key':v['key'],'ResponseContentDisposition':'attachment; filename="'+v['name']+'"'},ExpiresIn=300),'bytes':v['bytes'],'sha256':v['sha256']}
class Store:
 def __init__(self,account):
  if account not in list(json.loads(os.environ.get('FRAME_ACCOUNT_UIDS','{}')).values()):raise ValueError('Unknown principal')
  self.account=account;self.root=CAT/account;self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
 def path(self,id):
  if not re.fullmatch('[a-f0-9]{32}',str(id)):raise ValueError('Invalid object id')
  return self.root/(id+'.json')
 def read(self,id):
  p=self.path(id);return json.loads(p.read_text())
 def save(self,v):atomic(self.path(v['id']),v)
 def public(self,v):return {k:v.get(k)for k in ['id','name','bytes','status','uploaded','verified','sha256','error','created','partBytes','role','lastModified']}
 def init(self,d):
  size=int(d.get('bytes',0));name=str(d.get('name',''));ext=Path(name).suffix.lower()
  if not 0<size<=MAX or ext not in ['.mp4','.mov','.mkv','.webm','.wav','.mp3','.flac','.png','.jpg','.jpeg','.cube']:raise ValueError('One source must be <=10GiB, supported media only')
  if ext=='.cube'and size>1000000:raise ValueError('LUT exceeds1MB')
  expected=d.get('expectedSHA256')
  if expected and re.fullmatch('[a-f0-9]{64}',str(expected)):
   for p in self.root.glob('*.json'):
    old=json.loads(p.read_text())
    if old.get('status')=='ready'and old.get('sha256')==expected and old.get('bytes')==size:return self.public(old)
  if sum(json.loads(p.read_text()).get('bytes',0)for p in self.root.glob('*.json'))+size>100*1024**3:raise ValueError('Account object budget100GiB reached')
  id=uuid.uuid4().hex;key='frame/v1/'+self.account+'/'+id+ext
  upload=S3.create_multipart_upload(Bucket=BUCKET,Key=key,ContentType='application/octet-stream',Metadata={'frame-account':self.account})
  v={'id':id,'key':key,'uploadId':upload['UploadId'],'name':name[:240],'bytes':size,'status':'uploading','parts':[],'uploaded':0,'created':time.time(),'partBytes':PART,'role':str(d.get('role','video'))[:40],'lastModified':d.get('lastModified'),'expectedSHA256':expected};self.save(v);return self.public(v)
 def part(self,id,n,raw,digest):
  lock=LOCKS.setdefault(self.account+id,threading.Lock())
  with lock:
   v=self.read(id);n=int(n)
   if v['status']!='uploading'or not 1<=n<=math.ceil(v['bytes']/PART):raise ValueError('Invalid upload state/part')
   expected=min(PART,v['bytes']-(n-1)*PART)
   if len(raw)!=expected or hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('Upload part checksum/size mismatch')
   if n<=len(v['parts']):
    if v['parts'][n-1]['sha256']!=digest:raise ValueError('Previously uploaded part differs; original upload retained')
    return {'ok':True,'uploaded':v['uploaded'],'part':n,'already':True}
   if n!=len(v['parts'])+1:raise ValueError('Parts must arrive in order')
   r=S3.upload_part(Bucket=BUCKET,Key=v['key'],UploadId=v['uploadId'],PartNumber=n,Body=raw)
   v['parts'].append({'PartNumber':n,'ETag':r['ETag'],'sha256':digest,'bytes':len(raw)});v['uploaded']+=len(raw);self.save(v);return {'ok':True,'uploaded':v['uploaded'],'part':n}
 def part_url(self,id,n):
  v=self.read(id);n=int(n)
  if v['status']!='uploading'or not 1<=n<=math.ceil(v['bytes']/PART):raise ValueError('Invalid part')
  return {'url':S3.generate_presigned_url('upload_part',Params={'Bucket':BUCKET,'Key':v['key'],'UploadId':v['uploadId'],'PartNumber':n},ExpiresIn=1800)}
 def part_done(self,id,n,d):
  with LOCKS.setdefault(self.account+id,threading.Lock()):
   v=self.read(id);n=int(n)
   if v['status']!='uploading'or n!=len(v['parts'])+1:raise ValueError('Part order/state rejected')
   size=int(d['bytes']);etag=str(d['etag']);sha=str(d['sha256'])
   if size!=min(PART,v['bytes']-(n-1)*PART)or not re.fullmatch('[a-f0-9]{64}',sha)or not re.fullmatch(r'"[a-fA-F0-9]{32}"',etag):raise ValueError('Part receipt rejected')
   v['parts'].append({'PartNumber':n,'ETag':etag,'sha256':sha,'bytes':size});v['uploaded']+=size;self.save(v);return {'ok':True,'uploaded':v['uploaded']}
 def complete(self,id):
  with LOCKS.setdefault(self.account+id,threading.Lock()):
   v=self.read(id)
   if v['status']in ['verifying','ready']:return self.public(v)
   if v['status']!='uploading'or v['uploaded']!=v['bytes']:raise ValueError('Upload incomplete')
   S3.complete_multipart_upload(Bucket=BUCKET,Key=v['key'],UploadId=v['uploadId'],MultipartUpload={'Parts':[{k:p[k]for k in ['PartNumber','ETag']}for p in v['parts']]})
   v['status']='verifying';v['verified']=0;self.save(v)
  threading.Thread(target=self.verify,args=(id,),daemon=True).start();return self.public(v)
 def verify(self,id):
  with SEM:
   v=self.read(id)
   try:
    body=S3.get_object(Bucket=BUCKET,Key=v['key'])['Body'];whole=hashlib.sha256();count=0
    try:
     for part in v['parts']:
      h=hashlib.sha256();left=part['bytes']
      while left:
       b=body.read(min(left,1024**2))
       if not b:raise ValueError('Reverse read incomplete')
       left-=len(b);count+=len(b);whole.update(b);h.update(b)
      if h.hexdigest()!=part['sha256']:raise ValueError('Reverse SHA mismatch')
      v['verified']=count;self.save(v)
     if body.read(1)or count!=v['bytes']:raise ValueError('Reverse size mismatch')
    finally:body.close()
    if v.get('expectedSHA256')and whole.hexdigest()!=v['expectedSHA256']:raise ValueError('Declared full SHA mismatch')
    v.update(status='ready',sha256=whole.hexdigest(),finished=time.time())
   except Exception:v.update(status='error',error='Object reverse verification failed; original object retained, never refetched')
   self.save(v)
 def sign(self,id):
  v=self.read(id)
  if v['status']!='ready':raise ValueError('Original not verified')
  return {'url':S3.generate_presigned_url('get_object',Params={'Bucket':BUCKET,'Key':v['key'],'ResponseContentDisposition':"attachment; filename*=UTF-8''"+__import__('urllib.parse',fromlist=['quote']).quote(v['name'],safe='')},ExpiresIn=21600),'bytes':v['bytes'],'sha256':v['sha256'],'name':v['name'],'id':id}
class Server(socketserver.ThreadingMixIn,socketserver.UnixStreamServer):
 daemon_threads=True;slots=threading.BoundedSemaphore(4)
 def process_request(self,request,client_address):
  if not self.slots.acquire(False):self.shutdown_request(request);return
  try:super().process_request(request,client_address)
  except Exception:self.slots.release();raise
 def process_request_thread(self,request,client_address):
  try:super().process_request_thread(request,client_address)
  finally:self.slots.release()
class Handler(http.server.BaseHTTPRequestHandler):
 def log_message(self,*_):pass
 def reply(self,n,v):
  b=json.dumps(v,ensure_ascii=False).encode();self.send_response(n);self.send_header('Content-Length',str(len(b)));self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(b)
 def do_POST(self):
  try:
   _,uid,_=struct.unpack('3i',self.connection.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12));allowed={int(k):v for k,v in json.loads(os.environ['FRAME_ACCOUNT_UIDS']).items()}
   account=allowed.get(uid)
   if uid==0:account=self.headers.get('X-Frame-Account')
   if account not in list(json.loads(os.environ.get('FRAME_ACCOUNT_UIDS','{}')).values()):return self.reply(403,{'error':'Principal rejected'})
   store=Store(account);size=int(self.headers.get('Content-Length',0))
   if not 0<=size<=PART:raise ValueError('Request too large')
   if self.path=='/part':
    raw=self.rfile.read(size)
    out=store.part(self.headers.get('X-Object-Id'),self.headers.get('X-Part-Number'),raw,self.headers.get('X-Part-SHA256'))
   else:
    if size>65536:raise ValueError('Request too large')
    d=json.loads(self.rfile.read(size)or b'{}');id=d.get('id')
    if self.path=='/release':out=desktop_release(d.get('platform'))
    elif self.path=='/init':out=store.init(d)
    elif self.path=='/status':out=store.public(store.read(id))
    elif self.path=='/complete':out=store.complete(id)
    elif self.path=='/sign':out=store.sign(id)
    elif self.path=='/part-url':out=store.part_url(id,d['part'])
    elif self.path=='/part-done':out=store.part_done(id,d['part'],d)
    else:return self.reply(404,{'error':'Unknown operation'})
   self.reply(200,out)
  except (ValueError,KeyError,FileNotFoundError):self.reply(400,{'error':'Invalid object request or state'})
  except Exception:self.reply(503,{'error':'Object Storage unavailable; originals retained'})
if __name__=='__main__':
 lock=open('/run/frame-objects/broker.lock','a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 S3,BUCKET=client();CAT.mkdir(exist_ok=True,mode=0o700)
 if Path(SOCKET).exists():Path(SOCKET).unlink() # This service owns only its fixed stale socket.
 s=Server(SOCKET,Handler);os.chmod(SOCKET,0o666)
 # Resume reverse verification only, never another PUT or source acquisition.
 for a in list(json.loads(os.environ.get('FRAME_ACCOUNT_UIDS','{}')).values()):
  store=Store(a)
  for p in store.root.glob('*.json'):
   v=json.loads(p.read_text())
   if v.get('status')=='verifying':threading.Thread(target=store.verify,args=(v['id'],),daemon=True).start()
 s.serve_forever()
