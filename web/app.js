'use strict';
const $=id=>document.getElementById(id),BASE=location.pathname.replace(/\/$/,''),T=254016000000;
let data,csrf='',selected=null,asset=null,busy=false,videoURL='',polling=false,page='edit',bin='all',tool='select',snapping=true,uploadRole='video',sourceURL='',sourceIn=0,sourceOut=null,focusedSource=false,zoom=0,frameBusy=false,frameAgain=false,autoPlay=false,reverseTimer=null,dragging=false;
const PAGES=['media','audio','sync','story','edit','color','insert','voice','package','deliver'];
const TITLES={media:'Материалы проекта',audio:'Обработка звука',sync:'Синхронизация',story:'Содержание и смысл',edit:'Инспектор',color:'Цвет и изображение',insert:'Медиавставки',voice:'Перевод и дубляж',package:'Название и обложка',deliver:'Экспорт'};
const icon=id=>'<svg aria-hidden="true"><use href="#i-'+id+'"/></svg>';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const cleanName=s=>String(s||'').replace(/^[a-f0-9]{10}-/,'');
function note(t,error=false){$('notice').textContent=t;$('notice').classList.toggle('error',error);$('notice').title=t}
async function api(path,body){const r=await fetch(BASE+'/api/'+path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json','X-Frame-CSRF':csrf}:{},body:body?JSON.stringify(body):undefined});const d=await r.json();if(!r.ok)throw Error(d.error||'Ошибка операции');if(d.csrf)csrf=d.csrf;return d}
function seq(){return data?.document?.sequence||{}}
function clips(){return ['video','audio'].flatMap(k=>(seq()[k]||[]).flatMap((t,i)=>t.items.filter(c=>c.clip).map(c=>({...c,kind:k,track:(k==='video'?'V':'A')+(i+1)}))))}
function current(){return clips().find(c=>c.clip===selected)}
function fps(){const f=seq().settings?.frame_rate;return f?f.num/f.den:25}
function sec(t){return (t||0)/T}
function dur(){return sec(seq().duration)}
function tc(s){s=Math.max(0,s||0);const f=Math.floor((s%1)*fps()+.001);return [Math.floor(s/3600),Math.floor(s/60)%60,Math.floor(s)%60,f].map(x=>String(x).padStart(2,'0')).join(':')}
function n(id){return Number($(id)?.value||0)}
function el(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e}
function wf(){return data?.workflow||{roles:{},approved:{},notes:[]}}
function media(){return data?.media||[]}
function source(){return media().find(m=>m.item===asset)}
function val(id,fallback=''){return $(id)?.value??fallback}
function field(label,id,value,type='number',attrs=''){return '<label class="field">'+label+'<input id="'+id+'" type="'+type+'" value="'+esc(value)+'" '+attrs+'></label>'}
function select(label,id,items,chosen){return '<label class="field stacked">'+label+'<select id="'+id+'">'+items.map(m=>'<option value="'+m.item+'" '+(String(m.item)===String(chosen)?'selected':'')+'>'+esc(cleanName(m.name))+'</option>').join('')+'</select></label>'}
function bind(id,fn){if($(id))$(id).onclick=()=>Promise.resolve().then(fn).catch(e=>note(e.message,true))}
function textArea(id,text,placeholder=''){return '<textarea id="'+id+'" placeholder="'+esc(placeholder)+'">'+esc(text||'')+'</textarea>'}
function hint(t){return '<p class="hint">'+t+'</p>'}
function approval(){const ok=wf().approved?.[page];return '<div class="approval"><button id="approveStage">'+(ok?'✓ Этап принят · отменить':'Принять этот этап')+'</button></div>'}
async function saveWorkflow(patch){const next={...wf(),...patch};const d=await api('action',{action:'workflow',workflow:next});update(d);note('Настройки этапа сохранены')}
function update(d){
 data={...d,account:d.account||data?.account,authCsrf:d.authCsrf||data?.authCsrf};if(d.csrf)csrf=d.csrf;
 $('accountName').textContent=data.account||'';$('projectName').textContent=d.project?.replace('.fcproj','')||'Монтаж';
 const s=seq().settings;$('sequenceInfo').textContent=s?s.width+' × '+s.height+' · '+fps().toFixed(2).replace(/\.00$/,'')+' fps':'';
 const picker=$('projectPicker');picker.replaceChildren(...d.projects.map(p=>{const o=el('option',p.replace('.fcproj',''));o.value=p;return o}));picker.value=d.project;
 if(!media().some(m=>m.item===asset))asset=media()[0]?.item??null;
 renderAssets();renderSource();renderTimeline();renderInspector();syncCursor();
 $('duration').textContent=tc(dur());$('seek').max=Math.max(dur(),.001);
 if(d.preview?.url&&videoURL!==d.preview.url){videoURL=d.preview.url;$('video').src=videoURL;$('video').hidden=false;$('frame').hidden=true;$('empty').hidden=true;$('video').onloadedmetadata=()=>{$('video').currentTime=Math.min(n('playhead'),$('video').duration||0);if(autoPlay){autoPlay=false;$('video').play().catch(()=>{})}}}
 const stale=d.preview?.revision!==d.revision;
 $('staleMark').hidden=!d.preview||!stale;$('previewState').textContent=d.preview?(stale?'Просмотр устарел':'Просмотр актуален'):'';
 if(d.frame?.revision===d.revision){$('frame').src=d.frame.url;$('frame').hidden=false;$('video').hidden=true;$('empty').hidden=true}
 for(const b of document.querySelectorAll('[data-page]'))b.classList.toggle('done',!!wf().approved?.[b.dataset.page]);
 renderJobState(d.jobs||[]);
}
function renderAssets(){
 const term=$('search').value.toLocaleLowerCase();let list=media().filter(m=>cleanName(m.name).toLocaleLowerCase().includes(term));
 if(bin==='video')list=list.filter(m=>m.type==='Movie');if(bin==='audio')list=list.filter(m=>m.type==='Audio');
 if(['insert','reference'].includes(bin))list=list.filter(m=>(bin==='reference'?['reference','coverReference'].includes(wf().roles?.[m.item]):wf().roles?.[m.item]===bin));
 $('assets').replaceChildren(...list.map(m=>{
  const b=el('button',undefined,'asset '+(m.type==='Audio'?'audio ':'')+(m.item===asset?'selected':''));b.dataset.item=m.item;b.draggable=true;b.title=cleanName(m.name);
  const thumb=el('span',undefined,'thumb');if(m.thumb){const im=el('img');im.src=m.thumb;im.alt='';thumb.append(im)}else thumb.innerHTML=icon(m.type==='Audio'?'sound':'media');
  b.append(thumb,el('b',cleanName(m.name)),el('small',m.type==='Still'?'Изображение':tc(sec(m.duration))));b.onclick=()=>{asset=m.item;focusedSource=true;sourceIn=0;sourceOut=null;renderAssets();renderSource();renderInspector()};
  b.ondragstart=e=>{e.dataTransfer.setData('application/x-frame-item',String(m.item));e.dataTransfer.effectAllowed='copy'};return b;
 }));
 $('poolEmpty').hidden=!!list.length;$('assetCount').textContent=media().length+' файлов';
}
function renderSource(){
 const m=source();$('sourceName').textContent=m?cleanName(m.name):'Исходный материал';
 if(m&&m.url!==sourceURL){sourceURL=m.url;sourceIn=0;sourceOut=null;$('sourceVideo').pause();$('sourceVideo').removeAttribute('src');$('sourceImage').removeAttribute('src');
  if(m.type==='Still')$('sourceImage').src=m.url;else {$('sourceVideo').src=m.url;$('sourceVideo').onloadedmetadata=()=>{$('sourceVideo').currentTime=Math.min(3,($('sourceVideo').duration||0)*.25)}}
 }
 $('sourceVideo').hidden=!m||m.type==='Still';$('sourceImage').hidden=!m||m.type!=='Still';$('sourceEmpty').hidden=!!m;$('sourceSeek').max=Math.max(sec(m?.duration),.001);
 for(const id of ['addClip','insertClip','appendClip','markIn','markOut','sourcePlay'])$(id).disabled=!m;
 updateSourceTC();
}
function updateSourceTC(){const t=$('sourceVideo').currentTime||0;$('sourceTC').textContent=tc(t);$('sourceSeek').value=t;$('sourceRange').textContent=sourceIn||sourceOut!==null?tc(sourceIn)+' → '+tc(sourceOut??sec(source()?.duration)):''}
function range(){const m=source();const end=sourceOut??sec(m?.duration);return {sourceIn,duration:Math.max(.001,end-sourceIn)}}
async function add(mode='overwrite',track,at){if(asset==null)return note('Выбери материал',true);const m=source();return act('add',{item:asset,track:track||$('addTrack').value,seconds:at??(mode==='append'?dur():n('playhead')),insert:mode==='insert',...range()})}
function pxs(){const avail=Math.max(200,$('timelineScroll').clientWidth-126);return avail/Math.max(30,dur())*(1+zoom*zoom/500)}
function setCursor(t,frame=true){const v=Math.max(0,Math.min(t,dur()?Math.max(0,dur()-1/fps()):0));$('playhead').value=v.toFixed(5);syncCursor();if(!frame)return;if(!$('video').hidden&&data.preview?.revision===data.revision){$('video').currentTime=v}else showFrame().catch(e=>note(e.message,true))}
function syncCursor(){const t=n('playhead');for(const id of ['programTC','timelineTC'])$(id).textContent=tc(t);$('seek').value=t;$('cursorLine').style.left=(126+t*pxs())+'px'}
function renderTimeline(){
 const scale=pxs(),width=Math.max($('timelineScroll').clientWidth-126,Math.max(30,dur()+2)*scale);$('timelineCanvas').style.setProperty('--lane',width+'px');$('timelineCanvas').style.width=(126+width)+'px';
 const spacing=[.1,.25,.5,1,2,5,10,15,30,60,120].find(v=>v*scale>=75)||120;const ticks=[];
 for(let t=0;t<=width/scale;t+=spacing){const e=el('span',tc(t),'tick');e.style.left=(t*scale)+'px';ticks.push(e)}$('rulerTicks').replaceChildren(...ticks);
 const tracks=[];
 for(const kind of ['video','audio'])for(const [ix,t]of(seq()[kind]||[]).entries()){
  const tr=el('div',undefined,'track'),tn=(kind==='video'?'V':'A')+(ix+1);tr.dataset.track=tn;
  const name=el('div',undefined,'trackname '+kind),top=el('div',undefined,'tracktop');top.append(el('b',tn),el('span',kind==='video'?(ix===0?'Основное':'Вставки'):'Аудио '+(ix+1)));const toggle=el('button',kind==='audio'?'M':'◉');toggle.title=kind==='audio'?'Выключить звук дорожки':'Скрыть дорожку';toggle.setAttribute('aria-pressed',kind==='audio'?!!t.muted:!t.enabled);toggle.onclick=()=>act('track',{track:tn,...(kind==='audio'?{muted:!t.muted}:{enabled:!t.enabled})}).catch(e=>note(e.message,true));top.append(toggle);name.append(top,el('small',(t.items||[]).filter(c=>c.clip).length+' фрагм.'));tr.append(name);
  const lane=el('div',undefined,'lane');lane.dataset.track=tn;
  lane.onpointerdown=e=>{if(e.target!==lane)return;focusedSource=false;setCursor((e.clientX-lane.getBoundingClientRect().left)/scale)};
  lane.ondragover=e=>{e.preventDefault();e.dataTransfer.dropEffect='copy'};
  lane.ondrop=e=>{e.preventDefault();const id=Number(e.dataTransfer.getData('application/x-frame-item'));if(!media().some(m=>m.item===id))return;asset=id;sourceIn=0;sourceOut=null;add('overwrite',tn,Math.max(0,(e.clientX-lane.getBoundingClientRect().left)/scale))};
  for(const c of t.items||[]){if(!c.clip)continue;
   const b=el('button',undefined,'clip '+kind+(selected===c.clip?' selected':''));b.dataset.clip=c.clip;b.dataset.track=tn;b.style.left=(sec(c.start)*scale)+'px';b.style.width=Math.max(4,sec(c.duration)*scale)+'px';b.title=cleanName(c.name)+' · '+tc(sec(c.start))+' — '+tc(sec(c.end));b.setAttribute('aria-label',tn+' '+cleanName(c.name)+' '+tc(sec(c.start)));
   const m=media().find(m=>m.item===c.item);
   if(kind==='video'&&m?.thumb){const strip=el('span',undefined,'filmstrip');for(let i=0;i<Math.min(28,Math.ceil(sec(c.duration)*scale/65));i++){const im=el('img');im.src=m.thumb;im.alt='';strip.append(im)}b.append(strip)}
   if(kind==='audio'&&m?.peaks?.length){const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 400 40');svg.setAttribute('preserveAspectRatio','none');svg.classList.add('waveform');const start=sec(c.sourceIn)/Math.max(.001,sec(m.duration)),end=(sec(c.sourceIn)+sec(c.duration))/Math.max(.001,sec(m.duration));const p=m.peaks.slice(Math.floor(start*m.peaks.length),Math.max(Math.floor(start*m.peaks.length)+1,Math.ceil(end*m.peaks.length)));const path=document.createElementNS(svg.namespaceURI,'path');path.setAttribute('d',p.map((v,i)=>'M'+(400*i/p.length)+' '+(20-v*19)+'v'+(v*38)).join(''));path.setAttribute('stroke','#8ab9a0');path.setAttribute('stroke-width',Math.max(1,400/p.length*.65));svg.append(path);b.append(svg)}
   b.append(el('span',cleanName(c.name),'cliplabel'));for(const edge of ['left','right']){const h=el('span',undefined,'handle '+edge);h.dataset.edge=edge;b.append(h)}
   b.onpointerdown=e=>startClipDrag(e,b,c,tn,scale);
   b.onkeydown=e=>{if(e.key==='Enter'){selected=c.clip;setCursor(sec(c.start));renderTimeline();renderInspector()}};
   lane.append(b);
  }tr.append(lane);tracks.push(tr);
 }
 $('tracks').replaceChildren(...tracks);const c=current();$('selection').textContent=c?c.track+' · '+cleanName(c.name):'Фрагмент не выбран';for(const id of ['deleteClip','deleteRipple'])$(id).disabled=!c||busy;syncCursor();
}
function startClipDrag(e,b,c,tn,scale){
 if(e.button!==0||busy)return;e.preventDefault();focusedSource=false;selected=c.clip;
 if(tool==='blade'&&!e.target.dataset.edge){setCursor(sec(c.start)+(e.clientX-b.getBoundingClientRect().left)/scale,false);act('split',{seconds:n('playhead')});return}
 document.querySelectorAll('.clip').forEach(x=>x.classList.toggle('selected',Number(x.dataset.clip)===selected));renderInspector();$('selection').textContent=tn+' · '+cleanName(c.name);
 const x=e.clientX,edge=e.target.dataset.edge;let delta=0,moved=false,targetTrack=tn;b.setPointerCapture(e.pointerId);
 const move=ev=>{delta=(ev.clientX-x)/scale;if(snapping)delta=Math.round(delta*fps())/fps();if(Math.abs(ev.clientX-x)>3)moved=true;
 if(edge==='left'){delta=Math.max(-sec(c.sourceIn),Math.min(delta,sec(c.duration)-1/fps()));b.style.left=((sec(c.start)+delta)*scale)+'px';b.style.width=((sec(c.duration)-delta)*scale)+'px'}
 else if(edge==='right'){delta=Math.max(-sec(c.duration)+1/fps(),delta);b.style.width=((sec(c.duration)+delta)*scale)+'px'}
 else{delta=Math.max(-sec(c.start),delta);b.style.left=((sec(c.start)+delta)*scale)+'px';const lane=document.elementFromPoint(ev.clientX,ev.clientY)?.closest('.lane,.clip');if(lane?.dataset.track?.[0]===tn[0])targetTrack=lane.dataset.track}
 };const up=async()=>{b.removeEventListener('pointermove',move);b.removeEventListener('pointerup',up);b.removeEventListener('pointercancel',cancel);
 if(moved){if(edge)await act('trim',{clip:c.clip,edge:edge==='left'?'in':'out',seconds:delta});else await act('move',{clip:c.clip,track:targetTrack,seconds:sec(c.start)+delta})}
 else{setCursor(sec(c.start));renderTimeline()}
 };const cancel=()=>{b.removeEventListener('pointermove',move);renderTimeline()};b.addEventListener('pointermove',move);b.addEventListener('pointerup',up,{once:true});b.addEventListener('pointercancel',cancel,{once:true});
}
function renderInspector(){
 const c=current(),m=source(),w=wf(),audio=media().filter(m=>m.info?.audio_streams?.length),videos=media().filter(m=>m.type==='Movie');
 $('inspectorTitle').textContent=TITLES[page];$('stageApproval').textContent=w.approved?.[page]?'✓ принято':'';
 let h='';
 if(page==='edit'){
 h='<div class="selectedname">'+esc(c?cleanName(c.name)+' · '+c.track:'Фрагмент не выбран')+'</div>';
 if(c){h+='<h3>Положение и обрезка</h3>'+field('Начало, с','clipStart',sec(c.start).toFixed(3),'number','min="0" step=".04"')+'<label class="field">Дорожка<select id="moveTrack">'+['V1','V2','A1','A2'].filter(t=>t[0]===c.track[0]).map(t=>'<option '+(t===c.track?'selected':'')+'>'+t+'</option>').join('')+'</select></label><button id="move" class="wide">Переместить</button>'+field('Подрезать, с','trimSeconds',1,'number','step=".04"')+'<div class="row"><button id="trimIn">Слева</button><button id="trimOut">Справа</button></div>'+hint('Можно тянуть края клипа мышью. Отрицательное значение возвращает исходный материал.');
 if(c.kind==='audio')h+='<h3>Уровень</h3>'+field('Усиление, дБ','gain',c.gainDb??0,'number','min="-60" max="15"')+'<button id="applyGain" class="wide">Применить усиление</button>';
 else h+=transformHTML(c);
 }else h+=hint('Выбери фрагмент на таймлайне. Перетаскивание меняет его позицию; ручки по краям — границы.')+'<h3>Инструменты</h3><p class="info"><span class="key">A</span> Выбор<br><span class="key">B</span> Лезвие<br><span class="key">Ctrl+B</span> Разрезать на курсоре</p>';
 }
 if(page==='media'){
 h='<h3>Исходные материалы</h3><div class="row"><button data-upload="video">Видео</button><button data-upload="audio1">Аудио 1</button><button data-upload="audio2">Аудио 2</button></div>'+hint('Каждый файл загружается один раз. Выбери его слева для просмотра; метки I / O задают используемый отрезок.');
 if(m){h+='<h3>'+esc(cleanName(m.name))+'</h3><div class="metadata"><span>Тип</span><b>'+esc(m.type)+'</b><span>Длительность</span><b>'+tc(sec(m.duration))+'</b><span>Размер</span><b>'+((m.original?.bytes||m.info.file_size||0)/1048576).toFixed(1)+' МиБ</b>';
 if(m.info.video)h+='<span>'+(m.original?'Кадр просмотра':'Кадр')+'</span><b>'+m.info.video.width+' × '+m.info.video.height+'</b>';h+='</div><button id="assignReference" class="wide">Использовать как референс цвета</button>'}
 h+=approval();
 }
 if(page==='audio'){
 const audioChosen=audio.some(m=>m.item===asset)?asset:audio[0]?.item,candidate=w.audioCandidates?.[audioChosen],accepted=candidate?.accepted?candidate.item:null;h='<h3>Тихая речь и громкие пики</h3>'+select('Исходная дорожка','audioSource',audio,audioChosen)+hint('Цепочка: фильтр низких частот → снижение постоянного шума → компрессия → −16 LUFS, пик −1,5 dBTP. Результат нужно прослушать.')+'<button id="cleanAudio" class="wide primary" '+(!audio.length?'disabled':'')+'>Обработать выбранный звук</button>';
 const last=[...(data.jobs||[])].reverse().find(j=>j.kind==='clean'&&j.status==='done'&&j.sourceItem===audioChosen);const processed=media().find(m=>m.item===(candidate?.item??last?.item));if(processed)h+='<h3>После обработки</h3><audio controls src="'+esc(processed.url)+'"></audio><button id="listenOriginal" class="wide">Прослушать исходную дорожку</button><button id="acceptAudio" class="wide">'+(accepted?'✓ Эта дорожка принята':'Принять обработанную дорожку')+'</button>';
 if(c?.kind==='audio')h+='<h3>Выбранный клип</h3>'+field('Усиление, дБ','gain',c.gainDb??0)+'<button id="applyGain" class="wide">Применить</button>';
 h+='<div id="jobs"></div>'+approval();
 }
 if(page==='sync'){
 const choice=w.sync?.item??(w.audioCandidates?.[asset]?.accepted?w.audioCandidates[asset].item:w.audioAccepted??audio[0]?.item);
 h='<h3>Совместить записи</h3>'+select('Видео со звуком камеры','syncVideo',videos,videos[0]?.item)+select('Отдельная аудиодорожка','syncAudio',audio,choice)+'<button id="analyzeSync" class="wide" '+(!audio.length||!videos.length?'disabled':'')+'>Найти совпадение по звуку</button>'+hint('Базовый сдвиг: первые 120 с, ±10с. Для длинной записи включи измерение по всей длине: несколько точек выявляют постепенное расхождение часов.');
 h+='<label class="consent"><input id="syncDrift" type="checkbox" checked>Измерить дрейф по всей записи</label>';const job=[...(data.jobs||[])].reverse().find(j=>j.kind==='syncAnalyze'&&j.status==='done'&&j.sourceItem===choice)|| (w.syncAnalysis?.sourceItem===choice?w.syncAnalysis:null);h+=field('Сдвиг звука, с','syncOffset',job?.result?.seconds??w.sync?.seconds??0,'number','step=".02"');if(job){h+=hint('Совпадение: '+Math.round(job.result.score*100)+'%. Проверь губы и звук в начале и конце.');if(job.result.tempo)h+=hint('Дрейф: '+job.result.driftPpm+'ppm · к концу '+job.result.endDriftSeconds+'с · надёжных точек '+job.result.acceptedAnchors+' · остаток '+job.result.maxResidualSeconds+'с')+'<button id="correctSync" class="wide">Создать дорожку с исправленным дрейфом</button>';}
 h+='<label class="field">Дорожка<select id="syncTrack"><option>A2</option><option>A1</option></select></label><label class="field">Выключить звук камеры на A1<input id="muteCamera" type="checkbox" checked></label><button id="applySync" class="wide">Добавить звук с этим сдвигом</button><div id="jobs"></div>'+approval();
 }
 if(page==='story'){
 h='<h3>Задача и конспект</h3>'+textArea('brief',w.brief,'О чём ролик, что обязательно сохранить, где смысловые паузы…')+'<label class="field">Сокращение<select id="compression">'+['Среднее','Коротко','Без воды'].map(t=>'<option '+(t===w.compression?'selected':'')+'>'+t+'</option>').join('')+'</select></label><button id="saveBrief" class="wide">Сохранить задачу</button><h3>Заметка на курсоре</h3>'+textArea('newNote','', 'Важная мысль, повторный дубль, предложение вырезки…')+'<button id="addNote" class="wide">Добавить · '+tc(n('playhead'))+'</button><div id="notesList" class="noteslist"></div><p class="pending">Расшифровка выполняется на ПК, смысловые решения предлагает Ася. Принятые предложения применяются отдельно; заметки сохраняются в проекте.</p>'+approval();
 }
 if(page==='color'){
 h='<h3>Референс</h3><button data-upload="reference" class="wide">Добавить фото / видео-референс</button>';const ref=media().find(m=>m.item===w.reference);if(ref)h+='<button id="showReference" class="wide">'+esc(cleanName(ref.name))+' · сравнить</button>';
 h+='<h3>Основная коррекция</h3>';
 const col=c?.effects?.find(e=>e.effect==='lumetri');for(const [id,label,min,max,def,step]of [['exposure','Экспозиция',-5,5,0,.1],['contrast','Контраст',-100,100,0,1],['saturation','Насыщенность',0,200,100,1]]){const v=col?.params?.[id]?.value;const value=v?Number(String(v).replace(/^Float\((.*)\)$/,'$1')):def;h+=field(label,id,value,'number','min="'+min+'" max="'+max+'" step="'+step+'"')}
 h+='<button id="applyColor" class="wide" '+(c?.kind!=='video'?'disabled':'')+'>Применить к выбранному клипу</button>'+hint('Референс открыт в левом окне, результат FilmCraft — справа. Автоподбор сверху предлагает мягкую коррекцию; результат нужно проверить.')+'<h3>Изображение</h3>'+hint('Экспорт сохраняет размер проекта. ИИ-восстановление деталей и апскейл пока не подключены; увеличение числа пикселей само по себе не восстанавливает детали.')+approval();
 }
 if(page==='insert'){
 h='<h3>Добавить материал</h3><button data-upload="insert" class="wide">Загрузить фото / видео / постер</button>'+textArea('insertPrompt',w.insertPrompt,'Где и как использовать вставку; что произносится в этот момент…')+'<button id="saveInsert" class="wide">Сохранить указания</button><button id="placeInsert" class="wide">Выбранный материал → V2 на курсор</button>'+hint('Перетащи вставку из медиатеки на V2. Её позицию и длительность можно изменить на таймлайне.');
 if(c?.kind==='video')h+=transformHTML(c);else h+=hint('Выбери видеоклип на V2 для размера и компоновки «картинка в картинке».');h+=approval();
 }
 if(page==='voice'){
 h='<h3>Язык и голос</h3><label class="field stacked">Язык перевода<input id="language" type="text" value="'+esc(w.language||'')+'" placeholder="Например, English"></label><button id="saveVoice" class="wide">Сохранить язык</button><button data-upload="audio2" class="wide">Импорт готового дубляжа</button>'+hint('Готовую озвучку можно прослушать и поставить на A2. Публикация никуда не выполняется.')+'<p class="pending">Перевод, клонирование голоса и автоматический дубляж ещё не подключены.</p>'+approval();
 }
 if(page==='package'){
 h='<h3>Варианты названия</h3>'+textArea('titleIdeas',w.titleIdeas,'До 12 вариантов, каждый с новой строки…')+hint('Список хранится отдельно для этого проекта. Варианты можно сравнить перед ручной публикацией.')+'<h3>Обложка и стиль</h3>'+textArea('coverBrief',w.coverBrief,'Референс, герой, фон, текст, что сохранить в фирменном стиле…')+'<button data-upload="reference" class="wide">Добавить референсы обложки</button><button id="savePackage" class="wide">Сохранить варианты и стиль</button><button id="downloadFrame" class="wide" '+(!data.frame?'disabled':'')+'>Скачать текущий кадр PNG</button><p class="pending">Интернет-ресерч, генерация 9–12 названий и обложек ещё не подключены. Автопубликации нет.</p>'+approval();
 }
 if(page==='deliver'){
 const s=seq().settings||{};h='<h3>Настройки вывода</h3><div class="metadata"><span>Контейнер / кодеки</span><b id="renderCodecMeta379">MP4 · H.264 / AAC</b><span>Монтаж</span><b>'+s.width+' × '+s.height+'</b><span>Частота</span><b>'+fps().toFixed(2)+' fps</b><span>Длительность</span><b>'+tc(dur())+'</b></div><button id="export" class="wide primary" '+(!dur()?'disabled':'')+'>Добавить в очередь экспорта</button><button id="renderPreview" class="wide" '+(!dur()?'disabled':'')+'>Собрать лёгкий просмотр</button><h3>Очередь рендера</h3><div id="jobs"></div><h3>Проект</h3><a class="wide" id="downloadProject" href="'+BASE+'/files/projects/'+encodeURIComponent(data.project)+'">Скачать проект FilmCraft</a><button id="downloadBrief" class="wide">Скачать решения и заметки</button>'+hint('Рабочий лимит: 2 часа, 10 ГиБ на исходник, 2 ГиБ рабочих копий. Готовое видео скачиваешь и публикуешь самостоятельно.');
 }
 $('stageContent').innerHTML=h;
 document.querySelectorAll('#stageContent [data-upload]').forEach(b=>b.onclick=()=>chooseUpload(b.dataset.upload));
 bind('approveStage',()=>saveWorkflow({approved:{...(w.approved||{}),[page]:!w.approved?.[page]}}));
 bind('assignReference',()=>saveWorkflow({reference:asset,roles:{...(w.roles||{}),[asset]:'reference'}}));
 bind('move',()=>act('move',{clip:selected,track:val('moveTrack'),seconds:n('clipStart')}));
 bind('trimIn',()=>act('trim',{clip:selected,edge:'in',seconds:n('trimSeconds')}));
 bind('trimOut',()=>act('trim',{clip:selected,edge:'out',seconds:-n('trimSeconds')}));
 bind('applyGain',()=>act('gain',{clip:selected,db:n('gain')}));
 bind('applyColor',()=>act('color',{clip:selected,exposure:n('exposure'),contrast:n('contrast'),saturation:n('saturation')}));
 bind('applyTransform',()=>act('transform',{clip:selected,scale:n('scale'),x:n('positionX'),y:n('positionY')}));
 bind('pip',()=>act('transform',{clip:selected,scale:35,x:(seq().settings?.width||1920)*.78,y:(seq().settings?.height||1080)*.24}));
 bind('resetTransform',()=>act('transform',{clip:selected,scale:100,x:(seq().settings?.width||1920)/2,y:(seq().settings?.height||1080)/2}));
 bind('cleanAudio',()=>act('clean',{item:Number(val('audioSource'))}));
 bind('listenOriginal',()=>{asset=Number(val('audioSource'));renderSource();$('sourceVideo').play()});
 bind('acceptAudio',()=>{const sourceItem=Number(val('audioSource')),j=[...(data.jobs||[])].reverse().find(j=>j.kind==='clean'&&j.status==='done'&&j.sourceItem===sourceItem),item=w.audioCandidates?.[sourceItem]?.item??j?.item;if(!item)throw Error('Для этой дорожки ещё нет результата обработки');return saveWorkflow({audioAccepted:item,audioCandidates:{...(w.audioCandidates||{}),[sourceItem]:{item,accepted:true}}})});if($('audioSource'))$('audioSource').onchange=()=>{asset=Number(val('audioSource'));renderAssets();renderSource();renderInspector()};
 bind('analyzeSync',()=>act('syncAnalyze',{item:Number(val('syncAudio')),video:Number(val('syncVideo')),drift:$('syncDrift').checked,baseOffset:n('syncOffset')}));bind('correctSync',()=>{const id=Number(val('syncAudio')),j=[...(data.jobs||[])].reverse().find(j=>j.kind==='syncAnalyze'&&j.status==='done'&&j.sourceItem===id)||w.syncAnalysis;return act('syncCorrect',{item:id,analysis:j?.id})});
 bind('applySync',async()=>{const offset=n('syncOffset'),id=Number(val('syncAudio')),track=val('syncTrack'),mute=$('muteCamera')?.checked;const m=media().find(a=>a.item===id),v=clips().find(c=>c.kind==='video'&&c.item===Number(val('syncVideo')));if(!v)throw Error('Сначала добавь выбранное видео на таймлайн');if(track==='A1'&&mute)throw Error('Выбери A2 для нового звука или отключи выключение A1');const sourceStart=sec(v.sourceIn)-offset,delay=Math.max(0,-sourceStart),start=sec(v.start)+delay,sourceIn=Math.max(0,sourceStart),duration=Math.min(sec(v.duration)-delay,sec(m.duration)-sourceIn);if(duration<=0)throw Error('Записи не перекрываются с этим сдвигом');await act('add',{item:id,track,seconds:start,sourceIn,duration});await act('track',{track,muted:false});if(mute)await act('track',{track:'A1',muted:true});await saveWorkflow({sync:{item:id,seconds:offset,track}})});
 if($('syncTrack')&&$('syncAudio')){
  const updateCameraMute=()=>{const box=$('muteCamera'),camera=Number(val('syncVideo')),cameraPresent=(seq().audio?.[0]?.items||[]).some(c=>c.clip&&c.item===camera),onA1=val('syncTrack')==='A1';box.disabled=onA1||!cameraPresent;box.checked=!box.disabled};
  const targetForAudio=()=>{const m=Number(val('syncAudio')),root=Object.entries(w.audioCandidates||{}).find(([key,v])=>v.item===m)?.[0],role=w.roles?.[m]||w.roles?.[root]||'';if(role.startsWith('audio1'))$('syncTrack').value='A1';else if(role.startsWith('audio2'))$('syncTrack').value='A2';updateCameraMute()};
  $('syncTrack').onchange=updateCameraMute;$('syncVideo').onchange=updateCameraMute;$('syncAudio').onchange=targetForAudio;targetForAudio();
 }
 bind('saveBrief',()=>saveWorkflow({brief:val('brief'),compression:val('compression')}));
 bind('addNote',()=>{if(!val('newNote').trim())return;return saveWorkflow({notes:[...(w.notes||[]),{seconds:n('playhead'),text:val('newNote').slice(0,3000)}]})});
 if($('notesList'))for(const [i,note]of(w.notes||[]).entries()){const row=el('div',undefined,'noterow'),go=el('button',tc(note.seconds));go.onclick=()=>setCursor(note.seconds);const rm=el('button','×');rm.title='Убрать эту заметку';rm.onclick=()=>saveWorkflow({notes:w.notes.filter((_,ix)=>ix!==i)});row.append(go,el('span',note.text+(note.removed?' · вырезанный отрезок':'')),rm);$('notesList').append(row)}
 bind('saveInsert',()=>saveWorkflow({insertPrompt:val('insertPrompt')}));bind('placeInsert',()=>add('overwrite','V2'));
 bind('showReference',()=>{asset=w.reference;renderAssets();renderSource()});
 bind('saveVoice',()=>saveWorkflow({language:val('language')}));
 bind('savePackage',()=>saveWorkflow({titleIdeas:val('titleIdeas').split('\n').slice(0,12).join('\n'),coverBrief:val('coverBrief')}));
 bind('downloadFrame',()=>downloadURL(data.frame?.url,'frame.png'));
 bind('downloadBrief',()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(w,null,2)],{type:'application/json'}));downloadURL(url,'frame-notes.json');setTimeout(()=>URL.revokeObjectURL(url),1000)});
 bind('export',()=>render(false));bind('renderPreview',()=>render(true));
 if($('jobs'))renderJobs(data.jobs||[]);
 renderAIControls();
}
function transformHTML(c){
 const motion=c.effects?.find(e=>e.effect==='motion');const scale=Number(String(motion?.params?.scale?.value||'Float(100)').replace(/^Float\((.*)\)$/,'$1'))||100;
 const position=String(motion?.params?.position?.value||'').match(/x:\s*([-\d.]+).*y:\s*([-\d.]+)/);return '<h3>Трансформация</h3>'+field('Масштаб, %','scale',scale,'number','min="1" max="400"')+field('Позиция X','positionX',position?Number(position[1]):(seq().settings?.width||1920)/2)+field('Позиция Y','positionY',position?Number(position[2]):(seq().settings?.height||1080)/2)+'<button id="applyTransform" class="wide">Применить</button><div class="row"><button id="pip">Картинка в картинке</button><button id="resetTransform">Сбросить</button></div>';
}
function downloadURL(url,name){if(!url)return;const a=el('a');a.href=url;a.download=name;a.click()}
function setPage(next){page=next;document.querySelectorAll('[data-page]').forEach(b=>{b.classList.toggle('selected',b.dataset.page===page);if(b.dataset.page===page)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current')});$('workspace').classList.remove('hideinspect');$('toggleInspector').setAttribute('aria-pressed','true');renderInspector()}
function renderJobState(jobs){const running=jobs.some(j=>j.status==='running');$('preview').disabled=running||busy;const ex=$('export');if(ex)ex.disabled=running||busy||!dur();if(running&&!polling)pollJobs();if($('jobs'))renderJobs(jobs)}
function renderJobs(jobs){if(!$('jobs'))return;$('jobs').replaceChildren(...jobs.slice(-5).reverse().map(j=>{const e=el('div',undefined,'job'),names={objectProxy:'Подготовка просмотра',preview:'Просмотр',export:'Экспорт',clean:'Обработка звука',syncAnalyze:'Поиск синхронизации','ai:generateImage':'Изображение · Ася','syncCorrect':'Коррекция дрейфа','ai:translateTracks':'Переводы языковых дорожек','ai:dubFull':'Мультиязычный дубляж','ai:generateVideo':'Видео · Wan','ai:speech':'Речь · VoxCPM2','ai:metrics':'Измерение LUFS/true peak','ai:transcribe':'Расшифровка','ai:analyze':'Разбор содержания','ai:insertPlan':'Места вставок','ai:translate':'Перевод','ai:research':'Ресёрч и названия','ai:covers':'Обложки','ai:dub':'Дубляж','ai:resumeDub':'Проверка дубляжа','ai:colorMatch':'Цвет по референсу','ai:cutPreview':'Просмотр стыка','ai:applyCuts':'Применение вырезок','ai:applyInserts':'Размещение вставок','ai:checkProviders':'Проверка подключений'};e.append(el('span',(names[j.kind]||j.kind)+' · '+({running:'в работе…',done:'готово',error:'ошибка'}[j.status])));if(j.total>1)e.append(el('p',String(j.progress||0)+' / '+j.total+' готово'));if(j.pcProgress){const p=j.pcProgress,units=j.kind==='ai:dubFull'?'фраз':j.kind==='ai:analyze'?'фрагментов':'этапов';const phase={waitingFrameGPU:'Ожидание видеокарты Frame','load-audio-model':'Загрузка аудиомодели',listen:'Прослушивание',finished:'Проверка результата','load-voice-model':'Загрузка голосовой модели'}[p.phase]||String(p.phase||'').replace('synthesise-','Озвучка · ').replace('-phrase-',' · фраза ').replace('assemble-','Сборка · ').replace('loudness-','Громкость · ').replace('upload-','Передача · ').replace('verify-object-','Проверка записи · ');e.append(el('p',phase+' · '+(p.frame||0)+'/'+(p.frames||j.total)+' '+units+' · '+Math.round(p.elapsed||0)+' с','hint'))}if(j.status==='error')e.append(el('p',j.error));if(j.status==='done'&&j.url){const a=el('a',j.kind==='clean'?'Открыть обработанный WAV':j.kind==='ai:transcribe'?'Скачать субтитры':j.kind==='ai:dub'?'Скачать дубляж':'Скачать файл');a.href=j.url;a.download=j.url.split('/').pop().split('?')[0];e.append(a)}return e}));if(!jobs.length)$('jobs').append(el('p','Очередь пуста','hint'));if(jobs.some(j=>j.status==='running'&&['ai:analyze','ai:transcribe','ai:translate','ai:translateTracks','ai:dubFull','ai:research','ai:insertPlan','ai:covers','ai:generateImage'].includes(j.kind))){const cancel=el('button','Отменить ожидание результата');cancel.onclick=()=>aiAction('aiCancel');$('jobs').append(cancel)}}
async function pollJobs(){polling=true;try{while(true){await new Promise(r=>setTimeout(r,1500));const d=await api('jobs');data.jobs=d.jobs;if($('jobs'))renderJobs(d.jobs);if(!d.jobs.some(j=>j.status==='running')){update(await api('state'));const last=d.jobs.at(-1);note(last?.status==='error'?last.error:'Готово',last?.status==='error');break}}}catch(e){note(e.message,true)}finally{polling=false}}
async function act(action,params={}){if(busy)return;busy=true;note('Применение…');stopPlayback();try{const d=await api('action',{action,...params});busy=false;update(d);note(['clean','syncAnalyze','syncCorrect'].includes(action)?'Задача запущена':'Сохранено');if(dur()&&!['clean','syncAnalyze','workflow','providersSave','aiJob','aiDecision','aiTranscript','aiSelectCovers'].includes(action))await showFrame()}catch(e){renderTimeline();note(e.message,true);throw e}finally{busy=false}}
async function showFrame(){if(!dur())return;if(frameBusy){frameAgain=true;return}frameBusy=true;try{const at=n('playhead');const f=await api('frame',{seconds:Math.min(at,Math.max(0,dur()-1/fps()))});if(Math.abs(n('playhead')-at)<1/fps()){data.frame=f;$('frame').src=f.url;$('frame').hidden=false;$('video').hidden=true;$('empty').hidden=true}}finally{frameBusy=false;if(frameAgain){frameAgain=false;showFrame().catch(e=>note(e.message,true))}}}
function stopPlayback(){clearInterval(reverseTimer);reverseTimer=null;$('video').pause();$('play').textContent='▶'}
async function play(direction=1){focusedSource=false;if(direction<0){stopPlayback();reverseTimer=setInterval(()=>{if(n('playhead')<=0)return stopPlayback();setCursor(n('playhead')-.2)},250);return}
 clearInterval(reverseTimer);reverseTimer=null;if(!data.preview||data.preview.revision!==data.revision){autoPlay=true;await render(true);return}
 $('video').hidden=false;$('frame').hidden=true;$('empty').hidden=true;
 if($('video').paused){$('video').currentTime=n('playhead');$('video').playbackRate=1;await $('video').play();$('play').textContent='Ⅱ'}else{stopPlayback()}
}
async function render(preview){try{stopPlayback();note(preview?'Собирается просмотр…':'Начат экспорт…');await api('render',{preview});update(await api('state'))}catch(e){autoPlay=false;note(e.message,true)}}
function chooseUpload(role){uploadRole=role;$('filePicker').accept=role.startsWith('audio')?'audio/*':role==='video'?'video/*':'video/*,image/png,image/jpeg';$('filePicker').click()}
$('filePicker').onchange=e=>uploadFiles([...e.target.files]).finally(()=>e.target.value='');
async function uploadFiles(files){for(const file of files){try{if(file.size>data.limitBytes)throw Error('Файл должен быть не больше 64 МиБ');const before=new Set(media().map(m=>m.item));note('Загрузка '+file.name+'…');const r=await fetch(BASE+'/api/upload',{method:'POST',headers:{'X-Frame-CSRF':csrf,'X-File-Name':encodeURIComponent(file.name)},body:file});const d=await r.json();if(!r.ok)throw Error(d.error);update(d);const added=media().filter(m=>!before.has(m.item));if(added.length){asset=added[0].item;const roles={...(wf().roles||{})};for(const m of added)roles[m.item]=uploadRole;await saveWorkflow({roles,...(uploadRole==='reference'?{reference:asset}:uploadRole==='coverReference'?{coverReference:asset}:{})});$('addTrack').value=uploadRole==='audio1'?'A1':uploadRole==='audio2'?'A2':uploadRole==='insert'?'V2':'V1';renderSource();renderInspector()}note('Добавлен '+file.name)}catch(e){note(e.message,true);break}}}
$('pool').ondragover=e=>{if(e.dataTransfer.types.includes('Files')){e.preventDefault();$('pool').classList.add('dropactive')}};
$('pool').ondragleave=()=>$('pool').classList.remove('dropactive');$('pool').ondrop=e=>{e.preventDefault();$('pool').classList.remove('dropactive');uploadRole='video';uploadFiles([...e.dataTransfer.files])};
document.querySelectorAll('[data-upload]').forEach(b=>b.onclick=()=>chooseUpload(b.dataset.upload));
bind('upload',()=>chooseUpload('video'));bind('importEmpty',()=>chooseUpload('video'));$('search').oninput=renderAssets;
document.querySelectorAll('[data-bin]').forEach(b=>b.onclick=()=>{bin=b.dataset.bin;document.querySelectorAll('[data-bin]').forEach(x=>x.classList.toggle('selected',x===b));renderAssets()});
document.querySelectorAll('[data-page]').forEach(b=>b.onclick=()=>setPage(b.dataset.page));
bind('addClip',()=>add());bind('insertClip',()=>add('insert'));bind('appendClip',()=>add('append'));
bind('split',()=>act('split',{seconds:n('playhead')}));bind('deleteClip',()=>current()&&act('delete',{clip:selected}));bind('deleteRipple',()=>current()&&act('delete',{clip:selected,ripple:true}));
bind('undo',()=>act('undo'));bind('redo',()=>act('redo'));bind('save',()=>act('save'));
bind('newProject',async()=>{selected=null;asset=null;videoURL='';sourceURL='';$('video').hidden=true;$('frame').hidden=true;$('empty').hidden=false;await act('new');$('projectDialog').close()});
bind('openProject',async()=>{selected=null;asset=null;videoURL='';sourceURL='';$('video').hidden=true;$('frame').hidden=true;$('empty').hidden=false;await act('open',{name:$('projectPicker').value});$('projectDialog').close()});
bind('projectsMenu',()=>$('projectDialog').showModal());document.querySelectorAll('[data-close]').forEach(b=>b.onclick=()=>$(b.dataset.close).close());
bind('help',()=>$('helpDialog').showModal());bind('closeHelp',()=>$('helpDialog').close());
for(const [id,cls]of [['togglePool','hidepool'],['toggleInspector','hideinspect']])$(id).onclick=()=>{$('workspace').classList.toggle(cls);$(id).setAttribute('aria-pressed',!$('workspace').classList.contains(cls));setTimeout(renderTimeline,0)};
$('toggleSource').onclick=()=>{const on=$('sourcePanel').style.display!=='none';$('sourcePanel').style.display=on?'none':'';$('toggleSource').setAttribute('aria-pressed',String(!on))};
$('selectTool').onclick=()=>setTool('select');$('bladeTool').onclick=()=>setTool('blade');
function setTool(next){tool=next;$('selectTool').classList.toggle('selected',tool==='select');$('bladeTool').classList.toggle('selected',tool==='blade');$('toolHint').textContent=tool==='select'?'A · выбор / перетаскивание':'B · разрезать все дорожки щелчком'}
$('snap').onclick=()=>{snapping=!snapping;$('snap').setAttribute('aria-pressed',snapping)};
$('zoom').oninput=()=>{zoom=n('zoom');renderTimeline()};$('fit').onclick=()=>{zoom=0;$('zoom').value=0;renderTimeline()};
$('rulerTicks').onpointerdown=e=>{focusedSource=false;setCursor((e.clientX-$('rulerTicks').getBoundingClientRect().left)/pxs())};
$('seek').oninput=()=>setCursor(n('seek'));$('playhead').onchange=()=>setCursor(n('playhead'));
bind('showFrame',showFrame);bind('preview',()=>render(true));bind('play',()=>play());
bind('toStart',()=>setCursor(0));bind('toEnd',()=>setCursor(dur()));bind('stepBack',()=>setCursor(n('playhead')-1/fps()));bind('stepForward',()=>setCursor(n('playhead')+1/fps()));
$('video').ontimeupdate=()=>{if(!$('video').hidden){$('playhead').value=$('video').currentTime;syncCursor()}};$('video').onended=()=>{$('play').textContent='▶'};
$('sourceVideo').ontimeupdate=updateSourceTC;
$('sourceSeek').oninput=()=>{$('sourceVideo').currentTime=n('sourceSeek');focusedSource=true;updateSourceTC()};
$('sourcePanel').onpointerdown=()=>{focusedSource=true};
bind('sourceBack',()=>{$('sourceVideo').currentTime=0;updateSourceTC()});
bind('sourcePlay',()=>{focusedSource=true;$('sourceVideo').paused?$('sourceVideo').play():$('sourceVideo').pause()});
bind('markIn',()=>{sourceIn=$('sourceVideo').currentTime||0;if(sourceOut!==null&&sourceOut<=sourceIn)sourceOut=null;updateSourceTC()});
bind('markOut',()=>{sourceOut=$('sourceVideo').currentTime||sec(source()?.duration);if(sourceOut<=sourceIn)throw Error('Выход должен быть позже входа');updateSourceTC()});
bind('logout',async()=>{const r=await fetch(BASE+'/logout',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({csrf:data.authCsrf})});if(!r.ok)throw Error('Не удалось выйти');stopPlayback();$('sourceVideo').pause();location.replace(BASE+'/')});
document.addEventListener('keydown',e=>{
 if(e.target.getAttribute('role')==='separator'||e.isComposing||e.target.matches('input,select,textarea,[contenteditable=true]')||document.querySelector('dialog[open]'))return;
 const cmd=e.ctrlKey||e.metaKey,k=e.key.toLowerCase();let fn;
 if(e.altKey&&/^[0-9]$/.test(k))fn=()=>setPage(PAGES[k==='0'?9:Number(k)-1]);
 else if(cmd&&k==='z')fn=()=>act(e.shiftKey?'redo':'undo');
 else if(cmd&&k==='s')fn=()=>act('save');
 else if(cmd&&k==='i')fn=()=>chooseUpload('video');
 else if(cmd&&k==='b')fn=()=>act('split',{seconds:n('playhead')});
 else if(e.key==='Delete'||e.key==='Backspace')fn=()=>current()&&act('delete',{clip:selected,ripple:e.shiftKey});
 else if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key))fn=()=>{if(focusedSource&&source()&&source().type!=='Still'){const v=$('sourceVideo');v.currentTime=e.key==='Home'?0:e.key==='End'?v.duration:Math.max(0,v.currentTime+(e.key==='ArrowRight'?1:-1)*(e.shiftKey?10:1)/fps());updateSourceTC()}else setCursor(e.key==='Home'?0:e.key==='End'?dur():n('playhead')+(e.key==='ArrowRight'?1:-1)*(e.shiftKey?10:1)/fps())};
 else if(e.code==='Space')fn=()=>focusedSource?$('sourcePlay').click():play();
 else if(k==='k')fn=()=>{stopPlayback();$('sourceVideo').pause()};
 else if(k==='l')fn=()=>{if(!$('video').paused&&!$('video').hidden)$('video').playbackRate=Math.min(4,$('video').playbackRate*2);else return play()};
 else if(k==='j')fn=()=>play(-1);
 else if(k==='i')fn=()=>$('markIn').click();
 else if(k==='o')fn=()=>$('markOut').click();
 else if(e.key==='F9')fn=()=>add('insert');
 else if(e.key==='F10')fn=()=>add();
 else if(k==='e')fn=()=>add('append');
 else if(k==='a')fn=()=>setTool('select');
 else if(k==='b')fn=()=>setTool('blade');
 else if(k==='n')fn=()=>$('snap').click();
 else if(k==='z'&&e.shiftKey)fn=()=>$('fit').click();
 else if(['+','=','-'].includes(k))fn=()=>{zoom=Math.max(0,Math.min(100,zoom+(k==='-'?-5:5)));$('zoom').value=zoom;renderTimeline()};
 if(fn){e.preventDefault();Promise.resolve(fn()).catch(err=>note(err.message,true))}
});
window.addEventListener('resize',()=>{if(data)renderTimeline()});window.addEventListener('pagehide',stopPlayback);window.addEventListener('pageshow',e=>{if(e.persisted)location.reload()});
api('state').then(d=>{update(d);note('');if(dur())return showFrame()}).catch(e=>note(e.message,true));
/* Original voice workflow #355: explicit stage actions, review and isolated provider setup. */
function aiData(){return data?.ai||{}}
function aiButton(id,label,provider,enabled=true){provider=provider==='openai'?'asya':provider==='elevenlabs'?'pc':provider;const localPending=false;if(id==='dubAI')provider='pc';const ready=!localPending&&(!provider||data?.connections?.[provider]);return '<button id="'+id+'" class="wide '+(ready?'':'needs-provider')+'" '+(!ready||!enabled?'disabled':'')+' title="'+(!ready?(localPending?'Локальная генерация ещё не прошла проверку':provider==='asya'?'Связь с Асей временно недоступна':'Ожидается подключённый ПК'):'')+'">'+label+'</button>'}
function aiHint(provider){provider=provider==='openai'?'asya':provider==='elevenlabs'?'pc':provider;return data?.connections?.[provider]?'':'<p class="hint">'+(provider==='asya'?'Связь с Асей временно недоступна.':'ПК пока не готов к этой операции. Задание не будет отправлено в платный API.')+'</p>'}
function aiJob(kind,params={}){return api('action',{action:'aiJob',kind,...params}).then(d=>{update(d);note('Этап запущен');return d}).catch(e=>note(e.message,true))}
function aiAction(action,params={}){return api('action',{action,...params}).then(d=>{update(d);return d}).catch(e=>{note(e.message,true);throw e})}
function renderAIControls(){
 if(!data)return;const a=aiData(),w=wf(),c=current(),s=$('stageContent');s.querySelectorAll('.pending').forEach(e=>e.remove());if(page==='voice'){const approvalNode=s.querySelector('.approval');s.replaceChildren();if(approvalNode)s.append(approvalNode)}
 let html='',top=false;
 if(page==='story'){
  top=true;html='<h3>Расшифровка и смысловой монтаж</h3>'+aiButton('transcribeAI','1. Расшифровать с таймкодами','elevenlabs',!!dur())+aiHint('elevenlabs')+'<div class="row"><button id="openTranscript" '+(!a.transcript?'disabled':'')+'>Расшифровка</button><button id="importTranscript">Импорт субтитров</button></div>'+aiButton('analyzeAI','2. Ася: разобрать и предложить вырезки','openai',!!a.transcript&&!a.transcript.stale)+aiHint('openai');
  if(a.transcript?.stale)html+=hint('Монтаж изменился — расшифровку нужно обновить.');
  html+='<label class="consent"><input id="listenSpeech" type="checkbox" checked>Учитывать звучание всей речи (локальный аудиоанализ → решения Аси)</label>';if(a.analysis){html+='<button id="openCuts" class="wide">3. Рассмотреть вырезки · '+(a.analysis.cuts?.length||0)+'</button>'+hint(esc(a.analysis.summary||''))+'<button id="applyAICuts" class="wide primary" '+(a.analysis.stale||a.analysis.applied||!a.analysis.cuts?.some(c=>c.decision==='approved')?'disabled':'')+'>Применить только принятые вырезки</button>';if(a.analysis.stale)html+=hint('Предложения относятся к предыдущему монтажу. Повторный анализ не запускается сам.');html+=hint('Видеоконтекст: '+a.analysis.sampledFrames+' кадров с таймкодами. Это выборка, не непрерывный просмотр.')}
  html+='<h3>Не вырезать</h3>'+field('Начало, с','protectIn',n('playhead').toFixed(2),'number','min="0" step=".04"')+field('Конец, с','protectOut',Math.min(dur(),n('playhead')+2).toFixed(2),'number','min="0" step=".04"')+'<button id="protectRange" class="wide">Защитить этот интервал</button><div id="protectedList"></div><div id="jobs"></div>';
 }
 if(page==='color'){
  top=true;html='<h3>Цвет по референсу</h3>'+aiButton('matchReference','Подобрать цвет к текущему кадру',null,c?.kind==='video'&&!!w.reference);
  if(!w.reference)html+=hint('Загрузи референс или выбери файл в медиатеке → Материалы → использовать как референс цвета.');
  html+=field('Сила сопоставления','matchStrength',.55,'number','min="0" max="1" step=".05"')+'<label class="field">Сдерживать сдвиг тёплых оттенков<input id="matchWarmGuard" type="checkbox" checked></label>';
  if(a.colorMatch){html+='<a href="'+esc(a.colorMatch.url)+'" target="_blank" rel="noopener"><img class="look-comparison" src="'+esc(a.colorMatch.url)+'" alt="Слева исходный кадр, справа проба цвета"></a>'+hint('Слева до / справа после. Нативный3D LUT 17³, сила '+Math.round((a.colorMatch.strength||0)*100)+'%. Сдерживание тёплых оттенков — не распознавание кожи. Проверь лицо и белые/чёрные точки.')+'<a class="download-link" href="'+esc(a.colorMatch.lutUrl)+'" download>Скачать LUT</a><button id="applyMatchedColor" class="wide" '+(a.colorMatch.stale?'disabled':'')+'>Принять цвет</button>'}
  html+='<h3>Улучшение изображения</h3><label class="field">Снижение видеошума<input id="qualityDenoise" type="checkbox" '+(w.exportProfile?.denoise?'checked':'')+'></label>'+field('Резкость','qualitySharpness',w.exportProfile?.sharpness??.25,'number','min="0" max=".6" step=".05"')+'<label class="field">Размер<select id="qualitySize">'+[[0,'Исходный'],[2048,'Длинная сторона 2048'],[2560,'Длинная сторона 2560']].map(([v,t])=>'<option value="'+v+'" '+(v===(w.exportProfile?.maxSide??0)?'selected':'')+'>'+t+'</option>').join('')+'</select></label><button id="applyQuality" class="wide">Применить и обновить кадр</button>'+hint('Умеренные фильтры и Lanczos-масштабирование, не ИИ-восстановление деталей. Эти настройки действуют в просмотре и экспорте. Оцени лицо, мелкие детали и шум до принятия.')+'<div id="jobs"></div>';
 }
 if(page==='insert'){
  top=true;html='<h3>Вставки по смыслу</h3>'+aiButton('planInsertsAI','Предложить места для загруженных вставок','openai',!!a.transcript&&!a.transcript.stale)+aiHint('openai');
  if(a.insertPlan){html+='<div id="insertSuggestions"></div><button id="applyInsertsAI" class="wide primary" '+(a.insertPlan.stale||a.insertPlan.applied||!a.insertPlan.placements?.some(x=>x.decision==='approved')?'disabled':'')+'>Применить принятые вставки</button>';if(a.insertPlan.stale)html+=hint('Монтаж изменился — места нужно пересчитать.')}
  html+='<h3>Смена компоновки</h3>'+field('Длительность, с','swapDuration',Math.min(3,Math.max(.1,dur()-n('playhead'))),'number','min=".1" max="7200" step=".04"')+'<button id="swapInsert" class="wide" '+(!source()||source().type==='Audio'?'disabled':'')+'>Вставка основная · автор в окне</button>'+hint('Выбранный материал займёт V1; автор перейдёт на V2 в пределах этого отрезка. Звук остаётся прежним. V2 должна быть свободна.')+'<div id="jobs"></div>';
 }
 if(page==='voice'){
  top=true;const langs=[['en','English'],['es','Español'],['zh','中文 · Mandarin'],['pt','Português'],['de','Deutsch']],tracks=a.translations?.tracks||{};
  html='<h3>Языковые дорожки для YouTube</h3>'+hint('Ася переводит весь монтаж. Просмотри каждый перевод, затем ПК создаст отдельные WAV 48 кГц и SRT с длительностью ролика. Основной звук и монтаж не заменяются. Загрузка в YouTube — вручную, если каналу доступно добавление аудиодорожек в Studio.')+'<fieldset class="language-picks"><legend>Языки</legend>'+langs.map(([id,name])=>'<label><input type="checkbox" name="dubLanguage" value="'+id+'" '+(id==='en'?'checked':'')+'>'+name+'</label>').join('')+'</fieldset>'+aiButton('translateTracksAI','Ася: подготовить переводы','openai',!!a.transcript&&!a.transcript.stale)+'<div id="translationTracks"></div>';
  if(a.translations?.stale)html+=hint('Переводы устарели после изменения звука или расшифровки — подготовь их заново.');
  html+='<h3>Свой голос</h3>'+select('Чистая запись одного голоса','dubVoiceItem',media().filter(m=>m.type!=='Still'),asset)+field('Начало референса, с','dubVoiceStart',0,'number','min="0" max="7200" step=".1"')+hint('Используются следующие 12 секунд, не короче 3 с. Без музыки и других голосов.')+textArea('dubRefText','','Точный текст этих 12 секунд (необязательно, помогает сохранить тембр)')+'<label class="consent"><input id="ownVoiceConsent" type="checkbox">Это мой голос, разрешаю использовать запись для выбранных дорожек</label>'+aiButton('dubFullAI','Создать выбранные языковые дорожки','elevenlabs',!!a.translations&&!a.translations.stale)+hint('Qwen3-TTS на ПК. Фразы подгоняются без изменения высоты голоса; сильные изменения темпа отмечаются для проверки. Липсинк не выполняется.')+'<div id="dubTracks"></div><div id="jobs"></div>';
 }
 if(page==='package'){
  top=true;html='<h3>Ресёрч, названия и концепции</h3><label class="field">Число вариантов<select id="candidateCount"><option value="9">9</option><option value="12">12</option></select></label>'+aiButton('researchAI','Ася: исследовать и предложить варианты','openai',!!dur())+aiHint('openai');
  if(w.selectedTitle)html+=hint('Выбрано: '+esc(w.selectedTitle));if(a.research){html+='<button id="openTitles" class="wide">Названия и идеи обложек · '+(a.research.titles?.length||0)+'</button>';if(a.research.stale)html+=hint('Контекст изменился — варианты сохранены, но требуют пересмотра.')}
  html+='<h3>Обложки в твоём стиле</h3><button data-upload="coverReference" class="wide">Загрузить референс обложки</button><button id="assignCoverRef" class="wide" '+(!source()?'disabled':'')+'>Выбранный файл → референс обложки</button>'+hint('За основу берётся текущий кадр. Стиль референса Ася учитывает в концепциях. Изображение создаётся через Асю / OpenClaw Images по кадру автора и референсу стиля. Надпись из концепции накладывается обычным текстом после генерации; проверь композицию. Начни с одной пробы.');
  html+='<div class="row">'+aiButton('coverDraftAI','1 пробная','openai',!!a.research&&!a.research.stale)+aiButton('coversAI','Все '+(a.research?.covers?.length||9),'openai',!!a.research&&!a.research.stale)+'</div>';
  if(a.gallery?.images?.length)html+='<button id="openGallery" class="wide">Посмотреть обложки · '+a.gallery.images.length+'</button>';
  html+=hint('Смысловые задачи выполняет Ася через существующий OpenClaw. Изображения и обложки — через Асю; голос и короткое видео — на ПК.')+'<div id="jobs"></div>';
 }
 if(!html)return;
 const block=el('section',undefined,'ai-stage');block.innerHTML=html;
 // Existing queue element is replaced by the stage-specific one, not duplicated.
 s.querySelectorAll('#jobs').forEach(e=>e.remove());
 if(top)s.prepend(block);else s.append(block);
 s.querySelectorAll('[data-ai-settings]').forEach(b=>b.onclick=openProviders);
 s.querySelectorAll('[data-upload="coverReference"]').forEach(b=>b.onclick=()=>chooseUpload('coverReference'));
 bind('transcribeAI',()=>aiJob('transcribe'));bind('analyzeAI',()=>aiJob('analyze',{sound:$('listenSpeech')?.checked!==false}));
 bind('openTranscript',()=>openTranscript(false));bind('openTranslation',()=>openTranscript(true));
 bind('importTranscript',()=>$('transcriptFile').click());
 bind('openCuts',renderCuts);bind('applyAICuts',()=>aiJob('applyCuts'));
 bind('protectRange',async()=>{const start=n('protectIn'),end=n('protectOut');if(end<=start)throw Error('Конец должен быть позже начала');await saveWorkflow({protectedRanges:[...(w.protectedRanges||[]),{start,end,reason:'Отмечено автором — не вырезать'}]})});
 if($('protectedList'))for(const [i,r]of(w.protectedRanges||[]).entries()){const row=el('div',undefined,'noterow');row.append(el('span',tc(r.start)+' → '+tc(r.end)));const rm=el('button','×');rm.title='Снять защиту';rm.onclick=()=>saveWorkflow({protectedRanges:w.protectedRanges.filter((_,ix)=>ix!==i)});row.append(rm);$('protectedList').append(row)}
 bind('matchReference',()=>aiJob('colorMatch',{clip:selected,seconds:n('playhead'),strength:n('matchStrength'),warmGuard:$('matchWarmGuard').checked}));
 bind('applyMatchedColor',()=>act('applyColorMatch'));
 bind('applyQuality',async()=>{await saveWorkflow({exportProfile:{...(wf().exportProfile||{}),denoise:$('qualityDenoise').checked,sharpness:n('qualitySharpness'),maxSide:n('qualitySize')}});await showFrame()});
 bind('planInsertsAI',()=>aiJob('insertPlan'));
 bind('applyInsertsAI',()=>aiJob('applyInserts'));bind('swapInsert',()=>act('swapInsert',{item:asset,seconds:n('playhead'),duration:n('swapDuration')}));
 if($('insertSuggestions'))for(const row of a.insertPlan?.placements||[]){const e=el('div',undefined,'suggestion');e.append(el('p',tc(row.start)+' · '+row.duration.toFixed(1)+' с · '+(row.layout==='pip'?'картинка в картинке':row.layout==='swap'?'вставка основная, автор сверху':'весь кадр')),el('p',row.reason,'hint'));const actions=el('div',undefined,'row');for(const [label,decision]of[['Принять','approved'],['Оставить без вставки','rejected']]){const b=el('button',(row.decision===decision?'✓ ':'')+label);b.disabled=a.insertPlan.stale||a.insertPlan.applied;b.onclick=()=>aiAction('aiDecision',{id:row.id,decision,kind:'insertPlan'}).catch(()=>{});actions.append(b)}e.append(actions);$('insertSuggestions').append(e)}
 if(page==='voice')renderLanguageTracks();
 bind('translateAI',async()=>{const language=val('aiLanguage');await saveWorkflow({language});return aiJob('translate',{language})});
 bind('dubAI',async()=>{if(!$('ownVoiceConsent').checked)throw Error('Сначала подтверди использование собственного голоса');const language=val('aiLanguage');await saveWorkflow({language});return aiJob('dub',{language,voiceConsent:true})});
 bind('resumeDubAI',()=>aiJob('resumeDub',{language:a.dub.language}));
 bind('useDub',async()=>{const m=media().find(m=>m.item===a.dub.item);if(!m)throw Error('Дубляж недоступен');await act('add',{item:m.item,track:'A2',seconds:0,sourceIn:0,duration:Math.min(dur(),sec(m.duration))});await act('track',{track:'A1',muted:true})});
 bind('researchAI',()=>aiJob('research',{count:n('candidateCount'),seconds:n('playhead')}));
 bind('openTitles',renderTitles);
 bind('assignCoverRef',()=>saveWorkflow({coverReference:asset,roles:{...(w.roles||{}),[asset]:'coverReference'}}));
 bind('coverDraftAI',()=>aiJob('covers',{count:1,seconds:n('playhead')}));
 bind('coversAI',()=>aiJob('covers',{count:a.research?.covers?.length||9,seconds:n('playhead')}));
 bind('openGallery',renderGallery);
 renderJobs(data.jobs||[]);
 
}
function openProviders(){
 const caps=data?.connections||{};
 $('providerStatus').textContent='Ася: '+(caps.asya?'подключена через OpenClaw':'нет свежего соединения')+' · ПК: '+(caps.pc?'готов':'ожидает подключения');
 $('providerCheck').textContent='Смысловой монтаж, перевод, названия и идеи — Ася (Sol/high). Расшифровка и генерация медиа — локально на ПК. Отдельные платные API не используются.';
 $('providersDialog').showModal();
}
bind('aiSettings',openProviders);
bind('checkProviders',async()=>{await aiJob('checkProviders');$('providersDialog').close()});
function openTranscript(translation){
 const a=aiData(),doc=translation?a.translation:a.transcript;if(!doc)return;
 $('transcriptHeading').textContent=translation?'Перевод · '+doc.language:'Расшифровка с таймкодами';$('saveTranscript').hidden=translation;$('transcriptRows').replaceChildren();
 for(const [i,segment]of(doc.segments||[]).entries()){
  const row=el('div',undefined,'transcript-row');row.dataset.index=i;
  const go=el('button',tc(segment.start));go.onclick=()=>{$('transcriptDialog').close();setCursor(segment.start)};
  const fields=el('div',undefined,'transcript-times');for(const [k,label]of[['start','Вход, с'],['end','Выход, с']]){const lab=el('label',label),inp=el('input');inp.type='number';inp.step='.01';inp.min='0';inp.value=segment[k];inp.dataset.time=k;inp.disabled=translation;lab.append(inp);fields.append(lab)}
  const text=el('textarea');text.value=segment.text;text.rows=2;text.readOnly=translation;row.append(go,fields,text);$('transcriptRows').append(row);
 }
 $('transcriptDialog').showModal();
}
bind('saveTranscript',async()=>{const segments=[...$('transcriptRows').children].map(row=>({start:Number(row.querySelector('[data-time=start]').value),end:Number(row.querySelector('[data-time=end]').value),text:row.querySelector('textarea').value}));if(new TextEncoder().encode(JSON.stringify(segments)).length>58000)throw Error('Слишком большой текст для текущего лимита проекта');await aiAction('aiTranscript',{segments});$('transcriptDialog').close()});
$('transcriptFile').onchange=async e=>{
 try{const f=e.target.files[0];if(!f)return;if(f.size>1000000)throw Error('Файл субтитров слишком большой');const raw=(await f.text()).replace(/^\uFEFF/,'').replace(/\r/g,'');let segments;
 if(f.name.toLowerCase().endsWith('.json'))segments=JSON.parse(raw);
 else{
  const stamp=s=>{const a=s.replace(',','.').split(':').map(Number);return a.length===3?a[0]*3600+a[1]*60+a[2]:a[0]*60+a[1]};
  segments=raw.split(/\n\s*\n/).flatMap(block=>{const lines=block.split('\n'),i=lines.findIndex(l=>l.includes('-->'));if(i<0)return[];const pair=lines[i].split('-->').map(s=>s.trim().split(/\s/)[0]);return [{start:stamp(pair[0]),end:stamp(pair[1]),text:lines.slice(i+1).join(' ').replace(/<[^>]+>/g,'')}]});
 }
 if(new TextEncoder().encode(JSON.stringify(segments)).length>58000)throw Error('Слишком много субтитров для текущего лимита');await aiAction('aiTranscript',{segments});note('Субтитры импортированы')
 }catch(err){note(err.message,true)}finally{e.target.value=''}
};
function renderCuts(){
 const a=aiData().analysis;if(!a)return;$('cutsRows').replaceChildren();
 $('cutsStatus').textContent=a.applied?'Принятые вырезки применены':a.stale?'Монтаж изменился. Эти предложения нужно обновить.':'Ни одна вырезка не применяется без твоего решения.';
 const summary=el('p',a.summary,'info');$('cutsRows').append(summary);
 for(const chapter of a.outline||[]){const row=el('div',undefined,'chapterrow'),go=el('button',tc(chapter.start));go.onclick=()=>{$('cutsDialog').close();setCursor(chapter.start)};row.append(go,el('b',chapter.title),el('span',chapter.summary));$('cutsRows').append(row)}
 for(const cut of a.cuts||[]){
  const card=el('article',undefined,'cutcard '+cut.decision);card.dataset.cut=cut.id;card.append(el('h3',tc(cut.start)+' → '+tc(cut.end)+' · '+(cut.end-cut.start).toFixed(2)+' с'),el('p',cut.reason,'info'));if(cut.quote)card.append(el('blockquote',cut.quote));
  if(cut.blocked)card.append(el('p','Защищённый интервал: удаление запрещено','blockedlabel'));
  const fields=el('div',undefined,'row');for(const [k,label]of[['start','Начало, с'],['end','Конец, с']]){const lab=el('label',label),inp=el('input');inp.type='number';inp.step='.04';inp.value=cut[k];inp.dataset.edge=k;inp.disabled=a.stale||a.applied;lab.append(inp);fields.append(lab)}card.append(fields);
  const actions=el('div',undefined,'row');
  for(const [label,decision]of[['Убрать','approved'],['Оставить','rejected']]){const b=el('button',(cut.decision===decision?'✓ ':'')+label);b.disabled=a.stale||a.applied||(cut.blocked&&decision==='approved');b.onclick=()=>aiAction('aiDecision',{id:cut.id,decision,start:Number(card.querySelector('[data-edge=start]').value),end:Number(card.querySelector('[data-edge=end]').value)}).then(renderCuts).catch(()=>{});actions.append(b)}
  const preview=el('button','Просмотреть стык');preview.disabled=a.stale||a.applied;preview.onclick=async()=>{await aiJob('cutPreview',{id:cut.id});$('cutsDialog').close()};actions.append(preview);card.append(actions);$('cutsRows').append(card);
 }
 const view=aiData().cutPreview;if(view&&!a.stale){const video=el('video');video.src=view.url;video.controls=true;video.className='cut-preview';$('cutsRows').prepend(video)}
 if(!$('cutsDialog').open)$('cutsDialog').showModal();
}
function renderTitles(){
 const r=aiData().research;if(!r)return;$('titlesRows').replaceChildren();
 for(const [i,t]of(r.titles||[]).entries()){const row=el('article',undefined,'titlecard');row.append(el('h3',String(i+1).padStart(2,'0')+' · '+t.title),el('p',t.reason,'hint'));const choose=el('button','Выбрать название');choose.onclick=async()=>{await saveWorkflow({selectedTitle:t.title});note('Название выбрано; публикация не выполнялась');$('titlesDialog').close()};if(r.covers?.[i]){row.append(el('p','Обложка: '+r.covers[i].concept,'info'),el('p','Надпись: '+r.covers[i].copy,'hint'))}row.append(choose);$('titlesRows').append(row)}
 const sources=el('div',undefined,'sources');sources.append(el('h3','Источники ресёрча'));
 for(const ref of r.meta?.sources||[]){try{const url=new URL(ref.url);if(url.protocol!=='https:')continue;const link=el('a',ref.title||url.hostname);link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';sources.append(link)}catch{}}
 $('titlesRows').append(sources);if(!$('titlesDialog').open)$('titlesDialog').showModal();
}
function renderGallery(){
 const gallery=aiData().gallery;if(!gallery)return;$('galleryGrid').replaceChildren();
 for(const image of gallery.images||[]){const card=el('article',undefined,'gallerycard'),img=el('img');img.src=image.url;img.alt=image.concept||'Вариант обложки';const label=el('label'),checkbox=el('input');checkbox.type='checkbox';checkbox.checked=!!image.selected;checkbox.dataset.cover=image.id;label.append(checkbox,document.createTextNode('Выбрать для A/B'));const link=el('a','Скачать PNG');link.href=image.url;link.download='frame-cover-'+image.id+'.png';card.append(img,el('h3',image.concept),el('p',image.copy,'hint'),label,link);$('galleryGrid').append(card)}
 $('galleryStatus').textContent='Выбери до трёх вариантов. Проверь лицо, анатомию и надпись: генерация не гарантирует их точность.';
 if(!$('galleryDialog').open)$('galleryDialog').showModal();
}
bind('saveCoverSelection',async()=>{const ids=[...$('galleryGrid').querySelectorAll('input:checked')].map(i=>i.dataset.cover);await aiAction('aiSelectCovers',{ids});$('galleryStatus').textContent='Выбор сохранён. Обложки никуда не опубликованы.'});
bind('downloadCoverSelection',async()=>{const ids=[...$('galleryGrid').querySelectorAll('input:checked')].map(i=>i.dataset.cover);await aiAction('aiSelectCovers',{ids});const d=await api('action',{action:'aiCoverZip'});downloadURL(d.url,'frame-covers.zip')});
document.addEventListener('keydown',e=>{
 if(!(e.ctrlKey||e.metaKey)||!e.altKey||e.isComposing||e.target.matches('input,select,textarea,[contenteditable=true]')||document.querySelector('dialog[open]'))return;
 const map={t:['story','transcribeAI'],a:['story','analyzeAI'],c:['story','openCuts'],m:['color','matchReference'],i:['insert','planInsertsAI'],l:['voice','translateAI'],d:['voice','dubAI'],n:['package','researchAI'],g:['package','openGallery']};
 const choice=map[e.key.toLowerCase()];if(!choice)return;e.preventDefault();e.stopImmediatePropagation();setPage(choice[0]);const b=$(choice[1]);if(b&&!b.disabled)b.click();else if(!data.connections?.openai&&!data.connections?.elevenlabs)openProviders();
},true);

$("providersDialog").addEventListener("close",()=>{$("openaiKey").value="";$("elevenKey").value=""});

/* Studio controls: native actions, measured media, local generators. */
const studioUpdate=update,studioInspector=renderInspector,studioAI=renderAIControls;
const studio={scope:'histogram',audio:null,analysers:[],lastScope:0,peaks:[-120,-120],rms:[-120,-120]};
function studioInit(){
 const tools=$('aiSettings').parentElement;
 const generate=el('button','Создать');generate.id='openGenerate';generate.title='Голос, изображение, видео · Ctrl+Alt+V';generate.onclick=openGenerate;
 const meters=el('button','Измерители');meters.id='openMeters';meters.title='Метрики и видеоскопы · Ctrl+Alt+S';meters.onclick=openMeters;
 tools.insertBefore(generate,$('aiSettings'));tools.insertBefore(meters,$('aiSettings'));
 const dialog=el('dialog');dialog.id='generateDialog';dialog.className='generate-dialog';
 dialog.innerHTML='<div class="dialoghead"><h2>Создать медиа</h2><button id="closeGenerate" aria-label="Закрыть">×</button></div><label class="field">Что создать<select id="generateKind"><option value="generateVideo">Видео по изображению · Wan</option><option value="generateImage">Изображение · Ася</option><option value="speech">Речь из текста · VoxCPM2</option></select></label><label class="field">Исходник<select id="generateReference"></select></label><label class="stacked">Задача / текст речи<textarea id="generatePrompt" maxlength="1800" rows="5" placeholder="Один объект, одно действие, простой свет. Для речи — точный текст."></textarea></label><div class="row"><label class="field">Seed<input id="generateSeed" type="number" min="0" max="2147483647" value="42"></label><label class="field">Видео<select id="generateFrames"><option value="17">1 с · 17 кадров</option><option value="33" selected>2 с · 33 кадра</option><option value="49">3 с · 49 кадров</option></select></label></div><p class="hint" id="generateModeHint"></p><p class="hint" id="generateReady"></p><button id="submitGenerate" class="wide primary">Создать</button><p class="hint">Одна GPU-задача за раз. Результат добавится в медиатеку, не на таймлайн. Изображения создаёт Ася через текущий доступ; речь и видео выполняются на ПК. Похожесть лица нужно проверить.</p><div id="generateResults"></div>';
 document.body.append(dialog);bind('closeGenerate',()=>dialog.close());
 $('generateKind').onchange=studioGeneratorMode;bind('submitGenerate',async()=>{
  const kind=val('generateKind'),prompt=val('generatePrompt').trim();if(!prompt)throw Error('Введи задачу или текст');
  const result=await api('action',{action:'aiJob',kind,prompt,item:n('generateReference'),sourceSeconds:n('generateReference')===asset?($('sourceVideo').currentTime||0):0,seed:n('generateSeed'),frames:n('generateFrames')});update(result);dialog.close();note('Генерация запущена. Можно следить за очередью в измерителях.');openMeters();
 });
 const metrics=el('dialog');metrics.id='metersDialog';metrics.className='meters-dialog';
 metrics.innerHTML='<div class="dialoghead"><h2>Измерители</h2><button id="closeMeters" aria-label="Закрыть">×</button></div><div class="metrics-grid"><section><h3>Монтаж и выбранный фрагмент</h3><dl id="editMetrics" class="metric-list"></dl><h3>Исходный файл</h3><dl id="sourceMetrics" class="metric-list"></dl></section><section><h3>Звук программы · браузерный просмотр</h3><div class="audio-meter"><div><span>L</span><meter id="audioMeterL" min="-60" max="0" low="-18" high="-6" optimum="-18" value="-60"></meter><output id="audioPeakL">—</output></div><div><span>R</span><meter id="audioMeterR" min="-60" max="0" low="-18" high="-6" optimum="-18" value="-60"></meter><output id="audioPeakR">—</output></div></div><p class="hint" id="audioMeterInfo">Sample peak / RMS, dBFS. Запусти программу и нажми «Включить метры».</p><button id="enableMeters">Включить метры</button><button id="measureLoudness">Измерить громкость монтажа</button><dl id="loudnessMetrics" class="metric-list"></dl></section><section class="scope-section"><div class="scope-head"><h3>Видеоскопы просмотрщика</h3><select id="scopeMode" aria-label="Видеоскоп"><option value="histogram">RGB-гистограмма</option><option value="waveform">Яркостная волна</option><option value="vectorscope">Вектороскоп Cb/Cr</option></select></div><canvas id="scopeCanvas" width="512" height="180" aria-label="Видеоскоп текущего кадра"></canvas><p class="hint" id="scopeInfo">Пиксели текущего предпросмотра; не HDR-измеритель мастера.</p></section><section><h3>Очередь и рабочее хранилище</h3><dl id="runtimeMetrics" class="metric-list"></dl><div id="studioJobs"></div></section></div>';
 document.body.append(metrics);bind('closeMeters',()=>metrics.close());bind('enableMeters',enableAudioMeters);bind('measureLoudness',()=>{metrics.close();setPage('audio');return aiJob('metrics')});
 $('scopeMode').onchange=()=>{studio.scope=val('scopeMode');drawScopes()};
 const footer=el('div');footer.id='studioStatus';footer.className='studio-status';footer.setAttribute('aria-live','off');document.querySelector('.timelinefoot').append(footer);
 const extra=el('div');extra.className='row studio-transport';
 for(const [id,label,tip,fn]of[
  ['previousCut','|‹','Предыдущая склейка · ↑',()=>jumpCut(-1)],['nextCut','›|','Следующая склейка · ↓',()=>jumpCut(1)],
  ['captureStill','Кадр','Сохранить текущий отрендеренный кадр',async()=>{await showFrame();if(data.frame?.url)downloadURL(data.frame.url,'frame.png')}],
  ['fullViewer','⛶','Полноэкранный просмотр · Shift+F',()=>document.querySelector('.program.viewerpanel')?.requestFullscreen()]
 ]){const b=el('button',label);b.id=id;b.title=tip;b.onclick=()=>Promise.resolve(fn()).catch(e=>note(e.message,true));extra.append(b)}
 document.querySelector('.timelinefoot').before(extra);
 const help=$('helpDialog').querySelector('dl');help.insertAdjacentHTML('beforeend','<dt>↑ / ↓</dt><dd>Предыдущая / следующая склейка</dd><dt>Shift+F</dt><dd>Полноэкранный просмотр</dd><dt>Ctrl+Alt+V</dt><dd>Генерация голоса, изображений и видео</dd><dt>Ctrl+Alt+S</dt><dd>Измерители и видеоскопы</dd>');
 for(const [cls,axis,variable,min,max]of[['pool-resizer','x','--pool',180,500],['inspector-resizer','x','--inspect',250,550],['timeline-resizer','y','--viewer-height',180,700]]){
  const handle=el('div');handle.className='panel-resizer '+cls;handle.setAttribute('role','separator');handle.setAttribute('tabindex','0');handle.setAttribute('aria-label',cls==='pool-resizer'?'Ширина медиатеки':cls==='inspector-resizer'?'Ширина инспектора':'Высота просмотрщиков');
  let initial=0,start=0;
  handle.onpointerdown=e=>{start=axis==='x'?e.clientX:e.clientY;initial=axis==='y'?document.querySelector('.viewers').clientHeight:document.querySelector(cls==='pool-resizer'?'.pool':'.inspector').clientWidth;handle.setPointerCapture(e.pointerId)};
  handle.onpointermove=e=>{if(!handle.hasPointerCapture(e.pointerId))return;const delta=(axis==='x'?e.clientX:e.clientY)-start;const value=Math.max(min,Math.min(max,initial+(cls==='inspector-resizer'?-delta:delta)));document.documentElement.style.setProperty(variable,value+'px')};
  handle.onkeydown=e=>{if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key))return;e.preventDefault();e.stopPropagation();const value=parseInt(getComputedStyle(document.documentElement).getPropertyValue(variable))||300;document.documentElement.style.setProperty(variable,Math.max(min,Math.min(max,value+(e.key==='ArrowRight'||e.key==='ArrowDown'?20:-20)))+'px')};
  document.querySelector('.workspace').append(handle);
 }
 requestAnimationFrame(studioTick);
}
function studioGeneratorMode(){
 const speech=val('generateKind')==='speech',image=val('generateKind')==='generateImage';$('generateReference').closest('label').hidden=speech;$('generateFrames').closest('label').hidden=val('generateKind')!=='generateVideo';
 $('generateReady').textContent=image?(data?.connections?.asya?'Ася подключена. Используется существующий доступ, с его лимитами.':'Нет свежего соединения с Асей.'):(data?.connections?.pc?'ПК подключён. Очередь и память проверяются при запуске.':'ПК не подключён.');
 $('generateModeHint').textContent=image?'Качественное изображение через Асю. Выбранный кадр служит референсом; похожесть лица нужно проверить.':speech?'Точная речь из текста, без имитации твоего голоса. Свой голос — на странице «Перевод», после согласия.':'512 × 288, 16 fps. Для выбранного в просмотрщике видео берётся его текущий кадр; для другого — первый. Описывай небольшое изменение / движение; это image-to-video, не произвольное рисование с нуля.';
 $('submitGenerate').disabled=!(val('generateKind')==='generateImage'?data?.connections?.asya:data?.connections?.pc); // worker checks model availability and busy queue again
}
function openGenerate(){
 $('generateReference').replaceChildren(...media().filter(m=>m.type!=='Audio').map(m=>{const o=el('option',cleanName(m.name));o.value=m.item;return o}));
 if(asset)$('generateReference').value=asset;
 $('generateReady').textContent=data?.connections?.pc?'ПК подключён. Доступность модели и очередь проверяются при запуске.':'Нет свежего соединения с ПК.';
 $('generateResults').replaceChildren(...(aiData().generated||[]).slice(-3).reverse().map(r=>{const row=el('div',undefined,'generated-result'),a=el('a',r.operation==='speech'?'Открыть WAV':r.operation==='image'?'Открыть PNG':'Открыть MP4');a.href=r.url;a.target='_blank';a.rel='noopener';row.append(a,el('small',r.model+' · '+r.elapsed+' с · seed '+r.seed));return row}));
 studioGeneratorMode();if(!$('generateDialog').open)$('generateDialog').showModal();
}
function jumpCut(direction){const points=[...new Set([0,dur(),...clips().flatMap(c=>[sec(c.start),sec(c.start+c.duration)])])].sort((a,b)=>a-b),now=n('playhead');setCursor(direction>0?(points.find(t=>t>now+.5/fps())??dur()):([...points].reverse().find(t=>t<now-.5/fps())??0))}
function metricsList(id,rows){$(id).replaceChildren(...rows.flatMap(([k,v])=>[el('dt',k),el('dd',String(v??'—'))]))}
function formatBytes(v){return Number.isFinite(v)?(v/1048576).toFixed(1)+' МиБ':'—'}
function refreshMetrics(){
 if(!data)return;
 const c=current(),m=source(),v=m?.info?.video,settings=seq().settings||{},jobs=data.jobs||[];
 metricsList('editMetrics',[['Курсор',tc(n('playhead'))],['Длительность',tc(dur())+' · '+Math.round(dur()*fps())+' кадров'],['Формат',settings.width?settings.width+' × '+settings.height+' · '+fps().toFixed(3)+' fps':'—'],['Дорожки',(seq().video?.length||0)+' видео / '+(seq().audio?.length||0)+' аудио'],['Клипы',clips().length],['Выбран',c?cleanName(c.name)+' · '+c.track:'—'],['In / Out',c?tc(sec(c.start))+' → '+tc(sec(c.start+c.duration)):'—'],['Длина клипа',c?sec(c.duration).toFixed(3)+' с · '+Math.round(sec(c.duration)*fps())+' кадров':'—'],['Source In',c?tc(sec(c.sourceIn)):'—']]);
 const audio=m?.info?.audio_streams?.[0],originalVideo=m?.original?.probe?.streams?.find(s=>s.codec_type==='video');
 metricsList('sourceMetrics',[['Файл',m?cleanName(m.name):'—'],['Тип',m?.type],['Кадр просмотра',v?v.width+' × '+v.height:'—'],['Кадр оригинала',originalVideo?originalVideo.width+' × '+originalVideo.height:v?v.width+' × '+v.height:'—'],['Длительность',m?tc(sec(m.duration)):'—'],['Размер оригинала',formatBytes(m?.original?.bytes??m?.info?.file_size)],['Режим просмотра',m?.original?'Прокси; полный оригинал используется при PC-рендере':'Локальный материал'],['FPS исходника',v?.frame_rate?(v.frame_rate.num/v.frame_rate.den).toFixed(3)+' fps':'—'],['Видео кодек',v?.codec||v?.codec_name],['Pixel format',v?.pixel_format],['Поток видео',v?.bitrate?(v.bitrate/1000000).toFixed(2)+' Мбит/с':'—'],['Цвет',v?.color?[v.color.matrix,v.color.transfer,v.color.primaries,v.color.range].join(' · ')+(Object.values(v.color_assumed||{}).some(Boolean)?' · часть параметров предположена движком':''):'—'],['Аудио',audio?[audio.codec||audio.codec_name,audio.sample_rate?audio.sample_rate+' Hz':'',audio.channels?audio.channels+' ch':''].filter(Boolean).join(' · '):'—']]);
 const measurement=aiData().metrics;metricsList('loudnessMetrics',[['Integrated',measurement?.integratedLUFS!=null?measurement.integratedLUFS.toFixed(1)+' LUFS':'—'],['Loudness range',measurement?.rangeLU!=null?measurement.rangeLU.toFixed(1)+' LU':'—'],['True peak',measurement?.truePeakDBTP!=null?measurement.truePeakDBTP.toFixed(1)+' dBTP':'—'],['Источник измерения',measurement?(measurement.stale?'Устарел: монтаж изменился · ':'Отрендеренный звуковой proxy · ')+(measurement.fingerprint===undefined?'':new Date(measurement.created*1000).toLocaleTimeString('ru-RU')):'Ещё не измерен']]);
 const running=jobs.filter(j=>j.status==='running'),r=data.storage||{};
 metricsList('runtimeMetrics',[['Ася',data.connections?.asya?'подключена':'нет свежей связи'],['ПК',data.connections?.pc?'подключён':'нет свежей связи'],['Активные задачи',running.length],['В работе',running[0]?Math.round((Date.now()/1000-running[0].started))+' с':'—'],['Spool аккаунта',r.used!=null?formatBytes(r.used)+' / '+formatBytes(r.limit):'—'],['Свободно на FS',formatBytes(r.available)]]);
 $('measureLoudness').disabled=!dur()||running.length>0;$('studioJobs').replaceChildren(...jobs.slice(-5).reverse().map(j=>el('p',j.kind.replace('ai:','')+' · '+j.status+(j.status==='running'?' · '+Math.round(Date.now()/1000-j.started)+' с':j.error?' · '+j.error:''),'hint')));
 if(running.some(j=>j.kind.startsWith('ai:'))){const cancel=el('button','Отменить ожидание и применение');cancel.onclick=()=>aiAction('aiCancel');$('studioJobs').append(cancel,el('p','Вычисление на ПК может завершиться; отменённый результат не загрузится и не применится.','hint'))}
 $('studioStatus').textContent=clips().length+' клипов · '+Math.round(dur()*fps())+' кадров'+(running.length?' · задача '+Math.round(Date.now()/1000-running[0].started)+' с':'');
}
function openMeters(){refreshMetrics();if(!$('metersDialog').open)$('metersDialog').showModal();drawScopes()}
async function enableAudioMeters(){
 if(!studio.audio){studio.audio=new AudioContext();const input=studio.audio.createMediaElementSource($('video')),split=studio.audio.createChannelSplitter(2);input.connect(split);input.connect(studio.audio.destination);for(let i=0;i<2;i++){const a=studio.audio.createAnalyser();a.fftSize=2048;split.connect(a,i);studio.analysers.push(a)}}
 await studio.audio.resume();$('audioMeterInfo').textContent='Sample peak / RMS, dBFS; только программа, не исходник. LUFS и true peak измеряются отдельной кнопкой.';
}
const scopeBuffer=document.createElement('canvas');scopeBuffer.width=256;scopeBuffer.height=144;
function drawScopes(){
 const canvas=$('scopeCanvas');if(!canvas)return;const ctx=canvas.getContext('2d'),w=canvas.width,h=canvas.height;ctx.fillStyle='#15191e';ctx.fillRect(0,0,w,h);ctx.strokeStyle='#ffffff12';ctx.lineWidth=1;
 for(let i=1;i<4;i++){ctx.beginPath();ctx.moveTo(0,h*i/4);ctx.lineTo(w,h*i/4);ctx.stroke()}
 const image=!$('video').hidden&&$('video').readyState>=2?$('video'):!$('frame').hidden&&$('frame').naturalWidth?$('frame'):!$('sourceImage').hidden&&$('sourceImage').naturalWidth?$('sourceImage'):!$('sourceVideo').hidden&&$('sourceVideo').readyState>=2?$('sourceVideo'):null;
 if(!image){ctx.fillStyle='#8d99a7';ctx.fillText('Нет декодированного кадра',16,28);return}
 try{
  const c=scopeBuffer.getContext('2d',{willReadFrequently:true});c.drawImage(image,0,0,256,144);const pixels=c.getImageData(0,0,256,144).data;
  if(studio.scope==='histogram'){
   const bins=[new Uint32Array(256),new Uint32Array(256),new Uint32Array(256)];for(let i=0;i<pixels.length;i+=4)for(let k=0;k<3;k++)bins[k][pixels[i+k]]++;
   const max=Math.max(1,...bins.flatMap(a=>[...a]));ctx.globalAlpha=.7;
   bins.forEach((row,k)=>{ctx.strokeStyle=['#ec8c8d','#8acba5','#86adf0'][k];ctx.beginPath();for(let x=0;x<256;x++){const y=h-12-row[x]/max*(h-25);x?ctx.lineTo(x*w/256,y):ctx.moveTo(0,y)}ctx.stroke()});ctx.globalAlpha=1;ctx.fillStyle='#8d99a7';ctx.fillText('0',4,h-1);ctx.fillText('255',w-28,h-1);
  }else if(studio.scope==='waveform'){
   ctx.fillStyle='#b7cfbd';ctx.globalAlpha=.12;
   for(let y=0;y<144;y++)for(let x=0;x<256;x++){const i=(y*256+x)*4,l=.2126*pixels[i]+.7152*pixels[i+1]+.0722*pixels[i+2];ctx.fillRect(x*w/256,(1-l/255)*(h-12),2,1)}
   ctx.globalAlpha=1;ctx.fillStyle='#8d99a7';ctx.fillText('100% Y′',4,12);ctx.fillText('0%',4,h-1);
  }else{
   const radius=Math.min(w,h)/2-12;ctx.strokeStyle='#ffffff22';
   for(const r of [radius,radius/2]){ctx.beginPath();ctx.arc(w/2,h/2,r,0,Math.PI*2);ctx.stroke()}
   ctx.fillStyle='#c3cce4';ctx.globalAlpha=.15;
   for(let i=0;i<pixels.length;i+=8){const r=pixels[i]/255,g=pixels[i+1]/255,b=pixels[i+2]/255,cb=-.114572*r-.385428*g+.5*b,cr=.5*r-.454153*g-.045847*b;ctx.fillRect(w/2+cb*radius*2,h/2-cr*radius*2,1,1)}
   ctx.globalAlpha=1;ctx.fillStyle='#8d99a7';ctx.fillText('Cb →',w/2+radius-35,h/2);ctx.fillText('Cr ↑',w/2+3,13);
  }
  $('scopeInfo').textContent=(image===$('sourceVideo')||image===$('sourceImage')?'Исходник':'Программа')+' · RGB-декодирование браузера, 256 × 144 выборка. Не HDR/мастер-измерение.';
 }catch{$('scopeInfo').textContent='Кадр пока недоступен для измерения'}
}
function studioTick(now){
 if(now-studio.lastScope>250){studio.lastScope=now;if($('metersDialog')?.open){refreshMetrics();drawScopes();studio.analysers.forEach((a,i)=>{const buffer=new Float32Array(a.fftSize);a.getFloatTimeDomainData(buffer);let peak=0,sum=0;for(const v of buffer){peak=Math.max(peak,Math.abs(v));sum+=v*v}const db=20*Math.log10(Math.max(peak,1e-6)),rms=20*Math.log10(Math.max(Math.sqrt(sum/buffer.length),1e-6)),side=i?'R':'L';$('audioMeter'+side).value=Math.max(-60,db);$('audioPeak'+side).textContent=(db<=-120?'−∞':db.toFixed(1))+' / '+(rms<=-120?'−∞':rms.toFixed(1))+' dBFS'})}}
 requestAnimationFrame(studioTick);
}
update=function(d){studioUpdate(d);refreshMetrics()};
renderInspector=function(){studioInspector();if(['audio','color','edit'].includes(page)){const summary=el('p',undefined,'clip-metrics');const c=current();summary.textContent=c?tc(sec(c.start))+' → '+tc(sec(c.start+c.duration))+' · '+sec(c.duration).toFixed(2)+' с · '+Math.round(sec(c.duration)*fps())+' кадров':Math.round(dur()*fps())+' кадров · '+fps().toFixed(2)+' fps';$('stageContent').prepend(summary)}};
renderAIControls=function(){studioAI();if(['insert','package','voice'].includes(page)){const b=el('button',page==='voice'?'Создать речь из текста':'Создать изображение / видео');b.className='wide generate-entry';b.onclick=()=>{openGenerate();$('generateKind').value=page==='voice'?'speech':page==='package'?'generateImage':'generateVideo';studioGeneratorMode()};$('stageContent').prepend(b)}};
document.addEventListener('keydown',e=>{
 if(e.target.getAttribute('role')==='separator'||e.isComposing||e.target.matches('input,select,textarea,[contenteditable=true]')||document.querySelector('dialog[open]'))return;
 if((e.ctrlKey||e.metaKey)&&e.altKey&&['v','s'].includes(e.key.toLowerCase())){e.preventDefault();e.stopImmediatePropagation();e.key.toLowerCase()==='v'?openGenerate():openMeters();return}
 if(!e.ctrlKey&&!e.metaKey&&!e.altKey&&['ArrowUp','ArrowDown'].includes(e.key)){e.preventDefault();jumpCut(e.key==='ArrowUp'?-1:1)}
 if(e.shiftKey&&e.key.toLowerCase()==='f'){e.preventDefault();$('fullViewer').click()}
},true);
studioInit();

