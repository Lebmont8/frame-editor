'use strict';
const {contextBridge,ipcRenderer,webUtils}=require('electron');
contextBridge.exposeInMainWorld('frameNative',Object.freeze({
 connect:()=>ipcRenderer.invoke('frame:connect'),
 disconnect:()=>ipcRenderer.invoke('frame:disconnect'),
 importMedia:()=>ipcRenderer.invoke('frame:import'),
 exportFile:url=>ipcRenderer.invoke('frame:save',url),
 status:()=>ipcRenderer.invoke('frame:status')
}));

// Native OS drag/drop references the original file, never browser-upload copies.
window.addEventListener('drop',event=>{
 if(!event.isTrusted||!event.target.closest?.('#pool')||!event.dataTransfer?.files.length)return;
 event.preventDefault();event.stopImmediatePropagation();
 const paths=[...event.dataTransfer.files].map(file=>webUtils.getPathForFile(file));
 ipcRenderer.invoke('frame:import-paths',paths).then(data=>window.postMessage({type:'frame-native-drop',data},location.origin)).catch(error=>window.postMessage({type:'frame-native-drop',error:error.message},location.origin));
},true);
