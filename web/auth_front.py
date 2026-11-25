#!/usr/bin/env python3
"""Two fixed Frame accounts; independent auth DBs and isolated FilmCraft workers."""
import argparse,hashlib,hmac,http.client,ipaddress,json,os,re,secrets,sqlite3,threading,time
from pathlib import Path
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit
ROOT=Path(__file__).resolve().parent
P='/youtube-hub/frame';ORIGIN=os.environ['FRAME_ORIGIN']
ap=argparse.ArgumentParser();ap.add_argument('--config',default=str(ROOT/'auth/front.json'));ap.add_argument('--port',type=int,default=58121);opt=ap.parse_args()
CFG=json.loads(Path(opt.config).read_text());KEY=bytes.fromhex(CFG['key'])
AUTH=Path(opt.config).parent
ACCOUNTS=CFG['accounts']
assert ACCOUNTS and all(re.fullmatch(r'[A-Za-z0-9_-]{1,32}', k) and isinstance(a.get('login'),str) for k,a in ACCOUNTS.items())
hash_slots=threading.BoundedSemaphore(2)
def db(key):
 c=sqlite3.connect(AUTH/(key+'.sqlite'),timeout=3);c.row_factory=sqlite3.Row;return c
def hashpass(password,salt):
 return hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=32768,r=8,p=1,dklen=32,maxmem=96*1024**2).hex()
def digest(s):return hashlib.sha256(s.encode()).hexdigest()
def cookies(value):
 try:
  c=SimpleCookie();c.load(value[:8192]);return {k:v.value for k,v in c.items()}
 except Exception:return {}
def setcookie(name,value,maxage=None,samesite='Lax'):
 s=f'{name}={value}; Path={P}/; Secure; HttpOnly; SameSite={samesite}'
 if maxage is not None:s+='; Max-Age='+str(maxage)
 return s
def auth(token):
 if not re.fullmatch('[0-9a-f]{64}',token):return None
 for key,a in ACCOUNTS.items():
  with db(key) as c:r=c.execute('SELECT token,csrf,expires,remember FROM sessions WHERE token=? AND expires>?',(digest(token),int(time.time()))).fetchone()
  if r:return key,a,r
 return None
def rate_status(ip,key):
 now=int(time.time());targets=[('ip:'+digest(ip),12)]
 if key:targets.append(('account:'+key,8))
 with db('abuse') as c:
  c.execute('DELETE FROM attempts WHERE at<?',(now-900,))
  for ident,limit in targets:
   count=c.execute('SELECT COUNT(*) FROM attempts WHERE target=? AND at>?',(ident,now-900)).fetchone()[0]
   if count>=limit:return False
 return True
def failed(ip,key):
 now=int(time.time());targets=['ip:'+digest(ip)]
 if key:targets.append('account:'+key)
 with db('abuse') as c:c.executemany('INSERT INTO attempts(target,at) VALUES(?,?)',[(t,now)for t in targets])
class Server(ThreadingHTTPServer):
 slots=threading.BoundedSemaphore(24)
 request_queue_size=32
 daemon_threads=True
 def process_request(self,req,addr):
  if not self.slots.acquire(False):
   try:req.sendall(b'HTTP/1.1 503 Service Unavailable\r\nContent-Length: 4\r\nConnection: close\r\n\r\nBusy')
   finally:self.shutdown_request(req)
   return
  try:super().process_request(req,addr)
  except BaseException:self.slots.release();raise
 def process_request_thread(self,req,addr):
  try:super().process_request_thread(req,addr)
  finally:self.slots.release()
