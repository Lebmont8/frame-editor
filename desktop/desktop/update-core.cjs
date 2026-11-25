'use strict';
const crypto=require('node:crypto'),fs=require('node:fs');
const VERSION=/^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/;
function newer(a,b){if(!VERSION.test(a)||!VERSION.test(b))throw Error('Неверная версия обновления');const x=a.split('.').map(Number),y=b.split('.').map(Number);for(let i=0;i<3;i++){if(x[i]!==y[i])return x[i]>y[i]}return false}
function manifest(envelope,key,platform,arch,current){
 if(!envelope||typeof envelope.payload!=='string'||envelope.payload.length>90000||typeof envelope.signature!=='string'||envelope.signature.length>128)throw Error('Неверный пакет обновления');
 const bytes=Buffer.from(envelope.payload,'base64'),sig=Buffer.from(envelope.signature,'base64');
 if(sig.length!==64||!crypto.verify(null,bytes,key,sig))throw Error('Подпись обновления не прошла проверку');
 const d=JSON.parse(bytes.toString('utf8'));
 if(d.schema!==1||!VERSION.test(d.version)||!d.platforms)throw Error('Неверный формат обновления');
 const target=platform==='win32'&&arch==='x64'?'windows':platform==='darwin'&&arch==='arm64'?'mac':null;
 if(!target)return null;
 const f=d.platforms[target];
 if(!f||!Number.isSafeInteger(f.bytes)||f.bytes<1||f.bytes>1024**3||!Number.isSafeInteger(f.installBytes)||f.installBytes<1||f.installBytes>3*1024**3||!Number.isSafeInteger(f.fileCount)||f.fileCount<1||f.fileCount>50000||!/^[a-f0-9]{64}$/.test(f.sha256)||f.download!=='/api/desktop/downloads/'+target)throw Error('Неверные параметры обновления');
 return newer(d.version,current)?{...f,version:d.version,target}:null;
}
function sourceURL(value){const u=new URL(value);if(u.protocol!=='https:'||u.username||u.password||u.port||! /^[a-z0-9.-]+\.your-objectstorage\.com$/.test(u.hostname))throw Error('Недопустимый сервер обновлений');return u.href}
async function boundedJSON(response){if(!response.ok)throw Error('Не удалось проверить обновление');let size=0,parts=[];for await(const part of response.body){size+=part.length;if(size>100000)throw Error('Слишком большой ответ обновления');parts.push(Buffer.from(part))}return JSON.parse(Buffer.concat(parts).toString('utf8'))}
async function savePackage(response,file,release,onProgress=()=>{}){
 if(response.status!==200||!response.body)throw Error('Не удалось скачать обновление');
 const length=response.headers.get('content-length');
 if(length!==null&&Number(length)!==release.bytes)throw Error('Размер обновления не совпадает');
 const temporary=file+'.part';let fd;
 try{
  fd=fs.openSync(temporary,'wx',0o600);let n=0;const hash=crypto.createHash('sha256');
  for await(const part of response.body){
   const b=Buffer.from(part);n+=b.length;if(n>release.bytes)throw Error('Размер обновления превышен');
   hash.update(b);let off=0;while(off<b.length)off+=fs.writeSync(fd,b,off,b.length-off);onProgress(n/release.bytes);
  }
  if(n!==release.bytes||hash.digest('hex')!==release.sha256)throw Error('Обновление скачано не полностью или повреждено');
  fs.fsyncSync(fd);fs.closeSync(fd);fd=undefined;fs.renameSync(temporary,file);return file;
 }catch(e){if(fd!==undefined)fs.closeSync(fd);try{fs.unlinkSync(temporary)}catch{}throw e}
}
function atomic(file,value){const t=file+'.new';fs.writeFileSync(t,JSON.stringify(value),{mode:0o600});fs.renameSync(t,file)}
module.exports={newer,manifest,sourceURL,boundedJSON,savePackage,atomic};
