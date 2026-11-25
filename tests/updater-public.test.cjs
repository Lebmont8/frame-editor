const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {attach}=require('../desktop/desktop/updater.cjs');
test('source build never loads a private updater identity when no public key is configured',async()=>{
 const prior=process.env.FRAME_UPDATE_PUBLIC_KEY;delete process.env.FRAME_UPDATE_PUBLIC_KEY;
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'frame-public-updater-'));let notices=0;
 try{const updater=attach({app:{getPath:()=>dir},dialog:{showMessageBox:async()=>{notices++;return {response:0}}}});
 assert.equal(typeof updater.boot,'function');assert.equal(typeof updater.check,'function');await updater.boot();await updater.check();assert.equal(notices,1);
 }finally{if(prior!==undefined)process.env.FRAME_UPDATE_PUBLIC_KEY=prior;else delete process.env.FRAME_UPDATE_PUBLIC_KEY;}
});