class H(BaseHTTPRequestHandler):
 server_version='Frame';sys_version=''
 protocol_version='HTTP/1.1'
 def setup(self):super().setup();self.connection.settimeout(45)
 def log_message(self,*a):pass
 def common(self,status,typ,length,cookie_headers=[]):
  self.send_response(status);self.send_header('Content-Type',typ);self.send_header('Content-Length',str(length))
  self.send_header('Cache-Control','no-store, max-age=0');self.send_header('Pragma','no-cache')
  self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','no-referrer')
  self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'; form-action 'self'")
  self.send_header('X-Frame-Options','DENY');self.send_header('Connection','close');self.close_connection=True
  for c in cookie_headers:self.send_header('Set-Cookie',c)
 def reply(self,status,data,cookie_headers=[]):
  b=json.dumps(data,ensure_ascii=False).encode();self.common(status,'application/json; charset=utf-8',len(b),cookie_headers);self.end_headers();self.wfile.write(b)
 def static(self,name,cookie_headers=[]):
  b=(ROOT/name).read_bytes();typ='text/css'if name.endswith('.css')else'application/javascript'if name.endswith('.js')else'text/html'
  self.common(200,typ+'; charset=utf-8',len(b),cookie_headers);self.end_headers();self.wfile.write(b)
 def who(self):return auth(cookies(self.headers.get('Cookie','')).get('frame_session',''))
 def ip(self):
  try:return str(ipaddress.ip_address(self.headers.get('CF-Connecting-IP',self.client_address[0])))
  except ValueError:return self.client_address[0]
 def body(self,limit=4096):
  raw=self.headers.get('Content-Length','0')
  if not re.fullmatch(r'\d{1,10}',raw):raise ValueError()
  n=int(raw)
  if n>limit or self.headers.get('Transfer-Encoding'):raise ValueError()
  b=self.rfile.read(n)
  if len(b)!=n:raise ValueError()
  return json.loads(b or b'{}')
 def do_GET(self):
  try:
   path=urlsplit(self.path).path
   if self.headers.get('Host','').split(':')[0] not in {__import__('urllib.parse',fromlist=['urlsplit']).urlsplit(ORIGIN).hostname,'127.0.0.1','localhost'}:return self.reply(400,{'error':'Недопустимый адрес'})
   match=re.fullmatch(re.escape(P)+r'/api/pc-input/(cat|code)/[a-f0-9]{32}/[a-f0-9]{32}',path)
   if match:
    a=ACCOUNTS[match.group(1)];up=http.client.HTTPConnection('127.0.0.1',a['port'],timeout=60)
    try:
     up.request('GET',path,headers={'X-Frame-Worker-Token':a['workerToken'],'X-Frame-Result-Cap':self.headers.get('X-Frame-Result-Cap',''),'Range':self.headers.get('Range','')})
     r=up.getresponse();self.common(r.status,r.getheader('Content-Type','application/octet-stream'),int(r.getheader('Content-Length','0')));self.end_headers()
     while True:
      b=r.read(65536)
      if not b:break
      self.wfile.write(b)
     return
    finally:up.close()
   if path==P+'/health':return self.reply(200,{'status':'ok','auth':'two-fixed-accounts','engine':'FilmCraft 0.20.1'})
   if path in [P+'/login.js',P+'/app.css']:return self.static('login.js'if path.endswith('.js')else'app.css')
   user=self.who()
   if path in [P,P+'/',P+'/login']:
    if user:return self.proxy(user)
    challenge=secrets.token_hex(24);csrf=hmac.new(KEY,challenge.encode(),hashlib.sha256).hexdigest()
    b=(ROOT/'login.html').read_text().replace('LOGIN_CSRF_VALUE',csrf).encode()
    self.common(200,'text/html; charset=utf-8',len(b),[setcookie('frame_login',challenge,900,'Strict')]);self.end_headers();self.wfile.write(b);return
   if not user:return self.reply(401,{'error':'Войди в аккаунт Frame'})
   self.proxy(user)
  except (BrokenPipeError,ConnectionResetError,TimeoutError):pass
  except Exception:self.reply(503,{'error':'Сервис временно недоступен'})
 def do_POST(self):
  try:
   path=urlsplit(self.path).path
   pc_object=re.fullmatch(re.escape(P)+r'/api/pc-object/(cat|code)/([a-f0-9]{32})/(init|part-url|part-done|complete|status)',path)
   if pc_object:
    a=ACCOUNTS[pc_object[1]];size=int(self.headers.get('Content-Length','0'))
    if not 0<size<=8192:return self.reply(413,{'error':'PC object request too large'})
    up=http.client.HTTPConnection('127.0.0.1',a['port'],timeout=45)
    try:
     headers={'X-Frame-Worker-Token':a['workerToken'],'X-Frame-Result-Cap':self.headers.get('X-Frame-Result-Cap','')}
     up.request('GET',P+'/api/pc-result/'+pc_object[1]+'/'+pc_object[2]+'/wav',headers=headers);r=up.getresponse();r.read(8192)
     if r.status!=200:return self.reply(403,{'error':'Invalid PC object capability'})
     body=self.rfile.read(size);headers.update({'Content-Type':'application/json','Content-Length':str(size)});up.request('POST',path,body=body,headers=headers);r=up.getresponse();raw=r.read(65536);self.common(r.status,'application/json',len(raw));self.end_headers();self.wfile.write(raw);return
    finally:up.close()
   match=re.fullmatch(re.escape(P)+r'/api/pc-result/(cat|code)/[a-f0-9]{32}/(wav|png|mp4)',path)
   if match:
    a=ACCOUNTS[match.group(1)];size=int(self.headers.get('Content-Length','0'))
    if not 0<size<=32*1024**2 or self.headers.get('Transfer-Encoding'):return self.reply(413,{'error':'Result too large'})
    up=http.client.HTTPConnection('127.0.0.1',a['port'],timeout=90)
    try:
     verify=http.client.HTTPConnection('127.0.0.1',a['port'],timeout=10)
     try:
      verify.request('GET',path,headers={'X-Frame-Worker-Token':a['workerToken'],'X-Frame-Result-Cap':self.headers.get('X-Frame-Result-Cap','')})
      checked=verify.getresponse();checked.read(4096)
      if checked.status!=200:return self.reply(403,{'error':'Invalid result capability'})
     finally:verify.close()
     headers={'X-Frame-Worker-Token':a['workerToken'],'X-Frame-Result-Cap':self.headers.get('X-Frame-Result-Cap',''),'X-Frame-SHA256':self.headers.get('X-Frame-SHA256',''),'X-Frame-Progress':self.headers.get('X-Frame-Progress',''),'Content-Length':str(size)}
     # The worker validates the capability before consuming the body.
     up.putrequest('POST',path)
     for k,v in headers.items():up.putheader(k,v)
     up.endheaders()
     left=size
     while left:
      chunk=self.rfile.read(min(left,65536))
      if not chunk:raise ValueError('Interrupted result')
      up.send(chunk);left-=len(chunk)
     r=up.getresponse();raw=r.read(4096)
     self.common(r.status,'application/json',len(raw));self.end_headers();self.wfile.write(raw);return
    finally:up.close()
   if self.headers.get('Origin')!=ORIGIN:return self.reply(403,{'error':'Недопустимый источник запроса'})
   path=urlsplit(self.path).path
   if path==P+'/login':
    values=self.body()
    challenge=cookies(self.headers.get('Cookie','')).get('frame_login','')
    expected=hmac.new(KEY,challenge.encode(),hashlib.sha256).hexdigest()
    if not re.fullmatch('[0-9a-f]{48}',challenge) or not hmac.compare_digest(str(values.get('csrf','')),expected):return self.reply(403,{'error':'Обнови страницу входа'})
    login=str(values.get('login','')).strip().casefold();password=values.get('password','')
    if not isinstance(password,str)or len(password)>256:return self.reply(400,{'error':'Неверные данные входа'})
    key=next((k for k,a in ACCOUNTS.items()if a['login']==login),None)
    if not rate_status(self.ip(),key):return self.reply(429,{'error':'Слишком много попыток. Повтори через 15 минут.'})
    if not hash_slots.acquire(False):return self.reply(429,{'error':'Подожди несколько секунд и повтори'})
    try:
     with db(key or 'cat') as c:u=c.execute('SELECT salt,password_hash FROM account WHERE id=1').fetchone()
     valid=hmac.compare_digest(hashpass(password,u['salt']),u['password_hash']) and key is not None
    finally:hash_slots.release()
    if not valid:failed(self.ip(),key);return self.reply(403,{'error':'Неверный логин или пароль'})
    token=secrets.token_hex(32);csrf=secrets.token_hex(32);remember=values.get('remember',True) is True;seconds=30*86400 if remember else 12*3600
    with db(key) as c:
     c.execute('DELETE FROM sessions WHERE expires<?',(int(time.time()),))
     c.execute('INSERT INTO sessions(token,csrf,expires,remember) VALUES(?,?,?,?)',(digest(token),csrf,int(time.time())+seconds,int(remember)))
    return self.reply(200,{'ok':True},[setcookie('frame_session',token,seconds if remember else None),setcookie('frame_login','',0,'Strict')])
   user=self.who()
   if not user:return self.reply(401,{'error':'Войди в аккаунт Frame'})
   if path==P+'/logout':
    data=self.body()
    if not hmac.compare_digest(str(data.get('csrf','')),user[2]['csrf']):return self.reply(403,{'error':'Обнови страницу'})
    with db(user[0])as c:c.execute('DELETE FROM sessions WHERE token=?',(user[2]['token'],))
    return self.reply(200,{'ok':True},[setcookie('frame_session','',0)])
   if not path.startswith(P+'/api/desktop/') and path not in [P+'/api/action',P+'/api/render',P+'/api/frame',P+'/api/upload']and not re.fullmatch(re.escape(P)+r'/api/object-part/[a-f0-9]{32}/\d{1,4}',path):return self.reply(404,{'error':'Не найдено'})
   self.proxy(user)
  except (ValueError,KeyError,json.JSONDecodeError):self.reply(400,{'error':'Некорректный запрос'})
  except (BrokenPipeError,ConnectionResetError,TimeoutError):pass
  except Exception:self.reply(503,{'error':'Сервис временно недоступен'})
 def proxy(self,user):
  key,a,session=user;path=urlsplit(self.path).path
  if path in [P,P+'/login']:up_path=P+'/'
  else:up_path=self.path
  if self.command=='GET' and path not in [P,P+'/',P+'/login',P+'/app.js',P+'/api/state',P+'/api/jobs'] and not path.startswith(P+'/api/desktop/')and not path.startswith(P+'/files/')and not re.fullmatch(re.escape(P)+r'/api/object-download/[a-f0-9]{32}',path):return self.reply(404,{'error':'Не найдено'})
  # Only the gateway injects the per-worker token. Never pass a client-supplied one.
  headers={k:self.headers[k]for k in ['Content-Type','Range','X-File-Name','X-Frame-CSRF','Origin','X-Part-SHA256','X-Object-Id','X-Part-Number','X-Part-SHA256']if k in self.headers}
  sid=cookies(self.headers.get('Cookie','')).get('frame_session','')
  headers.update({'Host':__import__('urllib.parse',fromlist=['urlsplit']).urlsplit(ORIGIN).netloc,'Cookie':'frame_session='+sid,'X-Frame-Worker-Token':a['workerToken']})
  upstream=http.client.HTTPConnection('127.0.0.1',a['port'],timeout=60)
  try:
   size=int(self.headers.get('Content-Length','0'))
   if size<0 or size>(64*1024**2 if path.endswith('/api/upload')else 24*1024**2 if path.startswith(P+'/api/desktop/')else 8*1024**2 if '/api/object-part/'in path else 2*1024**2 if path==P+'/api/action'else 65536) or self.headers.get('Transfer-Encoding'):return self.reply(413,{'error':'Слишком большой запрос'})
   if self.command=='POST':headers['Content-Length']=str(size)
   upstream.putrequest(self.command,up_path,skip_host=True)
   for k,v in headers.items():upstream.putheader(k,v)
   upstream.endheaders()
   left=size if self.command=='POST'else 0
   while left:
    chunk=self.rfile.read(min(65536,left))
    if not chunk:raise ValueError()
    upstream.send(chunk);left-=len(chunk)
   r=upstream.getresponse();refresh=[]
   if session['remember'] and session['expires']-time.time()<15*86400:
    with db(key)as c:c.execute('UPDATE sessions SET expires=? WHERE token=?',(int(time.time())+30*86400,session['token']))
    refresh=[setcookie('frame_session',sid,30*86400)]
   if path==P+'/api/state'and r.status==200:
    data=json.loads(r.read(8*1024**2));data['account']=a['login'];data['authCsrf']=session['csrf'];return self.reply(200,data,refresh)
   self.common(r.status,r.getheader('Content-Type','application/octet-stream'),int(r.getheader('Content-Length','0')),refresh)
   for k in ['Content-Range','Accept-Ranges','Content-Disposition','Location']:
    if r.getheader(k):self.send_header(k,r.getheader(k))
   self.end_headers()
   while True:
    chunk=r.read(65536)
    if not chunk:break
    self.wfile.write(chunk)
  finally:upstream.close()
 def handle(self):
  try:super().handle()
  except (BrokenPipeError,ConnectionResetError,TimeoutError):pass
Server(('127.0.0.1',opt.port),H).serve_forever()