/* Persistent programme sample-peak meters; starts only on a playback gesture. */
const mini=el('div');mini.id='miniMeters';mini.className='mini-meters';mini.title='Программа: sample peak L/R, dBFS; не true peak';
mini.innerHTML='<span>L</span><meter id="miniL" min="-60" max="0" low="-18" high="-6" optimum="-18" value="-60" aria-label="Левый канал sample peak dBFS"></meter><span>R</span><meter id="miniR" min="-60" max="0" low="-18" high="-6" optimum="-18" value="-60" aria-label="Правый канал sample peak dBFS"></meter><output id="miniValue">dBFS</output>';
document.querySelector('.program .sourceactions')?.append(mini);
if(!mini.isConnected)document.querySelector('.program .viewertransport').after(mini);
$('play').addEventListener('click',()=>enableAudioMeters().catch(e=>note('Аудиометры: '+e.message,true)));
function miniTick(){if(studio.analysers.length){let highest=-120;studio.analysers.forEach((a,i)=>{const x=new Float32Array(a.fftSize);a.getFloatTimeDomainData(x);let peak=0;for(const v of x)peak=Math.max(peak,Math.abs(v));const db=20*Math.log10(Math.max(peak,1e-6));$(i?'miniR':'miniL').value=Math.max(-60,db);highest=Math.max(highest,db)});$('miniValue').textContent=(highest<=-120?'−∞':highest.toFixed(1))+' dBFS'}setTimeout(miniTick,150)}miniTick();


