'use strict';
const {app,BrowserWindow,session,ipcMain,dialog,Menu}=require('electron');
const {spawn}=require('node:child_process'),http=require('node:http'),crypto=require('node:crypto'),fs=require('node:fs'),path=require('node:path'),net=require('node:net');
const REMOTE=process.env.FRAME_REMOTE_ORIGIN||'https://frame.example.invalid',PREFIX='/youtube-hub/frame';
const remoteURL=new URL(REMOTE);if(remoteURL.protocol!=='https:'||remoteURL.origin!==REMOTE)throw Error('FRAME_REMOTE_ORIGIN must be an HTTPS origin without credentials or a path');
const {attach:attachUpdater}=require('./updater.cjs');
let updater;
let main,worker,transport,origin,remoteSession,csrf='',quitting=false;
const nativeToken=crypto.randomBytes(32).toString('hex'),workerToken=crypto.randomBytes(32).toString('hex');
if(!app.isPackaged&&process.env.FRAME_TEST_USER_DATA)app.setPath('userData',process.env.FRAME_TEST_USER_DATA);
const root=app.isPackaged?process.resourcesPath:path.resolve(__dirname,'..');
const runtime=path.join(root,'runtime'),vendor=(!app.isPackaged&&process.env.FRAME_DEV_VENDOR)||path.join(root,'vendor'),data=path.join(app.getPath('userData'),'workspaces','local');
function freePort(){return new Promise((resolve,reject)=>{const s=net.createServer();s.once('error',reject);s.listen(0,'127.0.0.1',()=>{const port=s.address().port;s.close(()=>resolve(port))})})}
function secure(win){win.webContents.setWindowOpenHandler(()=>({action:'deny'}));win.webContents.on('will-attach-webview',e=>e.preventDefault())}
async function connected(){const c=await remoteSession.cookies.get({url:REMOTE+PREFIX+'/',name:'frame_session'});return c.length>0}
async function remoteFetch(route,options={}){
 if(!await connected())throw Error('Подключи аккаунт Frame кнопкой «Ася и мой ПК»');
 const url=REMOTE+PREFIX+route;
 if(options.method==='POST'&&!csrf){
  const r=await remoteSession.fetch(REMOTE+PREFIX+'/api/state',{redirect:'error',credentials:'include'});
  if(!r.ok)throw Error('Сеанс Frame истёк. Войди заново.');
  csrf=(await r.json()).csrf;
 }
 const r=await remoteSession.fetch(url,{...options,redirect:options.redirect||'error',credentials:'include',headers:{...options.headers,Origin:REMOTE,...(options.method==='POST'?{'X-Frame-CSRF':csrf}:{})}});
 if(r.status===401||r.status===403)csrf='';
 return r;
}
async function nativeTransport(){
 const s=http.createServer(async(req,res)=>{
  try{
   if(req.headers['x-native-token']!==nativeToken||req.headers.host!=='127.0.0.1:'+s.address().port){res.writeHead(403);return res.end()}
   if(!(/^\/api\/desktop\/(status|jobs\/[a-f0-9]{32}(\/(cancel|close|pause|resume))?|objects\/(init|status|complete|sign|part))$/.test(req.url)||/^\/files\/renders\/local-[a-f0-9]{32}\.(mp4|png|wav)$/.test(req.url)))throw Error('Недопустимый маршрут');
   if(!['GET','POST'].includes(req.method))throw Error('Недопустимая операция');
   let parts=[],size=0;
   for await(const b of req){size+=b.length;if(size>24*1024**2)throw Error('Слишком большой запрос');parts.push(b)}
   const headers={'Content-Type':req.headers['content-type']||'application/json'};
   for(const k of ['x-object-id','x-part-number','x-part-sha256'])if(req.headers[k])headers[k]=req.headers[k];
   const r=await remoteFetch(req.url,{method:req.method,headers,...(req.method==='POST'?{body:Buffer.concat(parts)}:{})});
   res.writeHead(r.status,{'Content-Type':r.headers.get('content-type')||'application/json','Cache-Control':'no-store'});
   if(r.body)for await(const b of r.body){if(!res.write(Buffer.from(b)))await new Promise(resolve=>res.once('drain',resolve))}
   res.end();
  }catch(e){if(!res.headersSent)res.writeHead(503,{'Content-Type':'application/json'});res.end(JSON.stringify({error:e.message}))}
 });
 await new Promise(resolve=>s.listen(0,'127.0.0.1',resolve));transport=s;
 return s.address().port;
}
async function localJSON(route,body){
 const r=await fetch(origin+PREFIX+route,{method:body?'POST':'GET',headers:{'X-Frame-Worker-Token':workerToken,Origin:origin,'Content-Type':'application/json',...(body?{'X-Frame-CSRF':(await localJSON('/api/state')).csrf}:{})},...(body?{body:JSON.stringify(body)}:{})});
 const d=await r.json();if(!r.ok)throw Error(d.error||'Ошибка редактора');return d;
}
function verifySender(e){if(e.sender!==main?.webContents||!e.senderFrame.url.startsWith(origin+PREFIX+'/'))throw Error('Недопустимый вызов')}
async function connect(e){
 verifySender(e);
 if(await connected()){setTimeout(()=>updater?.check(false),300);return {connected:true}};
 const login=new BrowserWindow({width:620,height:700,parent:main,modal:true,autoHideMenuBar:true,webPreferences:{session:remoteSession,nodeIntegration:false,contextIsolation:true,sandbox:true}});
 secure(login);login.webContents.on('will-navigate',(e,url)=>{if(!url.startsWith(REMOTE+PREFIX+'/')&&url!==REMOTE+PREFIX)e.preventDefault()});
 await login.loadURL(REMOTE+PREFIX+'/login');
 return new Promise(resolve=>{
  let done=false;
  const changed=async(_e,c,cause,removed)=>{if(!removed&&c.name==='frame_session'&&!done){done=true;csrf='';login.close()}};
  remoteSession.cookies.on('changed',changed);
  login.once('closed',async()=>{remoteSession.cookies.removeListener('changed',changed);resolve({connected:await connected()});setTimeout(()=>updater?.check(false),500)});
 });
}
app.on('second-instance',()=>{if(main){if(main.isMinimized())main.restore();main.show();main.focus()}});
app.on('window-all-closed',()=>app.quit());
app.on('before-quit',()=>{quitting=true;if(worker){worker.kill();worker=null}transport?.close()});
app.whenReady().then(async()=>{
 if(!app.requestSingleInstanceLock()){app.quit();return}
 fs.mkdirSync(data,{recursive:true});
 remoteSession=session.fromPartition('persist:frame-remote');
 remoteSession.setPermissionRequestHandler((_w,_p,cb)=>cb(false));
 updater=attachUpdater({app,dialog,getMain:()=>main,connected,remoteFetch,localJSON,runtime,vendor});
 const nativePort=await nativeTransport(),localPort=await freePort();origin='http://127.0.0.1:'+localPort;
 const exe=process.platform==='win32'?path.join(vendor,'python','python.exe'):path.join(vendor,'python','bin','python3');
 const engine=process.platform==='win32'?path.join(vendor,'engine','filmcraft-cli.exe'):path.join(vendor,'engine','filmcraft-cli');
 const dev=process.env.FRAME_DEV_PYTHON;
 worker=spawn(dev||exe,['-X','utf8',path.join(runtime,'server.py'),'--port',String(localPort),'--data',data],{windowsHide:true,env:{...process.env,FRAME_ENGINE:process.env.FRAME_DEV_ENGINE||engine,FRAME_VENDOR:vendor,FRAME_LOCAL_ORIGIN:origin,FRAME_WORKER_TOKEN:workerToken,FRAME_NATIVE_PORT:String(nativePort),FRAME_NATIVE_TOKEN:nativeToken,PATH:path.join(vendor,'bin')+path.delimiter+process.env.PATH,PYTHONPATH:runtime,PYTHONDONTWRITEBYTECODE:'1',PYTHONUTF8:'1',PYTHONIOENCODING:'utf-8',OPENBLAS_NUM_THREADS:'1'}});
 let tail='';worker.stderr.on('data',b=>{tail=(tail+b.toString()).slice(-2000)});
 worker.once('error',e=>dialog.showErrorBox('Frame',e.message));
 worker.once('exit',code=>{if(!quitting){dialog.showErrorBox('Frame','Движок остановился ('+code+'). Проекты сохранены. '+tail);app.quit()}});
 main=new BrowserWindow({width:1600,height:1000,minWidth:1000,minHeight:700,show:false,backgroundColor:'#181a1d',title:'Frame',autoHideMenuBar:true,webPreferences:{preload:path.join(__dirname,'preload.cjs'),nodeIntegration:false,contextIsolation:true,sandbox:true}});
 secure(main);
 main.webContents.on('will-navigate',(e,url)=>{if(!url.startsWith(origin+PREFIX+'/'))e.preventDefault()});
 const ses=main.webContents.session;
 ses.setPermissionRequestHandler((_w,_p,cb)=>cb(false));
 ses.webRequest.onBeforeSendHeaders({urls:[origin+'/*']},(d,cb)=>cb({requestHeaders:{...d.requestHeaders,...(d.webContentsId===main.webContents.id?{'X-Frame-Worker-Token':workerToken}:{})}}));
 ipcMain.handle('frame:connect',connect);
 ipcMain.handle('frame:disconnect',async e=>{verifySender(e);await remoteSession.clearStorageData();csrf='';return {connected:false}});
 ipcMain.handle('frame:status',async e=>{verifySender(e);return {connected:await connected(),platform:process.platform,arch:process.arch}});
 ipcMain.handle('frame:import',async e=>{
  verifySender(e);const r=await dialog.showOpenDialog(main,{title:'Добавить материалы',properties:['openFile','multiSelections'],filters:[{name:'Видео, звук и изображения',extensions:['mp4','mov','mkv','webm','wav','mp3','flac','png','jpg','jpeg']}]});
  if(r.canceled)return null;return localJSON('/api/action',{action:'desktopImport',paths:r.filePaths});
 });
 ipcMain.handle('frame:import-paths',async(e,paths)=>{
  verifySender(e);
  if(!Array.isArray(paths)||!paths.length||paths.length>200||paths.some(p=>typeof p!=='string'||!path.isAbsolute(p)||p.includes('\0')))throw Error('Недопустимые файлы');
  return localJSON('/api/action',{action:'desktopImport',paths});
 });
 ipcMain.handle('frame:save',async(e,url)=>{
  verifySender(e);
  if(typeof url!=='string'||!url.startsWith(PREFIX+'/files/renders/')||url.includes('..'))throw Error('Недопустимый файл');
  const name=path.basename(new URL(origin+url).pathname),r=await dialog.showSaveDialog(main,{defaultPath:name});if(r.canceled)return;
  const source=path.join(data,'renders',name);
  if(!fs.existsSync(source))throw Error('Файл ещё не готов');
  const pending=r.filePath+'.frame-'+crypto.randomBytes(8).toString('hex')+'.tmp';
  try{await fs.promises.copyFile(source,pending,fs.constants.COPYFILE_EXCL);await fs.promises.rename(pending,r.filePath)}finally{await fs.promises.unlink(pending).catch(()=>{})}
  return {saved:true};
 });
 Menu.setApplicationMenu(Menu.buildFromTemplate([{label:'Frame',submenu:[{role:'about'},{label:'Проверить обновление',click:()=>updater.check(true)},{type:'separator'},{role:'quit'}]},{label:'Правка',submenu:[{role:'cut'},{role:'copy'},{role:'paste'},{role:'selectAll'}]},{label:'Вид',submenu:[{role:'togglefullscreen'},{role:'resetZoom'},{role:'zoomIn'},{role:'zoomOut'}]}]));
 let ready=false;
 for(let i=0;i<120;i++){try{await localJSON('/health');ready=true;break}catch{}await new Promise(r=>setTimeout(r,250))}
 if(!ready)throw Error('Движок не ответил: '+tail);
 await main.loadURL(origin+PREFIX+'/');main.show();await updater.boot();
}).catch(e=>{dialog.showErrorBox('Frame',e.message);app.quit()});
