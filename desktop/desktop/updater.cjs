'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),{spawn}=require('node:child_process');
const core=require('./update-core.cjs');
const CAPTURE="(()=>{\n if(typeof data==='undefined'||!data?.document)throw Error('Редактор ещё загружается');\n if(busy||frameBusy||dragging||document.querySelector('dialog[open]'))throw Error('Заверши текущее действие перед обновлением');\n const values=[...document.querySelectorAll('#stageContent input[id],#stageContent textarea[id],#stageContent select[id]')].filter(e=>!['file','password'].includes(e.type)).map(e=>({id:e.id,value:e.value,checked:e.checked,dirty:!!e.dataset.frameDirty,start:e.selectionStart,end:e.selectionEnd}));\n return {project:data.project,page,selected,asset,values,drafts:typeof inspectorDrafts==='undefined'?[]:[...inspectorDrafts],focus:document.activeElement?.id};\n})()";
function attach(deps){
 const {app,dialog,getMain,connected,remoteFetch,localJSON,runtime,vendor}=deps;
 const dir=path.join(app.getPath('userData'),'updates'),draft=path.join(app.getPath('userData'),'update-draft.json');
 let busy=false,offered='',pending=null,cache=null,controller=null,installing=false;
 fs.mkdirSync(dir,{recursive:true,mode:0o700});
 const keyFile=process.env.FRAME_UPDATE_PUBLIC_KEY;
 if(!keyFile)return {boot:async()=>{},check:async()=>{await dialog.showMessageBox({message:'Signed updates are not configured for this source build.'})}};
 const key=fs.readFileSync(keyFile,'utf8');
 const python=process.platform==='win32'?path.join(vendor,'python','python.exe'):path.join(vendor,'python','bin','python3');
 const helper=path.join(runtime,'update_helper.py');
 const message=(text,buttons=['OK'])=>!getMain()||getMain().isDestroyed()?Promise.resolve({response:buttons.length-1}):dialog.showMessageBox(getMain(),{title:'Frame',message:text,buttons,defaultId:0,cancelId:buttons.length-1,noLink:true});
 function command(exe,args,options={}){return new Promise((resolve,reject)=>{const child=spawn(exe,['-X','utf8',...args],{windowsHide:true,stdio:['ignore','pipe','pipe'],...options});let text='';child.stdout.on('data',b=>{text=(text+b).slice(-2000)});child.stderr.on('data',()=>{});const timer=setTimeout(()=>{child.kill();reject(Error('Подготовка обновления не завершилась'))},180000);child.once('error',()=>{clearTimeout(timer);reject(Error('Не удалось запустить подготовку обновления'))});child.once('exit',code=>{clearTimeout(timer);code===0?resolve(text):reject(Error('Не удалось подготовить обновление. Проверь свободное место и доступ к папке приложения.'))})})}
 function targetPath(){
  if(process.platform==='win32')return path.dirname(process.execPath);
  const suffix=path.sep+'Contents'+path.sep+'MacOS'+path.sep+'Frame';
  if(process.platform==='darwin'&&process.execPath.endsWith(suffix))return process.execPath.slice(0,-suffix.length);
  throw Error('Автообновление доступно в установленной Windows- или Mac-версии');
 }
 async function download(release){
  const nonce=crypto.randomBytes(16).toString('hex');cache=path.join(dir,'update-'+nonce);fs.mkdirSync(cache,{mode:0o700});
  const file=path.join(cache,release.target==='windows'?'package.exe':'package.zip'),target=targetPath();
  const plan={...release,cache,target,artifact:file,nonce,parentPid:process.pid,platform:release.target,helperBytes:120*1024**2};
  const cap="import importlib.util,json,sys\ns=importlib.util.spec_from_file_location(\"frame_update\",sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);d=json.loads(sys.argv[2]);m.capacity([(d[\"cache\"],d[\"bytes\"]+d[\"installBytes\"]+d[\"helperBytes\"]+16*1024**2),(str(m.P(d[\"target\"]).parent),d[\"installBytes\"]+16*1024**2)])\n";
  await command(python,['-c',cap,helper,JSON.stringify(plan)]);
  controller=new AbortController();const timer=setTimeout(()=>controller.abort(),10*60*1000);
  try{
   const r=await remoteFetch(release.download,{redirect:'manual',signal:controller.signal});
   if(r.status!==302)throw Error('Войди в аккаунт Frame для загрузки обновления');
   const url=core.sourceURL(r.headers.get('location'));
   const body=await fetch(url,{redirect:'error',credentials:'omit',signal:controller.signal});
   await core.savePackage(body,file,release,p=>getMain()?.setProgressBar(p));
  }finally{clearTimeout(timer);getMain()?.setProgressBar(-1);controller=null}
  core.atomic(path.join(cache,'plan.json'),plan);
  await command(python,[helper,'prepare',path.join(cache,'plan.json')]);
  return {release,plan};
 }
 async function apply(){
  if(!pending)return;
  const main=getMain(),plan=pending.plan;
  const snapshot=await main.webContents.executeJavaScript(CAPTURE);
  if(JSON.stringify(snapshot).length>1024**2)throw Error('Сохрани введённый текст перед обновлением');
  await main.webContents.executeJavaScript('document.documentElement.inert=true;document.querySelectorAll("video,audio").forEach(e=>e.pause())');
  let prepared=false;
  try{
   await localJSON('/api/action',{action:'desktopUpdatePrepare'});prepared=true;
   core.atomic(draft,snapshot);
   const helperRoot=path.join(cache,'helper-python');fs.cpSync(path.join(vendor,'python'),helperRoot,{recursive:true,dereference:false,errorOnExist:true,force:false});
   const script=path.join(cache,'update_helper.py');fs.copyFileSync(helper,script);
   const exe=process.platform==='win32'?path.join(helperRoot,'python.exe'):path.join(helperRoot,'bin','python3');
   const child=spawn(exe,['-X','utf8',script,'run',path.join(cache,'plan.json')],{windowsHide:true,detached:true,stdio:'ignore',cwd:cache});
   let error;child.once('error',()=>{error=Error('Не удалось запустить установку')});child.unref();
   const ready=path.join(cache,'ready.json');
   for(let i=0;i<300;i++){
    if(error)throw error;
    if(fs.existsSync(path.join(cache,'error.json')))throw Error('Не удалось подготовить установку');
    if(fs.existsSync(ready)){const r=JSON.parse(fs.readFileSync(ready));if(r.nonce===plan.nonce){core.atomic(path.join(cache,'commit.json'),{nonce:plan.nonce});installing=true;app.quit();return}}
    await new Promise(r=>setTimeout(r,100));
   }
   throw Error('Установщик не подтвердил готовность');
  }catch(e){
   core.atomic(path.join(cache,'cancel.json'),{nonce:plan.nonce});pending=null;
   if(prepared)await localJSON('/api/action',{action:'desktopUpdateAbort'}).catch(()=>{});
   await main.webContents.executeJavaScript('document.documentElement.inert=false').catch(()=>{});
   throw e;
  }
 }
 async function check(manual=false){
  if(busy||!getMain())return;
  if(!app.isPackaged){if(manual)await message('Обновления доступны в установленном приложении');return}
  busy=true;
  try{
   if(!await connected()){if(manual)await message('Сначала подключи аккаунт кнопкой «Ася и мой ПК»');return}
   const envelope=await core.boundedJSON(await remoteFetch('/api/desktop/updates',{signal:AbortSignal.timeout(20000)}));
   const release=core.manifest(envelope,key,deps.platform||process.platform,deps.arch||process.arch,app.getVersion());
   if(!release){if(manual)await message('Обновлений нет');return}
   if(offered===release.version&&!manual)return;
   offered=release.version;
   if(!pending||pending.release.sha256!==release.sha256){
    if((await message('Доступно обновление',['Обновить','Позже'])).response!==0)return;
    pending=await download(release);
   }
   if((await message('Обновление готово',['Перезапустить и обновить','Позже'])).response===0)await apply();
  }catch(e){if(manual||offered)await message('Обновление не применено. '+(e.message||'Попробуй позже.'))}
  finally{busy=false}
 }
 async function boot(){
  const main=getMain();
  if(fs.existsSync(draft)){
   try{
    const d=JSON.parse(fs.readFileSync(draft,'utf8'));
    for(let i=0;i<100;i++){
     if(await main.webContents.executeJavaScript("typeof data!=='undefined'&&!!data?.document"))break;
     await new Promise(r=>setTimeout(r,100));
    }
    const applied=await main.webContents.executeJavaScript('('+String(function(d){
     if(typeof data==='undefined'||data?.project!==d.project)return false;
     if(PAGES.includes(d.page))page=d.page;
     if(typeof inspectorDrafts!=='undefined'&&Array.isArray(d.drafts))for(const [key,value]of d.drafts.slice(0,100))if(typeof key==='string'&&Array.isArray(value?.values))inspectorDrafts.set(key,value);
     selected=d.selected;asset=d.asset;setPage(page);renderInspector();
     for(const v of d.values||[]){const e=document.getElementById(v.id);if(!e||!document.getElementById('stageContent').contains(e))continue;e.value=v.value;if(e.type==='checkbox'||e.type==='radio')e.checked=v.checked;if(v.dirty)e.dataset.frameDirty='1';if(e.id===d.focus){e.focus({preventScroll:true});if(typeof v.start==='number')try{e.setSelectionRange(v.start,v.end)}catch{}}}
     return true;
    })+')('+JSON.stringify(d)+')');
    if(applied)fs.renameSync(draft,draft+'.restored');
   }catch{await message('Проект сохранён, но введённый текст не удалось восстановить автоматически. Черновик сохранён.')}
  }
  const receiptArg=process.argv.find(a=>a.startsWith('--frame-update-receipt='));
  const nonceArg=process.argv.find(a=>a.startsWith('--frame-update-nonce='));
  if(receiptArg&&nonceArg){
   const file=receiptArg.slice('--frame-update-receipt='.length),nonce=nonceArg.slice('--frame-update-nonce='.length);
   if(/^[a-f0-9]{32}$/.test(nonce)&&file===path.join(dir,'update-'+nonce,'boot.json'))core.atomic(file,{nonce,version:app.getVersion(),pid:process.pid});
  }
  if(app.isPackaged)setTimeout(()=>check(false),1200);
 }
 app.on('before-quit',()=>controller?.abort());
 return {check,boot,get installing(){return installing}};
}
module.exports={attach,CAPTURE};