// #379 — explicit local master versus site preview, real AI comparison, full brief map.
const render379Base=render,controls379Base=renderAIControls,jobs379Base=renderJobs;
function profile379(){const p={...(wf().exportProfile||{})};if($('renderDevice379'))p.renderDevice=val('renderDevice379');if($('renderCodec379'))p.codec=val('renderCodec379');if($('aiUpscale379'))p.aiUpscale=$('aiUpscale379').checked;if($('qualitySize'))p.maxSide=n('qualitySize');if($('qualityDenoise'))p.denoise=$('qualityDenoise').checked;if($('qualitySharpness'))p.sharpness=n('qualitySharpness');return p}
render=async function(preview,extra={}){if(preview)return render379Base(true);try{stopPlayback();const p=profile379();await saveWorkflow({exportProfile:p});await api('render',{preview:false,...extra});update(await api('state'));note(extra.qualityPreview?'Проба до/после отправлена на ПК':'Рендер добавлен в очередь')}catch(e){note(e.message,true)}};
renderAIControls=function(){controls379Base();const s=$('stageContent');if(!s)return;const p=wf().exportProfile||{};
 if(page==='color'){
  const size=$('qualitySize');if(size&&!size.querySelector('[value="3840"]')){const o=el('option','Длинная сторона 3840');o.value='3840';o.selected=p.maxSide===3840;size.append(o)}
  const box=el('section',undefined,'quality-ai379');box.innerHTML='<label class="consent"><input id="aiUpscale379" type="checkbox" '+(p.aiUpscale?'checked':'')+'>ИИ-апскейл · Real-ESRGAN x4plus на ПК</label><button id="qualityCompare379" class="wide" '+(!dur()||!data.connections?.pc?'disabled':'')+'>Проба 2 с: до / после</button>'+hint('Слева исходный нативный рендер, справа обработка. Модель может менять фактуру лица и создавать ложные детали; оцени движение и мерцание. Полный размер сохраняется на ПК. Обычный просмотр в программе не показывает ИИ-апскейл. При «Исходный» ИИ выбирает ×2, не более 3840 по длинной стороне.');
  $('applyQuality')?.after(box);bind('applyQuality',async()=>{const p=profile379();await saveWorkflow({exportProfile:p});await showFrame()});bind('qualityCompare379',()=>render(false,{qualityPreview:true,seconds:n('playhead')}));
 }
 if(page==='deliver'){
  const box=el('section',undefined,'render-settings379');box.innerHTML='<label class="field">Исполнитель<select id="renderDevice379"><option value="pc">Мой ПК · полный файл локально</option><option value="server">Сервер · скачать MP4</option></select></label><label class="field">Кодек<select id="renderCodec379"><option value="h264">H.264 · совместимость</option><option value="hevc">HEVC · только ПК</option></select></label><label class="consent"><input id="aiUpscale379" type="checkbox" '+(p.aiUpscale?'checked':'')+'>Real-ESRGAN · ИИ-апскейл</label>'+hint('Полный MP4 остаётся на ПК; на сайте — только лёгкое превью (для длинного ролика — первые 120 с). Размер, шум и резкость — в «Цвете». Серверный вывод: H.264 без ИИ.');
  $('export').before(box);$('renderDevice379').value=p.renderDevice||'pc';$('renderCodec379').value=p.codec||'h264';const meta=$('renderCodecMeta379');const updateCodec=()=>{if(meta)meta.textContent='MP4 · '+(val('renderCodec379')==='hevc'?'HEVC':'H.264')+' / AAC'};updateCodec();$('renderCodec379').onchange=updateCodec;$('export').textContent='Начать рендер';
  const stages=[['Материалы','Видео, две звуковые дорожки, вставки и референсы','media'],['Очистка речи','Прослушать обе дорожки до / после; принять','audio'],['Синхрон','Проверить начало и конец; измерение дрейфа по длине, отдельное принятие коррекции','sync'],['Расшифровка','Whisper на ПК; слова и таймкоды','story'],['Смысловой разбор','Ася: конспект, повторы, варианты; выборка кадров, не непрерывный просмотр','story'],['Монтаж','Принять вырезки; спорные ударения, интонации и смех — прослушать','edit'],['Цвет по референсу','Мягкий подбор; сравнить и принять','color'],['Качество','Шум / резкость / размер / ИИ-апскейл; проба в движении','color'],['Вставки','По смыслу; основной кадр, окно или смена компоновки','insert'],['Перевод','Ася; проверить текст и субтитры','voice'],['Свой голос','Qwen3-TTS:5языков, отдельные WAV/SRT; проверить тембр. Без липсинка','voice'],['Упаковка','9–12 названий, референс, пробная обложка, выбрать до трёх','package'],['Рендер','ПК / сервер → проверка → личный MP4. Без автопубликации','deliver']];
  const det=el('details');det.className='brief379';const sum=el('summary','Все 13 этапов из ТЗ');det.append(sum);for(const [title,help,key]of stages){const b=el('button',undefined,'brief-step379');b.append(el('b',title),el('span',help));b.onclick=()=>setPage(key);det.append(b)}s.append(det);
 }
};
renderJobs=function(jobs){const pc=jobs.filter(j=>['pcExport','pcQualityPreview'].includes(j.kind));jobs379Base(jobs.filter(j=>!pc.includes(j)));const root=$('jobs');if(!root)return;if(pc.length&&!jobs.some(j=>!pc.includes(j)))root.replaceChildren();for(const j of pc.slice(-5).reverse()){
 const card=el('section',undefined,'job pc-job379');card.append(el('b',(j.kind==='pcQualityPreview'?'Проба качества · ПК':'Полный рендер · ПК')+' · '+({running:'в работе',done:'готов',error:'не завершён'}[j.status])));
 const p=j.pcProgress;if(p){const total=Number(p.frames)||0,frame=Math.min(total,Number(p.frame)||0);if(total){const bar=el('progress');bar.max=total;bar.value=frame;bar.setAttribute('aria-label',frame+' из '+total+' кадров обработано');card.append(bar)}card.append(el('p',String(p.phase||'')+' · '+frame+'/'+total+' кадров · '+Number(p.elapsed||0).toFixed(0)+' с'+(p.fps?' · '+p.fps+' кадр/с':'')+(p.eta?' · осталось ≈ '+Math.ceil(p.eta)+' с':'')+(p.paused?' · пауза':''),'hint'))}
 const control=(label,action)=>{const b=el('button',label);b.onclick=()=>aiAction('pcRenderControl',{id:j.id,control:action});return b};
 if(j.status==='running'){const row=el('div',undefined,'row');row.append(control(j.pauseRequested?'Продолжить':'Пауза',j.pauseRequested?'resume':'pause'),control('Отменить','cancel'));card.append(row);if(j.cancelRequested)card.append(el('p','Отмена запрошена. Ожидается остановка собственного процесса ПК.','hint'));}
 if(j.error)card.append(el('p',j.error,'error'));if(j.status==='error'){const b=el('button','Проверить и получить прежний файл');b.onclick=()=>render(false,{resume:j.id});card.append(b)}
 if(j.status==='done'&&j.full){const f=j.full;card.append(el('p',f.width+' × '+f.height+' · '+f.fps+' fps · '+f.codec+' · '+(f.fullBytes/1024/1024).toFixed(1)+' МиБ','hint'));const path=el('code',f.fullPath);card.append(path,control('Показать полный MP4 на ПК','open'));const a=el('a',j.kind==='pcQualityPreview'?'Открыть сравнение: слева до / справа после':(j.full?.previewIsExcerpt?'Открыть первые 120 с — не мастер':'Открыть облегчённое превью — не мастер'));a.href=j.url;a.target='_blank';a.rel='noopener';card.append(a);}
 root.prepend(card);
 }};

// #386 object-first sources: small bounded parts, verified resume, no giant VPS spool.
const upload386Local=uploadFiles;let object386Stop=false;
function object386Dialog(){let d=$('objectUpload386');if(d)return d;d=el('dialog');d.id='objectUpload386';d.innerHTML='<h2>Исходник в Object Storage</h2><p id="objectName386"></p><progress id="objectProgress386" max="1" value="0" aria-label="Передано байтов"></progress><p id="objectStatus386" role="status" aria-live="polite"></p><button id="objectPause386">Остановить и продолжить позже</button>';document.body.append(d);$('objectPause386').onclick=()=>{object386Stop=true};d.addEventListener('cancel',e=>{e.preventDefault();object386Stop=true});return d}
function bytes386(n){return n>=1024**3?(n/1024**3).toFixed(2)+' ГиБ':(n/1024**2).toFixed(1)+' МиБ'}
async function object386API(operation,more={}){return api('action',{action:'object',operation,...more})}
async function object386Upload(file,role){
 const max=data.objectLimitBytes||10*1024**3;if(!file.size||file.size>max)throw Error('Один исходник — до 10 ГиБ');const sourceProject=data.project,dialog=object386Dialog();object386Stop=false;$('objectName386').textContent=file.name+' · '+bytes386(file.size);$('objectProgress386').max=file.size;$('objectProgress386').value=0;dialog.showModal();const key='frame386:upload:'+data.account;let ticket;
 try{
  let previous;try{previous=JSON.parse(localStorage.getItem(key)||'null')}catch{}
  if(previous&&previous.name===file.name&&previous.bytes===file.size&&previous.lastModified===file.lastModified){try{ticket=await object386API('status',{id:previous.id})}catch{}}
  if(!ticket)ticket=await object386API('init',{name:file.name,bytes:file.size,lastModified:file.lastModified,role});
  localStorage.setItem(key,JSON.stringify({id:ticket.id,name:file.name,bytes:file.size,lastModified:file.lastModified,role}));
  const part=ticket.partBytes||8*1024**2;
  for(let offset=ticket.uploaded||0;ticket.status==='uploading'&&offset<file.size;offset+=part){
   if(object386Stop){note('Загрузка остановлена. Выбери этот же файл, чтобы продолжить.');return}
   $('objectStatus386').textContent='Передано '+bytes386(offset)+' из '+bytes386(file.size);const body=await file.slice(offset,Math.min(file.size,offset+part)).arrayBuffer();const digest=[...new Uint8Array(await crypto.subtle.digest('SHA-256',body))].map(n=>n.toString(16).padStart(2,'0')).join('');
   const r=await fetch(BASE+'/api/object-part/'+ticket.id+'/'+(Math.floor(offset/part)+1),{method:'POST',headers:{'X-Frame-CSRF':csrf,'X-Part-SHA256':digest},body});const receipt=await r.json();if(!r.ok)throw Error(receipt.error||'Часть не принята; исходник не удалён');$('objectProgress386').value=receipt.uploaded;
  }
  if(ticket.status==='uploading')ticket=await object386API('complete',{id:ticket.id});
  while(ticket.status==='verifying'){
   if(object386Stop){note('Проверка исходника продолжится на сервере. Выбери этот же файл позже.');return}
   $('objectStatus386').textContent='Обратная проверка: '+bytes386(ticket.verified||0)+' из '+bytes386(file.size);$('objectProgress386').value=ticket.verified||0;await new Promise(r=>setTimeout(r,1500));ticket=await object386API('status',{id:ticket.id});
  }
  if(ticket.status!=='ready')throw Error(ticket.error||'Исходник не прошёл проверку');$('objectStatus386').textContent='Исходник проверен. Подготовка лёгкого просмотра…';$('objectProgress386').value=file.size;
  const job=await object386API('import',{id:ticket.id});update(await api('state'));let result=job;
  while(result.status==='running'){if(data.project!==sourceProject)throw Error('Проект переключён. Просмотр сохранён в исходном проекте.');if(object386Stop){note('Подготовка просмотра продолжится. Результат появится в очереди.');return}await new Promise(r=>setTimeout(r,1500));const s=await api('jobs');result=s.jobs.find(j=>j.id===job.id)||result;data.jobs=s.jobs;renderJobs(s.jobs)}
  if(result.status!=='done')throw Error(result.error||'Просмотр не готов; исходник сохранён');update(await api('state'));asset=result.item;renderAssets();renderSource();renderInspector();localStorage.removeItem(key);note('Добавлен '+file.name+' · полный исходник сохранён в облаке');
 }finally{dialog.close()}
}
uploadFiles=async function(files){for(const file of files){try{if(file.size>data.limitBytes||['video','audio1','audio2'].includes(uploadRole))await object386Upload(file,uploadRole);else await upload386Local([file])}catch(e){note(e.message,true);break}}};

/* Reviewed alternate audio tracks, kept separate from the programme timeline. */
const dubLanguages386={en:'English',es:'Español',zh:'中文 · Mandarin',pt:'Português',de:'Deutsch'};
function chosenDubLanguages(){const languages=[...document.querySelectorAll('input[name="dubLanguage"]:checked')].map(i=>i.value);if(!languages.length)throw Error('Выбери хотя бы один язык');return languages}
function renderLanguageTracks(){
 const a=aiData();bind('translateTracksAI',()=>aiJob('translateTracks',{languages:chosenDubLanguages()}));
 bind('dubFullAI',()=>{if(!$('ownVoiceConsent').checked)throw Error('Подтверди использование своего голоса');const languages=chosenDubLanguages();if(languages.some(l=>!a.translations?.tracks?.[l]?.approved))throw Error('Просмотри и прими каждый выбранный перевод');return aiJob('dubFull',{languages,voiceConsent:true,voiceItem:n('dubVoiceItem'),voiceStart:n('dubVoiceStart'),refText:val('dubRefText')})});
 for(const [lang,t]of Object.entries(a.translations?.tracks||{})){const row=el('div',undefined,'language-track');row.append(el('h4',(dubLanguages386[lang]||lang)+(t.approved?' · принят':' · проверить')));const b=el('button','Просмотреть / исправить перевод');b.disabled=!!a.translations.stale;b.onclick=()=>reviewLanguageTrack(lang,t);const link=el('a','SRT');link.href=t.url;link.download='subtitles-'+lang+'.srt';row.append(b,link);$('translationTracks').append(row)}
 for(const t of a.dubs?.tracks||[]){const row=el('div',undefined,'language-track');row.append(el('h4',(dubLanguages386[t.language]||t.language)+(t.stale?' · прежняя версия':'')));for(const [name,url]of[['Полная WAV-дорожка',t.download],['Субтитры SRT',t.subtitle]]){const link=el('a',name);link.href=url;link.download=(name.startsWith('Полная')?'audio-':'subtitles-')+t.language+(name.startsWith('Полная')?'.wav':'.srt');row.append(link)}const region=a.dubs?.previewRegions?.find(r=>r.language===t.language);if(region){const play=el('button','Прослушать пробу · '+Math.round(region.end-region.start)+'с');play.onclick=()=>{const audio=$('dubPreview386');if(!audio)return;audio.pause();audio.currentTime=region.start;audio.ontimeupdate=()=>{if(audio.currentTime>=region.end)audio.pause()};$('dubPreviewLabel386').textContent='Проба · '+(dubLanguages386[t.language]||t.language)+' · не полная дорожка';audio.play().catch(e=>note(e.message,true))};row.append(play)}row.append(el('p',tc(t.samples/t.sampleRate)+' · '+t.format+' · изменений темпа для проверки: '+(t.warnings?.length||0),'hint'));if(t.loudness)row.append(el('p','Готовая WAV: '+t.loudness.input_i+' LUFS · '+t.loudness.input_tp+' dBTP','hint'));$('dubTracks').append(row)}
 if(a.dubs?.preview){const label=el('p',a.dubs.previewRegions?.length?'Выбери язык для прослушивания пробы до 20 с':'Проба первых 20 с первого языка (не полный файл)','hint'),audio=el('audio');label.id='dubPreviewLabel386';audio.id='dubPreview386';audio.controls=true;audio.src=a.dubs.preview;$('dubTracks').append(label,audio)}
}
function reviewLanguageTrack(lang,track){
 let dialog=$('languageReview386');if(!dialog){dialog=el('dialog');dialog.id='languageReview386';dialog.className='translation-review';document.body.append(dialog)}dialog.replaceChildren();const opener=document.activeElement;const title=el('h2','Перевод · '+dubLanguages386[lang]),hint=el('p','Исправляй текст фраз; таймкоды сохраняются. После изменения перевода прежняя озвучка отмечается устаревшей.','hint');dialog.append(title,hint);const fields=[];
 for(const row of track.segments){const label=el('label',tc(row.start)+' → '+tc(row.end),'stacked'),text=el('textarea');text.value=row.text;text.rows=2;text.maxLength=1800;label.append(text);fields.push(text);dialog.append(label)}
 const status=el('p');status.setAttribute('role','alert');const actions=el('div',undefined,'row'),close=el('button','Закрыть'),save=el('button','Принять этот перевод');close.onclick=()=>dialog.close();save.onclick=async()=>{save.disabled=true;try{await aiAction('aiTranslationReview',{language:lang,approved:true,segments:track.segments.map((r,i)=>({...r,text:fields[i].value}))});dialog.close()}catch(e){status.textContent=e.message}finally{save.disabled=false}};actions.append(close,save);dialog.append(status,actions);dialog.onclose=()=>opener?.focus();dialog.showModal();
}
