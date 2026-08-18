(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const $$ = (sel) => [...document.querySelectorAll(sel)];
  const state = {
    auth:null,license:null,settings:null,messageOptions:[],playlistOptions:[],messages:[],playlists:[],schedules:[],conditionalRules:[],brightnessSchedules:[],users:[],fonts:[],assets:[],videos:[],shaders:[],components:[],playlistItems:[],
    editorTimer:null,selectedMessage:null,selectedPlaylist:null,selectedSchedule:null,selectedConditionalRule:null,selectedBrightnessSchedule:null,selectedUser:null,
    scene:null,selectedLayerId:null,selectedLayerIds:[],selectedZoneId:null,previewBusy:false,previewStarted:performance.now(),drag:null,timelineDrag:null,
    historyPast:[],historyFuture:[],historyBurst:false,historyTimer:null,
    livePreviewEnabled:true,livePreviewBusy:false,livePreviewTimer:null,livePreviewObjectUrl:null,videoUploadBusy:false,lastWidgetPreviewAt:0,diagnosticsBusy:false,lastDiagnostics:null,backups:[],backupBusy:false,backupPollTimer:null,messageVersions:[],displayWidth:0,displayHeight:0,gpioStatus:null,gpioPollTimer:null
  };

  async function api(url, options={}) {
    const opts = {...options};
    const method=String(opts.method||'GET').toUpperCase();
    opts.headers={...(opts.headers||{})};
    if(state.auth?.csrf_token && !['GET','HEAD','OPTIONS'].includes(method))opts.headers['X-CSRF-Token']=state.auth.csrf_token;
    if (opts.body && !(opts.body instanceof FormData)) {
      opts.headers['Content-Type']='application/json';
      if (typeof opts.body !== 'string') opts.body = JSON.stringify(opts.body);
    }
    const r = await fetch(url, opts);
    if(r.status===401){location.href='/login';throw new Error('Sign in required');}
    if (!r.ok) {
      let message = `${r.status} ${r.statusText}`;
      try { const data = await r.json(); if (data.error) message = data.error; } catch (_) {}
      const err = new Error(message);
      err.status = r.status;
      throw err;
    }
    const ct = r.headers.get('content-type') || '';
    return ct.includes('application/json') ? r.json() : r;
  }

  function toast(message, error=false) {
    const el = $('toast'); el.textContent = message; el.classList.toggle('error', error); el.classList.add('show');
    clearTimeout(el._timer); el._timer = setTimeout(()=>el.classList.remove('show'), 2700);
  }
  function esc(s='') { return String(s).replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
  function option(value, label, selected=false){ return `<option value="${esc(value)}"${selected?' selected':''}>${esc(label)}</option>`; }
  function clamp(n,min,max){return Math.min(max,Math.max(min,n));}
  function uid(){return `L${Date.now().toString(36)}${Math.random().toString(36).slice(2,7)}`;}
  function deepClone(x){return JSON.parse(JSON.stringify(x));}
  function sceneSnapshot(){return state.scene?JSON.stringify(state.scene):'';}
  function updateHistoryButtons(){if($('undoDesigner'))$('undoDesigner').disabled=!state.historyPast.length;if($('redoDesigner'))$('redoDesigner').disabled=!state.historyFuture.length;}
  function resetHistory(){state.historyPast=[];state.historyFuture=[];state.historyBurst=false;clearTimeout(state.historyTimer);updateHistoryButtons();}
  function recordHistory(){if(!state.scene)return;const snap=sceneSnapshot();if(state.historyPast[state.historyPast.length-1]!==snap)state.historyPast.push(snap);if(state.historyPast.length>80)state.historyPast.shift();state.historyFuture=[];updateHistoryButtons();}
  function beginHistoryBurst(){if(!state.historyBurst){recordHistory();state.historyBurst=true;}clearTimeout(state.historyTimer);state.historyTimer=setTimeout(()=>{state.historyBurst=false;},650);}
  function restoreHistory(snap){try{state.scene=normalizeScene(JSON.parse(snap));const ids=new Set(state.scene.layers.map(l=>l.id));state.selectedLayerIds=state.selectedLayerIds.filter(id=>ids.has(id));if(!ids.has(state.selectedLayerId))state.selectedLayerId=state.selectedLayerIds[0]||state.scene.layers.at(-1)?.id||null;syncSceneBackgroundControls();renderLayerList();loadSelectedLayerControls();scheduleEditorPreview();}catch(e){toast('Could not restore Designer history',true);}}
  function undoDesigner(){if(!state.scene||!state.historyPast.length)return;state.historyFuture.push(sceneSnapshot());restoreHistory(state.historyPast.pop());updateHistoryButtons();}
  function redoDesigner(){if(!state.scene||!state.historyFuture.length)return;state.historyPast.push(sceneSnapshot());restoreHistory(state.historyFuture.pop());updateHistoryButtons();}
  function selectionLayers(){const ids=new Set(state.selectedLayerIds||[]);if(state.selectedLayerId)ids.add(state.selectedLayerId);return (state.scene?.layers||[]).filter(l=>ids.has(l.id));}
  function setSelection(ids,primary=null){state.selectedLayerIds=[...new Set(ids.filter(Boolean))];state.selectedLayerId=primary&&state.selectedLayerIds.includes(primary)?primary:(state.selectedLayerIds[0]||null);}
  function selectionBounds(layers=selectionLayers()){if(!layers.length)return null;const x=Math.min(...layers.map(l=>+l.x||0)),y=Math.min(...layers.map(l=>+l.y||0));const x2=Math.max(...layers.map(l=>(+l.x||0)+(+l.w||1))),y2=Math.max(...layers.map(l=>(+l.y||0)+(+l.h||1)));return{x,y,w:x2-x,h:y2-y,x2,y2};}


  // Portable content, layer clipboard and preview simulation ----------------
  function isTypingTarget(el=document.activeElement){return !!el && (['INPUT','TEXTAREA','SELECT'].includes(el.tagName)||el.isContentEditable);}
  function applyPreviewSimulation(img,mode,logicalW,logicalH){
    if(!img)return;mode=['pixels','p5','smooth'].includes(mode)?mode:'p5';img.dataset.previewMode=mode;img.classList.remove('preview-pixels','preview-p5','preview-smooth');img.classList.add(`preview-${mode}`);
    img.style.webkitMaskImage='';img.style.maskImage='';img.style.webkitMaskSize='';img.style.maskSize='';img.style.webkitMaskRepeat='';img.style.maskRepeat='';
    img.style.imageRendering=mode==='smooth'?'auto':'pixelated';
    if(mode==='p5')requestAnimationFrame(()=>{const r=img.getBoundingClientRect();const w=Math.max(1,+logicalW||1),h=Math.max(1,+logicalH||1);if(!r.width||!r.height)return;const cellW=r.width/w,cellH=r.height/h;const dot='radial-gradient(ellipse at center, #000 0 34%, rgba(0,0,0,.98) 38%, rgba(0,0,0,.75) 41%, transparent 47%)';img.style.webkitMaskImage=dot;img.style.maskImage=dot;img.style.webkitMaskSize=`${cellW}px ${cellH}px`;img.style.maskSize=`${cellW}px ${cellH}px`;img.style.webkitMaskRepeat='repeat';img.style.maskRepeat='repeat';});
  }
  function refreshPreviewSimulation(){const logical=logicalSize();if($('editorPreview'))applyPreviewSimulation($('editorPreview'),$('designerPreviewMode')?.value||'p5',state.scene?.design_width||logical.w,state.scene?.design_height||logical.h);if($('livePreview'))applyPreviewSimulation($('livePreview'),$('livePreviewMode')?.value||'p5',state.displayWidth||logical.w,state.displayHeight||logical.h);}
  function setPreviewMode(which,mode){localStorage.setItem(`pimatrixPreviewMode:${which}`,mode);refreshPreviewSimulation();}
  function downloadPortable(kind,id){if(kind==='configuration'){location.href='/api/portable/export/configuration';return;}if(!id){toast(`Save or select a ${kind} first`,true);return;}location.href=`/api/portable/export/${encodeURIComponent(kind)}/${encodeURIComponent(id)}`;}
  async function importPortableFile(file,expectedKind=''){
    if(!file)return null;if(expectedKind==='configuration'&&!confirm('Import this portable configuration?\n\nMessages, components, playlists, schedules, rules, brightness profiles and display settings will be replaced. User accounts and FPP are left unchanged.'))return null;
    const fd=new FormData();fd.append('file',file);try{const r=await api('/api/portable/import',{method:'POST',body:fd});toast(`${expectedKind==='configuration'?'Configuration':expectedKind.charAt(0).toUpperCase()+expectedKind.slice(1)} imported`);await refreshContent();
      if(can('messages')){state.assets=await api('/api/assets');state.videos=await api('/api/videos');state.shaders=await api('/api/shaders');state.fonts=await api('/api/fonts');state.components=await api('/api/components');populateAssets();populateVideos();populateShaders();populateFonts();populateComponents();}
      if(r.message_id&&can('messages'))selectMessage(r.message_id);if(r.playlist_id&&can('playlists'))selectPlaylist(r.playlist_id);return r;
    }catch(e){toast(e.message,true);return null;}
  }
  function copySelectedLayers(){const ls=selectionLayers();if(!ls.length){toast('Select one or more layers to copy',true);return;}const zoneIds=new Set(ls.map(l=>l.zone_id).filter(Boolean)),zones=(state.scene?.zones||[]).filter(z=>zoneIds.has(z.id)).map(deepClone);const clip={format:1,copied_at:Date.now(),design_width:state.scene?.design_width||logicalSize().w,design_height:state.scene?.design_height||logicalSize().h,layers:ls.map(deepClone),zones};localStorage.setItem('pimatrixLayerClipboard',JSON.stringify(clip));toast(`${ls.length} layer${ls.length===1?'':'s'} copied`);updateClipboardButton();}
  function layerClipboard(){try{const c=JSON.parse(localStorage.getItem('pimatrixLayerClipboard')||'null');return c&&c.format===1&&Array.isArray(c.layers)?c:null;}catch(_){return null;}}
  function updateClipboardButton(){if($('pasteLayers'))$('pasteLayers').disabled=!layerClipboard();}
  function pasteCopiedLayers(){const clip=layerClipboard();if(!clip?.layers?.length||!state.scene){toast('Layer clipboard is empty',true);return;}recordHistory();const zoneMap=new Map(),groupMap=new Map();for(const source of clip.zones||[]){const z=deepClone(source),old=z.id;z.id=`Z${uid().slice(1)}`;z.name=`${z.name||'Zone'} copy`;zoneMap.set(old,z.id);state.scene.zones.push(z);}const maxZ=state.scene.layers.reduce((m,x)=>Math.max(m,+x.z||0),0),added=[];clip.layers.forEach((source,i)=>{const l=deepClone(source),oldGroup=l.group_id;l.id=uid();l.x=(+l.x||0)+2;l.y=(+l.y||0)+2;l.z=maxZ+10+i*10;if(l.zone_id&&zoneMap.has(l.zone_id))l.zone_id=zoneMap.get(l.zone_id);else if(l.zone_id)l.zone_id='';if(oldGroup){if(!groupMap.has(oldGroup))groupMap.set(oldGroup,uid().replace(/^L/,'G'));l.group_id=groupMap.get(oldGroup);}state.scene.layers.push(l);added.push(l.id);});setSelection(added,added[0]);renderLayerList();loadSelectedLayerControls();scheduleEditorPreview();toast(`${added.length} layer${added.length===1?'':'s'} pasted`);}
  function showShortcutHelp(show=true){$('shortcutModal')?.classList.toggle('hidden',!show);}

  // Colour picker -------------------------------------------------------
  // Preset colours are intentionally generic UI data rather than being tied to
  // a particular customer/brand.  The initial palette is sampled from the five
  // background circles in the supplied Fledglings logo.
  const PRESET_COLOURS = [
    {name:'Orange',value:'#b84921'},
    {name:'Pink',value:'#e1b2c2'},
    {name:'Green',value:'#b5d889'},
    {name:'Blue',value:'#91cad6'},
    {name:'Deep teal',value:'#003748'}
  ];
  let activeColourInput=null,activeColourTrigger=null,colourPopover=null;
  function normaliseHex(value,fallback='#000000'){
    const v=String(value||'').trim().toLowerCase();
    if(/^#[0-9a-f]{6}$/.test(v))return v;
    if(/^#[0-9a-f]{3}$/.test(v))return '#'+v.slice(1).split('').map(c=>c+c).join('');
    return fallback;
  }
  function contrastingText(hex){
    const v=normaliseHex(hex).slice(1),r=parseInt(v.slice(0,2),16),g=parseInt(v.slice(2,4),16),b=parseInt(v.slice(4,6),16);
    return (r*299+g*587+b*114)/1000>150?'#071018':'#ffffff';
  }
  function syncColourTrigger(input){
    const trigger=input?document.querySelector(`.colour-picker-trigger[data-colour-for="${CSS.escape(input.id)}"]`):null;if(!trigger)return;
    const value=normaliseHex(input.value);trigger.querySelector('.colour-picker-chip').style.background=value;trigger.querySelector('.colour-picker-value').textContent=value.toUpperCase();
    const match=PRESET_COLOURS.find(c=>c.value===value);trigger.classList.toggle('is-preset',!!match);trigger.title=match?`${match.name} · ${value.toUpperCase()}`:`Custom colour · ${value.toUpperCase()}`;
  }
  function syncAllColourPickers(){document.querySelectorAll('input[type="color"][data-colour-enhanced="1"]').forEach(syncColourTrigger);}
  function setColourPickerMode(mode){
    if(!colourPopover)return;mode=mode==='custom'?'custom':'preset';localStorage.setItem('pimatrixColourPickerMode',mode);
    colourPopover.querySelectorAll('[data-colour-mode]').forEach(b=>b.classList.toggle('active',b.dataset.colourMode===mode));
    colourPopover.querySelector('.colour-preset-panel').classList.toggle('hidden',mode!=='preset');colourPopover.querySelector('.colour-custom-panel').classList.toggle('hidden',mode!=='custom');
  }
  function applyColourToActive(value){
    if(!activeColourInput)return;value=normaliseHex(value,activeColourInput.value||'#000000');if(activeColourInput.value===value){syncColourTrigger(activeColourInput);return;}
    activeColourInput.value=value;syncColourTrigger(activeColourInput);activeColourInput.dispatchEvent(new Event('input',{bubbles:true}));activeColourInput.dispatchEvent(new Event('change',{bubbles:true}));
  }
  function hexToRgb(hex){
    const v=normaliseHex(hex).slice(1);return {r:parseInt(v.slice(0,2),16),g:parseInt(v.slice(2,4),16),b:parseInt(v.slice(4,6),16)};
  }
  function rgbToHex(r,g,b){
    const h=n=>clamp(Math.round(Number(n)||0),0,255).toString(16).padStart(2,'0');return `#${h(r)}${h(g)}${h(b)}`;
  }
  function refreshColourPopover(){
    if(!colourPopover||!activeColourInput)return;const value=normaliseHex(activeColourInput.value),rgb=hexToRgb(value);
    colourPopover.querySelector('.colour-current-chip').style.background=value;colourPopover.querySelector('.colour-current-value').textContent=value.toUpperCase();
    const native=colourPopover.querySelector('.colour-native-picker');native.value=value;
    colourPopover.querySelector('.colour-custom-swatch').style.background=value;
    colourPopover.querySelector('.colour-hex-input').value=value.toUpperCase();
    colourPopover.querySelector('.colour-r').value=rgb.r;colourPopover.querySelector('.colour-g').value=rgb.g;colourPopover.querySelector('.colour-b').value=rgb.b;
    colourPopover.querySelectorAll('[data-preset-colour]').forEach(b=>b.classList.toggle('active',b.dataset.presetColour===value));
  }
  function closeColourPopover(){if(!colourPopover)return;colourPopover.classList.add('hidden');activeColourInput=null;activeColourTrigger=null;}
  function positionColourPopover(trigger){
    if(!colourPopover||!trigger)return;colourPopover.classList.remove('hidden');const r=trigger.getBoundingClientRect(),pw=310,margin=10;let left=Math.min(window.innerWidth-pw-margin,Math.max(margin,r.left));let top=r.bottom+7;
    const ph=colourPopover.offsetHeight||260;if(top+ph>window.innerHeight-margin)top=Math.max(margin,r.top-ph-7);colourPopover.style.left=`${Math.round(left)}px`;colourPopover.style.top=`${Math.round(top)}px`;
  }
  function openColourPopover(input,trigger){
    activeColourInput=input;activeColourTrigger=trigger;refreshColourPopover();setColourPickerMode(localStorage.getItem('pimatrixColourPickerMode')||'preset');positionColourPopover(trigger);
  }
  function createColourPopover(){
    if(colourPopover)return;const pop=document.createElement('div');pop.id='colourPickerPopover';pop.className='colour-picker-popover hidden';pop.setAttribute('role','dialog');pop.setAttribute('aria-label','Choose colour');
    pop.innerHTML=`<div class="colour-popover-head"><div class="colour-current"><span class="colour-current-chip"></span><strong class="colour-current-value">#000000</strong></div><button type="button" class="colour-close" aria-label="Close colour picker">×</button></div><div class="colour-mode-tabs"><button type="button" data-colour-mode="preset">Preset colours</button><button type="button" data-colour-mode="custom">Custom colour</button></div><div class="colour-preset-panel"><p>Preset palette</p><div class="colour-preset-grid">${PRESET_COLOURS.map(c=>`<button type="button" class="colour-preset" data-preset-colour="${c.value}" title="${c.name} · ${c.value.toUpperCase()}"><span style="background:${c.value};color:${contrastingText(c.value)}"></span><small>${c.name}</small></button>`).join('')}</div><p class="colour-preset-hint">Five colours sampled from the supplied logo.</p></div><div class="colour-custom-panel hidden"><input type="color" class="colour-native-picker" value="#000000" tabindex="-1" aria-hidden="true"><button type="button" class="colour-custom-choose"><span class="colour-custom-swatch"></span><span><strong>Choose custom colour…</strong><small>Open the system colour picker</small></span></button><label class="colour-hex-label">Hex value<input class="colour-hex-input" maxlength="7" value="#000000" spellcheck="false"></label><div class="colour-rgb-grid"><label>R<input type="number" class="colour-r" min="0" max="255" value="0"></label><label>G<input type="number" class="colour-g" min="0" max="255" value="0"></label><label>B<input type="number" class="colour-b" min="0" max="255" value="0"></label></div><p class="colour-custom-hint">Use the picker, type a hex colour, or enter RGB values.</p></div>`;
    document.body.appendChild(pop);colourPopover=pop;
    pop.querySelector('.colour-close').addEventListener('click',closeColourPopover);pop.querySelectorAll('[data-colour-mode]').forEach(b=>b.addEventListener('click',()=>setColourPickerMode(b.dataset.colourMode)));
    pop.querySelectorAll('[data-preset-colour]').forEach(b=>b.addEventListener('click',()=>{applyColourToActive(b.dataset.presetColour);refreshColourPopover();}));
    const native=pop.querySelector('.colour-native-picker');native.addEventListener('input',e=>{applyColourToActive(e.target.value);refreshColourPopover();});native.addEventListener('change',e=>{applyColourToActive(e.target.value);refreshColourPopover();});
    pop.querySelector('.colour-custom-choose').addEventListener('click',()=>{try{if(typeof native.showPicker==='function')native.showPicker();else native.click();}catch(_){native.click();}});
    pop.querySelector('.colour-custom-swatch').addEventListener('click',e=>{e.preventDefault();e.stopPropagation();try{if(typeof native.showPicker==='function')native.showPicker();else native.click();}catch(_){native.click();}});
    const hex=pop.querySelector('.colour-hex-input');const applyHex=()=>{const v=normaliseHex(hex.value,'');if(v){hex.classList.remove('invalid');applyColourToActive(v);refreshColourPopover();}else hex.classList.add('invalid');};hex.addEventListener('input',()=>{hex.classList.remove('invalid');if(/^#[0-9a-fA-F]{6}$/.test(hex.value))applyHex();});hex.addEventListener('change',applyHex);hex.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();applyHex();}});
    const applyRgb=()=>{const r=pop.querySelector('.colour-r'),g=pop.querySelector('.colour-g'),b=pop.querySelector('.colour-b');applyColourToActive(rgbToHex(r.value,g.value,b.value));refreshColourPopover();};pop.querySelectorAll('.colour-r,.colour-g,.colour-b').forEach(el=>{el.addEventListener('input',applyRgb);el.addEventListener('change',applyRgb);});
  }
  function enhanceColourPickers(){
    createColourPopover();document.querySelectorAll('input[type="color"]').forEach(input=>{if(input.dataset.colourEnhanced)return;input.dataset.colourEnhanced='1';const wrap=document.createElement('div');wrap.className='colour-picker-control';input.parentNode.insertBefore(wrap,input);wrap.appendChild(input);input.classList.add('colour-native-source');input.tabIndex=-1;input.setAttribute('aria-hidden','true');
      const trigger=document.createElement('button');trigger.type='button';trigger.className='colour-picker-trigger';trigger.dataset.colourFor=input.id;trigger.innerHTML='<span class="colour-picker-chip"></span><span class="colour-picker-value"></span><span class="colour-picker-chevron">▾</span>';wrap.insertBefore(trigger,input);trigger.addEventListener('click',e=>{e.preventDefault();e.stopPropagation();if(activeColourInput===input&&!colourPopover.classList.contains('hidden'))closeColourPopover();else openColourPopover(input,trigger);});input.addEventListener('input',()=>{syncColourTrigger(input);if(activeColourInput===input)refreshColourPopover();});syncColourTrigger(input);
    });
    document.addEventListener('pointerdown',e=>{if(!colourPopover||colourPopover.classList.contains('hidden'))return;if(colourPopover.contains(e.target)||activeColourTrigger?.contains(e.target))return;closeColourPopover();});document.addEventListener('keydown',e=>{if(e.key==='Escape')closeColourPopover();});window.addEventListener('resize',()=>activeColourTrigger&&positionColourPopover(activeColourTrigger));window.addEventListener('scroll',()=>activeColourTrigger&&positionColourPopover(activeColourTrigger),true);
  }

  // Navigation
  function can(permission){return permission==='dashboard'||!!state.auth?.user?.permissions?.[permission];}
  function showDashboard(){
    $$('.tab').forEach(x=>x.classList.toggle('active',x.dataset.tab==='dashboard'));
    $$('.page').forEach(x=>x.classList.toggle('active',x.id==='page-dashboard'));
    $('settingsMenuToggle').classList.remove('menu-active');
    setSettingsMenu(false);
    scheduleLivePreview(0);
  }
  function applyPermissions(){
    const user=state.auth?.user;if(!user)return;
    $$('[data-permission]').forEach(el=>{const allowed=can(el.dataset.permission);el.classList.toggle('allowed',allowed);el.classList.toggle('permission-denied',!allowed);});
    $('currentUserName').textContent=user.display_name||user.username;$('currentUserInitial').textContent=(user.display_name||user.username||'U').trim().charAt(0).toUpperCase();
    const settingsItems=$$('.settings-menu-item');
    $('settingsMenu').classList.toggle('hidden',!settingsItems.some(el=>can(el.dataset.permission)));
    const active=document.querySelector('[data-tab].active');if(active?.dataset.permission&&!can(active.dataset.permission))showDashboard();
  }
  async function refreshAuth(){state.auth=await api('/api/auth/me');applyPermissions();return state.auth;}

  function setSettingsMenu(open){
    $('settingsMenuPanel').classList.toggle('hidden',!open);
    $('settingsMenuToggle').setAttribute('aria-expanded',open?'true':'false');
  }
  $('settingsMenuToggle').addEventListener('click',ev=>{ev.stopPropagation();setSettingsMenu($('settingsMenuPanel').classList.contains('hidden'));});
  document.addEventListener('click',ev=>{if(!$('settingsMenu').contains(ev.target))setSettingsMenu(false);});
  document.addEventListener('keydown',ev=>{if(ev.key==='Escape')setSettingsMenu(false);});

  $$('.tab').forEach(btn => btn.addEventListener('click', () => {
    $$('.tab').forEach(x=>x.classList.remove('active')); btn.classList.add('active');
    $$('.page').forEach(x=>x.classList.remove('active')); $(`page-${btn.dataset.tab}`).classList.add('active');
    if (btn.dataset.tab === 'setup') { loadFppSetup(); loadDiagnostics(true); loadLicence(); }
    if (btn.dataset.tab === 'upgrade') loadUpgradeStatus();
    if (btn.dataset.tab === 'backup') loadBackups(true);
    if (btn.dataset.tab === 'users') loadUsers();
    if (btn.dataset.tab === 'messages') { showMessageLibrary(); renderMessageList(); }
    if (btn.dataset.tab === 'dashboard') scheduleLivePreview(0);
    $('settingsMenuToggle').classList.toggle('menu-active',btn.classList.contains('settings-menu-item'));
    setSettingsMenu(false);
  }));

  async function loadAll() {
    try {
      await refreshAuth();
      const [settings,options,licence] = await Promise.all([api('/api/settings'),api('/api/content-options'),api('/api/license')]);
      state.settings=settings;state.license=licence;state.messageOptions=options.messages||[];state.playlistOptions=options.playlists||[];renderLicence();
      const jobs=[];
      if(can('messages'))jobs.push(Promise.all([api('/api/messages'),api('/api/fonts'),api('/api/assets'),api('/api/videos'),api('/api/shaders'),api('/api/components')]).then(([messages,fonts,assets,videos,shaders,components])=>Object.assign(state,{messages,fonts,assets,videos,shaders,components})));
      if(can('playlists'))jobs.push(api('/api/playlists').then(v=>state.playlists=v));
      if(can('schedules'))jobs.push(Promise.all([api('/api/schedules'),api('/api/conditional-rules'),api('/api/brightness-schedules')]).then(([a,b,c])=>{state.schedules=a;state.conditionalRules=b;state.brightnessSchedules=c;}));
      if(can('users'))jobs.push(api('/api/users').then(v=>state.users=v));
      await Promise.all(jobs);
      populateSharedSelectors();
      if(can('messages')){renderMessageList();populateFonts();populateAssets();populateVideos();populateShaders();populateComponents();showMessageLibrary();}
      if(can('playlists')){renderPlaylistList();if(!state.selectedPlaylist&&state.playlists.length)selectPlaylist(state.playlists[0].id);else if(!state.playlists.length)blankPlaylist();}
      if(can('schedules')){renderScheduleList();if(!state.selectedSchedule&&state.schedules.length)selectSchedule(state.schedules[0].id);else if(!state.schedules.length)blankSchedule();renderConditionalRuleList();state.conditionalRules.length?selectConditionalRule(state.selectedConditionalRule||state.conditionalRules[0].id):blankConditionalRule();renderBrightnessScheduleList();state.brightnessSchedules.length?selectBrightnessSchedule(state.selectedBrightnessSchedule||state.brightnessSchedules[0].id):blankBrightnessSchedule();populateEmergencySetting();}
      if(can('display_setup')){populateSettings();await loadGpioControls(true);}
      if(can('users')){renderUserList();if(!state.selectedUser&&state.users.length)selectUser(state.users[0].id);else if(!state.users.length)blankUser();}
    } catch(e){ toast(e.message,true); }
  }

  // ----------------------- Messages / Designer -----------------------
  function setupMessageEditorWorkspace(){
    const card=document.querySelector('.messages-editor-card');
    if(!card||card.querySelector(':scope > .message-editor-workspace'))return;
    const head=card.querySelector(':scope > .card-head'),workspace=document.createElement('div'),rail=document.createElement('aside'),main=document.createElement('section');
    workspace.className='message-editor-workspace';rail.className='message-editor-rail';main.className='message-editor-main';
    [...card.children].filter(el=>el!==head).forEach(el=>main.appendChild(el));
    workspace.append(rail,main);card.appendChild(workspace);
    const designer=main.querySelector('#designerEditor');
    [designer?.querySelector('.designer-commandbar'),designer?.querySelector('.designer-toolbar'),designer?.querySelector('.designer-layer-panel')].filter(Boolean).forEach(el=>rail.appendChild(el));
  }
  function showMessageLibrary(focusSearch=false){
    const ws=$('messagesWorkspace');if(!ws)return;ws.classList.add('messages-library-view');ws.classList.remove('messages-editor-view');
    if(focusSearch)setTimeout(()=>$('messageSearch')?.focus(),0);
  }
  function showMessageEditor(){
    const ws=$('messagesWorkspace');if(!ws)return;ws.classList.remove('messages-library-view');ws.classList.add('messages-editor-view');scheduleEditorPreview();
  }
  function logicalSize(){
    const s=state.settings||{panel_width:64,panel_height:32,panels_across:1,panels_down:1,display_rotation:0};
    const pw=(+s.panel_width||64)*(+s.panels_across||1), ph=(+s.panel_height||32)*(+s.panels_down||1);
    return (+s.display_rotation===90||+s.display_rotation===270)?{w:ph,h:pw}:{w:pw,h:ph};
  }
  function sceneSummary(m){
    if ((m.editor_mode||'quick')!=='designer') return 'Designer · legacy message';
    try{const sc=JSON.parse(m.scene_json||'{}');const n=Array.isArray(sc.layers)?sc.layers.length:0;return `Designer · ${n} layer${n===1?'':'s'}`;}catch(_){return 'Designer';}
  }
  function renderMessageList() {
    const q=String($('messageSearch')?.value||'').trim().toLowerCase();
    const rows=q?state.messages.filter(m=>`${m.name||''} ${sceneSummary(m)}`.toLowerCase().includes(q)):state.messages;
    $('messageList').innerHTML = rows.length ? rows.map(m=>`<div class="list-item ${Number(state.selectedMessage)===Number(m.id)?'active':''}" data-message-id="${m.id}"><strong>${esc(m.name)}</strong><small>${esc(sceneSummary(m))}</small></div>`).join('') : `<p class="muted">${q?'No matching messages.':'No saved messages yet.'}</p>`;
    $$('#messageList [data-message-id]').forEach(el=>el.addEventListener('click',()=>selectMessage(+el.dataset.messageId)));
  }
  function baseAnimatedLayer(type,name){
    const {w,h}=logicalSize();
    return {id:uid(),type,name,enabled:true,x:0,y:0,w,h,z:10,opacity:100,rotation:0,delay:0,animation:'static',speed:30,effect_period:1,blink_duty:.5,entrance_effect:'none',entrance_duration:.5,exit_effect:'none',exit_after:0,exit_duration:.5};
  }
  function defaultTextLayer(name='Text'){
    const {w,h}=logicalSize(); const l=baseAnimatedLayer('text',name);
    return Object.assign(l,{text:'YOUR MESSAGE',font:'',font_size:Math.max(8,Math.round(h*.7)),auto_fit:true,wrap:false,overflow:'manual',text_transform:'none',typewriter_speed:12,color:'#ffffff',color2:'#ff00ff',color_effect:'none',color_speed:1,color_palette:'#ff0000,#ffff00,#00ff00,#00aaff',glow:0,glow_color:'#ffffff',outline_color:'#000000',outline_width:0,padding:1,align:'center',valign:'middle',line_spacing:.12,shadow_color:'#000000',shadow_x:0,shadow_y:0,render_mode:'pixel',pixel_scale:1,pixel_bold:false,letter_spacing:0});
  }
  function defaultImageLayer(){
    const {w,h}=logicalSize(); const l=baseAnimatedLayer('image','Image');
    return Object.assign(l,{w:Math.max(16,Math.round(w*.25)),h,image_path:'',fit:'contain',media_speed:1,media_loop:true});
  }
  function defaultVideoLayer(){
    const {w,h}=logicalSize(); const l=baseAnimatedLayer('video','Video');
    return Object.assign(l,{w:Math.max(32,Math.round(w*.5)),h,video_path:'',fit:'contain',media_speed:1,media_loop:true});
  }
  function shaderDefaults(asset){
    const out={};for(const item of asset?.inputs||[]){const type=String(item.type||'float').toLowerCase();let v=item.default;if(v===undefined||v===null){if(type==='bool'||type==='event')v=false;else if(type==='point2d')v=[0,0];else if(type==='color')v=[1,1,1,1];else v=0;}out[item.name]=deepClone(v);}return out;
  }
  function defaultShaderLayer(){
    const {w,h}=logicalSize();const l=baseAnimatedLayer('shader','Shader');const asset=(state.shaders||[])[0];
    return Object.assign(l,{w,h,shader_id:asset?.id||'',shader_params:shaderDefaults(asset),shader_fps:15,shader_time_scale:1,shader_quality:'auto',shader_live_weather:false,shader_weather_lat:53.55,shader_weather_lon:-2.52,shader_weather_refresh:600});
  }
  function defaultWidgetLayer(){
    const {w,h}=logicalSize(); const l=baseAnimatedLayer('widget','Clock');
    return Object.assign(l,{widget_type:'clock',widget_format:'%H:%M',refresh_seconds:300,clock_ring_color:'#ffffff',clock_tick_color:'#ffffff',clock_hour_color:'#ffffff',clock_minute_color:'#ffffff',clock_second_color:'#ff3030',clock_face_color:'#000000',clock_show_seconds:true,clock_fill_face:false,countdown_target:'',countdown_format:'{D}d {HH}:{MM}:{SS}',weather_lat:53.55,weather_lon:-2.52,weather_display:'animated',weather_temp_unit:'c',weather_wind_unit:'mph',weather_show_icon:true,weather_animate_icon:true,weather_show_condition:true,weather_show_feels:true,weather_show_wind:true,weather_show_gusts:false,weather_show_humidity:false,weather_show_precip:false,weather_cycle_details:true,weather_detail_period:2.5,weather_template:'{TEMP}{TEMP_UNIT} {CONDITION}',data_url:'',json_path:'',rss_item:0,widget_prefix:'',widget_suffix:'',font:'',font_size:Math.max(8,Math.round(h*.7)),auto_fit:true,wrap:false,overflow:'manual',text_transform:'none',typewriter_speed:12,color:'#ffffff',color2:'#00ffff',color_effect:'none',color_speed:1,color_palette:'#ff0000,#ffff00,#00ff00,#00aaff',glow:0,glow_color:'#ffffff',outline_color:'#000000',outline_width:0,padding:1,align:'center',valign:'middle',line_spacing:.12,shadow_color:'#000000',shadow_x:0,shadow_y:0,render_mode:'pixel',pixel_scale:1,pixel_bold:false,letter_spacing:0});
  }
  function defaultShapeLayer(){
    const {w,h}=logicalSize(); return {id:uid(),type:'shape',name:'Shape',enabled:true,x:0,y:0,w:Math.max(16,Math.round(w*.25)),h,z:0,opacity:100,rotation:0,delay:0,animation:'static',speed:30,effect_period:1,blink_duty:.5,shape:'rectangle',fill:'#2255aa',border_color:'#ffffff',border_width:0,radius:0};
  }
  function defaultIconLayer(name='Icon',iconName='info'){
    const {w,h}=logicalSize(); const l=baseAnimatedLayer('icon',name);
    const size=Math.max(8,Math.min(h,Math.round(w*.18)));
    return Object.assign(l,{w:size,h:size,icon_name:iconName,icon_color:'#ffffff',icon_color2:'#31506a',icon_effect:'none',icon_period:1});
  }
  function templateScene(kind='headline'){
    const {w,h}=logicalSize();
    const C={orange:'#B84921',pink:'#E1B2C2',green:'#B5D889',blue:'#91CAD6',teal:'#003748',white:'#ffffff',red:'#ff3030',yellow:'#ffd45d'};
    const bg={mode:'solid',color1:'#000000',color2:'#000000'}; let layers=[],zones=[];
    const iw=Math.max(10,Math.min(h,Math.round(w*.18)));
    const mkText=(name,text,x,y,ww,hh,extra={})=>{const t=defaultTextLayer(name);Object.assign(t,{text,x,y,w:Math.max(1,ww),h:Math.max(1,hh),auto_fit:true,render_mode:'pixel',color:C.white,padding:1},extra);return t;};
    const mkIcon=(name,icon,x,y,ww=iw,hh=h,extra={})=>{const i=defaultIconLayer(name,icon);Object.assign(i,{x,y,w:Math.max(1,ww),h:Math.max(1,hh),icon_color:C.white,icon_color2:C.teal},extra);return i;};
    const mkShape=(name,x,y,ww,hh,fill,extra={})=>{const sh=defaultShapeLayer();Object.assign(sh,{name,x,y,w:Math.max(1,ww),h:Math.max(1,hh),fill,border_width:0},extra);return sh;};
    const restX=iw+2,restW=Math.max(1,w-restX);

    if(kind==='ticker'){
      const t=mkText('Ticker','YOUR SCROLLING MESSAGE',0,0,w,h,{auto_fit:false,font_size:Math.max(8,Math.round(h*.65)),animation:'scroll-left',speed:35});layers=[t];
    } else if(kind==='clock'){
      const time=defaultWidgetLayer();Object.assign(time,{name:'Time',widget_type:'clock',widget_format:'%H:%M',x:0,y:0,w:Math.round(w*.42),h,auto_fit:true,align:'center'});
      const date=defaultWidgetLayer();Object.assign(date,{name:'Day & date',widget_type:'date',widget_format:'%a %d/%m',x:Math.round(w*.42),y:0,w:w-Math.round(w*.42),h,auto_fit:true,align:'center'});layers=[time,date];
    } else if(kind==='analog-clock'){
      const clock=defaultWidgetLayer();const size=Math.min(h,w);Object.assign(clock,{name:'Analogue clock',widget_type:'analog-clock',x:Math.max(0,Math.round((w-size)/2)),y:0,w:size,h:size,animation:'static'});layers=[clock];
    } else if(kind==='notice'){
      const bandW=Math.max(iw,Math.round(w*.25));const band=mkShape('Notice panel',0,0,bandW,h,C.orange);const label=mkText('Notice label','NOTICE',0,0,bandW,h,{z:5});const body=mkText('Message','IMPORTANT MESSAGE',bandW+2,0,Math.max(1,w-bandW-2),h,{z:5});layers=[band,label,body];
    } else if(kind==='welcome'){
      layers=[mkIcon('Welcome icon','smile',0,0,iw,h,{icon_color:C.green,icon_effect:'pulse',icon_period:1.4}),mkText('Welcome','WELCOME',restX,0,restW,h,{entrance_effect:'slide-right',entrance_duration:.6})];
    } else if(kind==='opening-hours'){
      const clock=defaultWidgetLayer();Object.assign(clock,{name:'Clock',widget_type:'analog-clock',x:0,y:0,w:iw,h:Math.min(iw,h),clock_ring_color:C.green,clock_tick_color:C.white,clock_hour_color:C.white,clock_minute_color:C.white,clock_show_seconds:false});
      const text=mkText('Opening hours','OPEN TODAY 10:00–16:00',restX,0,restW,h,{color:C.green});layers=[clock,text];
    } else if(kind==='information'){
      layers=[mkIcon('Information','info',0,0,iw,h,{icon_color:C.blue}),mkText('Information text','INFORMATION',restX,0,restW,h)];
    } else if(kind==='queue'){
      layers=[mkIcon('Queue','queue',0,0,iw,h,{icon_color:C.blue,icon_effect:'native',icon_period:1.1}),mkText('Queue message','PLEASE WAIT HERE',restX,0,restW,h,{animation:'auto-marquee',speed:24})];
    } else if(kind.startsWith('direction-')){
      const dir=kind.split('-')[1],icon=`arrow-${dir}`;layers=[mkIcon('Direction',icon,0,0,iw,h,{icon_color:C.green,icon_effect:'chase',icon_period:.9}),mkText('Direction text','THIS WAY',restX,0,restW,h)];
    } else if(kind==='parking'){
      layers=[mkIcon('Parking','parking',0,0,iw,h,{icon_color:C.blue}),mkText('Parking text','PARKING',restX,0,restW,h)];
    } else if(kind==='wifi'){
      layers=[mkIcon('Wi-Fi','wifi',0,0,iw,h,{icon_color:C.blue,icon_color2:C.teal,icon_effect:'native',icon_period:1.3}),mkText('Wi-Fi text','FREE WI-FI',restX,0,restW,h)];
    } else if(kind==='sale'){
      bg.color1=C.orange;bg.color2=C.orange;const tag=mkIcon('Sale','sale-tag',0,0,iw,h,{icon_color:C.white,icon_effect:'pulse',icon_period:1});const text=mkText('Sale text','SALE TODAY',restX,0,restW,h,{color:C.white,pixel_bold:true});layers=[tag,text];
    } else if(kind==='price'){
      const tag=mkIcon('Price tag','sale-tag',0,0,iw,h,{icon_color:C.pink});const text=mkText('Price','£00.00',restX,0,restW,h,{color:C.white,pixel_bold:true});layers=[tag,text];
    } else if(kind==='event'){
      layers=[mkIcon('Event star','star',0,0,iw,h,{icon_color:C.yellow,icon_effect:'spin',icon_period:5}),mkText('Event text','EVENT TODAY',restX,0,restW,h)];
    } else if(kind==='birthday'){
      layers=[mkIcon('Birthday gift','gift',0,0,iw,h,{icon_color:C.pink,icon_effect:'pulse',icon_period:1.3}),mkText('Birthday message','HAPPY BIRTHDAY!',restX,0,restW,h,{color:C.pink})];
    } else if(kind==='christmas'){
      layers=[mkIcon('Snowflake','snowflake',0,0,iw,h,{icon_color:C.blue,icon_effect:'spin',icon_period:6}),mkText('Christmas message','MERRY CHRISTMAS',restX,0,restW,h,{color:C.white})];
    } else if(kind==='water-swim'){
      const waterH=Math.max(6,Math.min(12,Math.round(h*.31))),waterY=Math.max(0,h-waterH);const water=baseAnimatedLayer('shader','Water ripples');Object.assign(water,{x:0,y:waterY,w,h:waterH,z:0,shader_id:'builtin:Water-Ripples.fs',shader_fps:15,shader_time_scale:1,shader_quality:'native',shader_params:{Style:0,Speed:1,WaveHeight:1.8,RippleSize:12,Choppiness:.35,WaterColor:[.5686,.7922,.8392,1],DeepColor:[0,.2157,.2824,1],HighlightColor:[.92,.98,1,1],WaterOpacity:.82}});const text=mkText('Water headline','SWIM / WATER',0,0,w,Math.max(8,waterY+1),{z:10,color:C.white,pixel_bold:true});layers=[water,text];
    } else if(kind==='emergency'){
      bg.color1='#220000';bg.color2='#220000';layers=[mkIcon('Warning','warning',0,0,iw,h,{icon_color:C.red,icon_effect:'flash',icon_period:.6}),mkText('Emergency text','EMERGENCY',restX,0,restW,h,{color:C.red,pixel_bold:true})];
    } else if(kind==='accessibility'){
      layers=[mkIcon('Accessibility','wheelchair',0,0,iw,h,{icon_color:C.blue}),mkText('Accessibility text','ACCESSIBLE',restX,0,restW,h)];
    } else if(kind==='countdown'){
      const labelW=Math.max(iw,Math.round(w*.3));const label=mkText('Countdown label','STARTS IN',0,0,labelW,h,{color:C.blue});const cd=defaultWidgetLayer();Object.assign(cd,{name:'Countdown',widget_type:'countdown',x:labelW+2,y:0,w:Math.max(1,w-labelW-2),h,countdown_format:'{HH}:{MM}:{SS}',auto_fit:true,color:C.white});layers=[label,cd];
    } else if(kind==='weather'){
      const ww=Math.max(1,Math.round(w*.72));const weather=defaultWidgetLayer();Object.assign(weather,{name:'Weather',widget_type:'weather',weather_display:'animated',weather_template:'{TEMP}{TEMP_UNIT} {CONDITION}',x:0,y:0,w:ww,h,color:C.white,auto_fit:true});const time=defaultWidgetLayer();Object.assign(time,{name:'Time',widget_type:'clock',widget_format:'%H:%M',x:ww+2,y:0,w:Math.max(1,w-ww-2),h,auto_fit:true});layers=[weather,time];
    } else if(kind==='split-screen'){
      const half=Math.floor(w/2);zones=[{id:'ZLEFT',name:'Left',x:0,y:0,w:half,h,color:C.blue},{id:'ZRIGHT',name:'Right',x:half,y:0,w:w-half,h,color:C.green}];
      const left=mkText('Left message','LEFT',0,0,half,h,{zone_id:'ZLEFT',color:C.blue});const right=mkText('Right message','RIGHT',half,0,w-half,h,{zone_id:'ZRIGHT',color:C.green});layers=[left,right];
    } else if(kind==='thank-you'){
      layers=[mkIcon('Heart','heart',0,0,iw,h,{icon_color:C.pink,icon_effect:'native',icon_period:1.2}),mkText('Thank you','THANK YOU',restX,0,restW,h,{color:C.pink})];
    } else if(kind==='contact'){
      layers=[mkIcon('Telephone','phone',0,0,iw,h,{icon_color:C.green,icon_effect:'wiggle',icon_period:1.5}),mkText('Contact','PLEASE ASK A MEMBER OF STAFF',restX,0,restW,h,{animation:'auto-marquee',speed:22})];
    } else if(kind==='blank'){
      layers=[];
    } else {
      layers=[mkText('Headline','YOUR MESSAGE',0,0,w,h)];
    }
    layers.forEach((l,i)=>l.z=i*10);
    return {version:4,design_width:w,design_height:h,duration:10,transition_in:'none',transition_in_duration:.5,transition_out:'none',transition_out_duration:.5,background:bg,zones,layers};
  }
  function quickToScene(){
    const {w,h}=logicalSize(); const sc=templateScene('blank'); sc.background.color1=$('msgBgColor').value||'#000000';sc.background.color2=sc.background.color1;
    const text=defaultTextLayer('Text'); Object.assign(text,{text:$('msgText').value,font:$('msgFont').value,font_size:+$('msgFontSize').value||18,auto_fit:$('msgAutoFit').checked,color:$('msgTextColor').value,outline_color:$('msgOutlineColor').value,outline_width:+$('msgOutlineWidth').value||0,align:$('msgAlign').value,valign:$('msgVAlign').value,padding:+$('msgPadding').value||0,speed:+$('msgSpeed').value||30,render_mode:$('msgRenderMode').value,pixel_scale:+$('msgPixelScale').value||1,pixel_bold:$('msgPixelBold').checked,letter_spacing:+$('msgLetterSpacing').value||0});
    const dir=$('msgDirection').value; text.animation=({left:'scroll-left',right:'scroll-right',up:'scroll-up',down:'scroll-down'})[dir]||'static';
    const imgPath=$('msgImage').value, mode=$('msgImageMode').value;
    if(imgPath){
      const im=defaultImageLayer();im.image_path=imgPath;im.z=0;
      if(mode==='background-cover'||mode==='background-contain'){Object.assign(im,{x:0,y:0,w,h,fit:mode==='background-cover'?'cover':'contain'});text.z=10;}
      else if(mode==='logo-left'){const iw=Math.max(16,Math.round(w*.25));Object.assign(im,{x:0,y:0,w:iw,h,fit:'contain'});Object.assign(text,{x:iw+2,w:Math.max(1,w-iw-2),h});}
      else if(mode==='logo-right'){const iw=Math.max(16,Math.round(w*.25));Object.assign(im,{x:w-iw,y:0,w:iw,h,fit:'contain'});Object.assign(text,{x:0,w:Math.max(1,w-iw-2),h});}
      else {Object.assign(im,{x:0,y:0,w,h,fit:'contain'});if(!$('msgText').value)text.enabled=false;}
      sc.layers.push(im);
    }
    sc.layers.push(text); return sc;
  }
  function normalizeScene(sc){
    const {w,h}=logicalSize(); if(!sc||typeof sc!=='object')return templateScene('headline');
    sc.version=2;sc.design_width=+sc.design_width||w;sc.design_height=+sc.design_height||h;sc.duration=clamp(+sc.duration||10,.25,3600);
    sc.transition_in=sc.transition_in||'none';sc.transition_in_duration=clamp(+sc.transition_in_duration||.5,.05,30);sc.transition_out=sc.transition_out||'none';sc.transition_out_duration=clamp(+sc.transition_out_duration||.5,.05,30);
    sc.background=(sc.background&&typeof sc.background==='object')?sc.background:{mode:'solid',color1:'#000000',color2:'#000000'};if(!sc.background.color1)sc.background.color1='#000000';if(!sc.background.color2)sc.background.color2=sc.background.color1;if(sc.background.shader_params===undefined||typeof sc.background.shader_params!=='object')sc.background.shader_params={};if(sc.background.shader_fps===undefined)sc.background.shader_fps=15;if(sc.background.shader_time_scale===undefined)sc.background.shader_time_scale=1;if(!sc.background.shader_quality)sc.background.shader_quality='auto';if(sc.background.shader_live_weather===undefined)sc.background.shader_live_weather=false;if(sc.background.shader_weather_lat===undefined)sc.background.shader_weather_lat=53.55;if(sc.background.shader_weather_lon===undefined)sc.background.shader_weather_lon=-2.52;if(sc.background.shader_weather_refresh===undefined)sc.background.shader_weather_refresh=600;
    if(!Array.isArray(sc.layers))sc.layers=[];
    if(!Array.isArray(sc.zones))sc.zones=[];
    sc.zones=sc.zones.filter(z=>z&&typeof z==='object').slice(0,32).map((z,i)=>Object.assign({id:z.id||`Z${i+1}`,name:z.name||`Zone ${i+1}`,x:0,y:0,w:Math.max(1,Math.round((sc.design_width||logicalSize().w)/2)),h:sc.design_height||logicalSize().h,color:'#4aa3ff'},z));
    const zoneIds=new Set(sc.zones.map(z=>z.id));
    sc.layers.forEach((l,i)=>{
      if(l.group_id===undefined)l.group_id='';if(l.zone_id===undefined||!zoneIds.has(l.zone_id))l.zone_id='';
      if(!l.id)l.id=uid();if(!l.type)l.type='text';if(!l.name)l.name=`${l.type} ${i+1}`;if(l.enabled===undefined)l.enabled=true;if(l.z===undefined)l.z=i*10;if(l.opacity===undefined)l.opacity=100;if(!l.animation)l.animation='static';
      if(['text','image','video','widget','icon','shader'].includes(l.type)){if(l.entrance_effect===undefined)l.entrance_effect='none';if(l.entrance_duration===undefined)l.entrance_duration=.5;if(l.exit_effect===undefined)l.exit_effect='none';if(l.exit_after===undefined)l.exit_after=0;if(l.exit_duration===undefined)l.exit_duration=.5;}
      if(l.type==='icon'){if(!l.icon_name)l.icon_name='info';if(!l.icon_color)l.icon_color='#ffffff';if(!l.icon_color2)l.icon_color2='#31506a';if(!l.icon_effect)l.icon_effect='none';if(!l.icon_period)l.icon_period=1;}
      if(['text','widget'].includes(l.type)){if(!l.render_mode)l.render_mode='pixel';if(!l.pixel_scale)l.pixel_scale=1;if(l.pixel_bold===undefined)l.pixel_bold=false;if(l.letter_spacing===undefined)l.letter_spacing=0;if(!l.overflow)l.overflow='manual';if(!l.text_transform)l.text_transform='none';if(l.typewriter_speed===undefined)l.typewriter_speed=12;if(!l.color_effect)l.color_effect='none';if(!l.color2)l.color2='#ff00ff';if(l.color_speed===undefined)l.color_speed=1;if(l.color_palette===undefined)l.color_palette='#ff0000,#ffff00,#00ff00,#00aaff';if(l.glow===undefined)l.glow=0;if(!l.glow_color)l.glow_color=l.color||'#ffffff';}
      if(['image','video'].includes(l.type)){if(l.media_speed===undefined)l.media_speed=1;if(l.media_loop===undefined)l.media_loop=true;}
      if(l.type==='shader'){if(l.shader_params===undefined||typeof l.shader_params!=='object')l.shader_params={};if(l.shader_fps===undefined)l.shader_fps=15;if(l.shader_time_scale===undefined)l.shader_time_scale=1;if(!l.shader_quality)l.shader_quality='auto';if(l.shader_live_weather===undefined)l.shader_live_weather=false;if(l.shader_weather_lat===undefined)l.shader_weather_lat=53.55;if(l.shader_weather_lon===undefined)l.shader_weather_lon=-2.52;if(l.shader_weather_refresh===undefined)l.shader_weather_refresh=600;}
      if(l.type==='widget'){if(!l.widget_type)l.widget_type='clock';if(l.refresh_seconds===undefined)l.refresh_seconds=300;if(l.widget_type==='weather'){if(l.weather_display===undefined)l.weather_display='text';if(!l.weather_temp_unit)l.weather_temp_unit='c';if(!l.weather_wind_unit)l.weather_wind_unit='mph';if(l.weather_show_icon===undefined)l.weather_show_icon=true;if(l.weather_animate_icon===undefined)l.weather_animate_icon=true;if(l.weather_show_condition===undefined)l.weather_show_condition=true;if(l.weather_show_feels===undefined)l.weather_show_feels=true;if(l.weather_show_wind===undefined)l.weather_show_wind=true;if(l.weather_show_gusts===undefined)l.weather_show_gusts=false;if(l.weather_show_humidity===undefined)l.weather_show_humidity=false;if(l.weather_show_precip===undefined)l.weather_show_precip=false;if(l.weather_cycle_details===undefined)l.weather_cycle_details=true;if(l.weather_detail_period===undefined)l.weather_detail_period=2.5;}}
    });
    return sc;
  }
  async function loadMessageVersions(){const id=+$('messageId').value;if(!id){state.messageVersions=[];renderMessageVersions();return;}const el=$('messageVersionList');if(el)el.innerHTML='<p class="muted">Loading saved versions…</p>';try{const versions=await api(`/api/messages/${id}/versions`);if(+$('messageId').value!==id)return;state.messageVersions=versions;renderMessageVersions();}catch(e){if(+$('messageId').value!==id)return;state.messageVersions=[];renderMessageVersions(e.message);}}
  function renderMessageVersions(error=''){const el=$('messageVersionList');if(!el)return;if(error){el.innerHTML=`<p class="error-text">${esc(error)}</p>`;return;}if(!state.messageVersions.length){el.innerHTML='<p class="muted">No saved versions yet.</p>';return;}el.innerHTML=state.messageVersions.map((v,i)=>`<div class="message-version-row ${i===0?'current-revision':''}"><div><strong>Version ${v.version_number}</strong><small>${esc(String(v.created_at||'').replace('T',' '))}${v.saved_by?` · ${esc(v.saved_by)}`:''}${i===0?' · latest':''}</small></div><button class="btn secondary small" data-restore-version="${v.id}" ${i===0?'disabled':''}>Restore</button></div>`).join('');$$('[data-restore-version]').forEach(btn=>btn.addEventListener('click',()=>restoreMessageVersion(+btn.dataset.restoreVersion)));}
  async function restoreMessageVersion(versionId){const mid=+$('messageId').value,v=state.messageVersions.find(x=>+x.id===+versionId);if(!mid||!v)return;if(!confirm(`Restore Version ${v.version_number}?\n\nThe current message will remain in version history, so you can undo this restore later.`))return;try{const m=await api(`/api/messages/${mid}/versions/${versionId}/restore`,{method:'POST',body:{}});await refreshContent();$('messageHistoryPanel').open=true;selectMessage(m.id);await loadMessageVersions();toast(`Restored Version ${v.version_number}`);}catch(e){toast(e.message,true);}}

  function blankMessage() {
    showMessageEditor();
    state.selectedMessage=null;state.scene=null;state.selectedLayerId=null;state.selectedLayerIds=[];state.selectedZoneId=null;state.messageVersions=[];renderMessageVersions();resetHistory();$('messageId').value='';$('messageEditorTitle').textContent='New message';$('msgName').value='New message';
    $('msgText').value='YOUR MESSAGE';$('msgFont').value='';$('msgFontSize').value=18;$('msgRenderMode').value='pixel';$('msgPixelScale').value=1;$('msgPixelBold').checked=false;$('msgLetterSpacing').value=0;$('msgAutoFit').checked=false;$('msgTextColor').value='#ffffff';$('msgBgColor').value='#000000';$('msgOutlineColor').value='#000000';$('msgOutlineWidth').value=0;$('msgDirection').value='left';$('msgSpeed').value=30;$('speedValue').textContent='30 px/s';$('msgAlign').value='center';$('msgVAlign').value='middle';$('msgImage').value='';$('msgImageMode').value='none';$('msgImageScale').value=1;$('msgPadding').value=1;$('msgEditorMode').value='designer';
    state.scene=templateScene('headline');state.selectedLayerId=state.scene.layers.at(-1)?.id||null;state.selectedLayerIds=state.selectedLayerId?[state.selectedLayerId]:[];switchEditorMode('designer',false);renderMessageList();syncAllColourPickers();scheduleEditorPreview();loadMessageVersions();
  }
  function selectMessage(id) {
    const m=state.messages.find(x=>+x.id===+id);if(!m)return;showMessageEditor();state.selectedMessage=m.id;$('messageId').value=m.id;$('messageEditorTitle').textContent=m.name;$('msgName').value=m.name||'';$('msgText').value=m.text||'';$('msgFont').value=m.font||'';$('msgFontSize').value=m.font_size||18;$('msgRenderMode').value=m.render_mode||'smooth';$('msgPixelScale').value=m.pixel_scale||1;$('msgPixelBold').checked=!!m.pixel_bold;$('msgLetterSpacing').value=m.letter_spacing||0;$('msgAutoFit').checked=!!m.auto_fit;$('msgTextColor').value=m.text_color||'#ffffff';$('msgBgColor').value=m.background_color||'#000000';$('msgOutlineColor').value=m.outline_color||'#000000';$('msgOutlineWidth').value=m.outline_width||0;$('msgDirection').value=m.direction||'left';$('msgSpeed').value=clamp(Number(m.speed)||30,.1,500);$('speedValue').textContent=`${Number(m.speed)||30} px/s`;$('msgAlign').value=m.align||'center';$('msgVAlign').value=m.valign||'middle';$('msgImage').value=m.image_path||'';$('msgImageMode').value=m.image_mode||'none';$('msgImageScale').value=m.image_scale||1;$('msgPadding').value=m.padding??1;
    try{state.scene=m.scene_json?normalizeScene(JSON.parse(m.scene_json)):null;}catch(_){state.scene=null;}
    $('msgEditorMode').value='designer';if(!state.scene)state.scene=quickToScene();state.scene=normalizeScene(state.scene);state.selectedLayerId=state.scene?.layers?.[state.scene.layers.length-1]?.id||null;state.selectedLayerIds=state.selectedLayerId?[state.selectedLayerId]:[];state.selectedZoneId=null;state.messageVersions=[];renderMessageVersions();resetHistory();switchEditorMode('designer',false);renderMessageList();syncAllColourPickers();scheduleEditorPreview();if($('messageHistoryPanel')?.open)loadMessageVersions();
  }
  function switchEditorMode(mode,createScene=true){
    const designer=mode==='designer';$('quickEditor').classList.toggle('hidden',designer);$('designerEditor').classList.toggle('hidden',!designer);$('designerPreviewControls').classList.toggle('hidden',!designer);
    if(designer){if(!state.scene&&createScene)state.scene=quickToScene();state.scene=normalizeScene(state.scene||templateScene('headline'));if(!state.selectedLayerId&&state.scene.layers.length)state.selectedLayerId=state.scene.layers[state.scene.layers.length-1].id;if(state.selectedLayerId&&!state.selectedLayerIds.length)state.selectedLayerIds=[state.selectedLayerId];syncSceneBackgroundControls();renderLayerList();loadSelectedLayerControls();}
    else {$('designerSelection').classList.add('hidden');}
    state.previewStarted=performance.now();scheduleEditorPreview();
  }
  function messagePayload(){
    return {name:$('msgName').value.trim()||'Untitled',text:$('msgText').value,font:$('msgFont').value,font_size:+$('msgFontSize').value||18,render_mode:$('msgRenderMode').value,pixel_scale:+$('msgPixelScale').value||1,pixel_bold:$('msgPixelBold').checked,letter_spacing:+$('msgLetterSpacing').value||0,auto_fit:$('msgAutoFit').checked,text_color:$('msgTextColor').value,background_color:$('msgBgColor').value,outline_color:$('msgOutlineColor').value,outline_width:+$('msgOutlineWidth').value||0,direction:$('msgDirection').value,speed:+$('msgSpeed').value||30,align:$('msgAlign').value,valign:$('msgVAlign').value,image_path:$('msgImage').value,image_mode:$('msgImageMode').value,image_scale:+$('msgImageScale').value||1,padding:+$('msgPadding').value||0,enabled:true,editor_mode:'designer',scene_json:state.scene?JSON.stringify(state.scene):''};
  }
  async function saveMessage(showAfter=false) {
    try {const id=$('messageId').value;const m=await api(id?`/api/messages/${id}`:'/api/messages',{method:id?'PUT':'POST',body:messagePayload()});state.selectedMessage=m.id;await refreshContent();selectMessage(m.id);if($('messageHistoryPanel')?.open)await loadMessageVersions();toast('Message saved');if(showAfter){await api(`/api/messages/${m.id}/show`,{method:'POST',body:{duration:0}});toast('Showing message now');}return m;} catch(e){toast(e.message,true);}
  }
  async function duplicateMessage(){
    try{const body=messagePayload();body.name=`${body.name} copy`;const m=await api('/api/messages',{method:'POST',body});state.selectedMessage=m.id;await refreshContent();selectMessage(m.id);toast('Message duplicated');}catch(e){toast(e.message,true);}
  }
  async function deleteMessage(){const id=$('messageId').value;if(!id)return;if(!confirm('Delete this saved message?'))return;try{await api(`/api/messages/${id}`,{method:'DELETE'});state.selectedMessage=null;$('messageId').value='';await refreshContent();showMessageLibrary();toast('Message deleted');}catch(e){toast(e.message,true);}}
  function scheduleEditorPreview(){clearTimeout(state.editorTimer);state.editorTimer=setTimeout(()=>updateEditorPreview(),120);}
  function sceneHasLiveWidget(){return !!state.scene?.layers?.some(l=>l.enabled!==false&&l.type==='widget');}
  function sceneHasShader(){return !!((state.scene?.background?.mode==='shader'&&state.scene?.background?.shader_id)||state.scene?.layers?.some(l=>l.enabled!==false&&l.type==='shader'&&l.shader_id));}
  function messagesTabVisible(){return document.querySelector('.tab.active')?.dataset.tab==='messages'&&$('messagesWorkspace')?.classList.contains('messages-editor-view')&&!document.hidden;}
  function previewElapsed(){if($('msgEditorMode').value!=='designer')return 1.25;if($('designerAnimatePreview').checked){const d=sceneDuration();return d>0?((performance.now()-state.previewStarted)/1000)%d:0;}return +$('designerPreviewTime').value||0;}
  async function updateEditorPreview(){
    if(state.previewBusy)return;state.previewBusy=true;
    try{const msg=messagePayload(),elapsed=previewElapsed();const r=await fetch(`/api/render-preview?scale=6&elapsed=${encodeURIComponent(elapsed.toFixed(3))}`,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':state.auth?.csrf_token||''},body:JSON.stringify(msg)});if(!r.ok)throw new Error('Preview failed');const blob=await r.blob();const im=$('editorPreview'),old=im.src;im.onload=()=>{updateSelectionOverlay();refreshPreviewSimulation();if(old.startsWith('blob:'))setTimeout(()=>URL.revokeObjectURL(old),500);};im.src=URL.createObjectURL(blob);if(sceneHasShader())setTimeout(()=>{refreshShaderRenderStatus();refreshSceneShaderRenderStatus();},40);}catch(_){}finally{state.previewBusy=false;}
  }

  function shaderStatusText(status){
    const error=status?.preview_error||status?.live_error||'';if(error)return {text:`Shader error: ${error}`,error:true};
    const st=(status?.preview_stats&&Object.keys(status.preview_stats).length?status.preview_stats:status?.live_stats)||{};
    const scale=Number(st.render_scale||1),ms=Number(st.render_ms||0);if(scale<.999)return {text:`Adaptive shader performance: ${scale===.5?'½':scale===.25?'¼':Math.round(scale*100)+'%'} resolution${ms?` · ${ms.toFixed(0)} ms/frame`:''}`,error:false};
    return {text:'',error:false};
  }
  async function refreshShaderRenderStatus(){
    const box=$('shaderRenderStatus'),l=selectedLayer();if(!box)return;
    if(!l||l.type!=='shader'||!l.shader_id){box.classList.add('hidden');box.textContent='';return;}
    try{const result=shaderStatusText(await api(`/api/shaders/status/${encodeURIComponent(l.id)}`));box.textContent=result.text;box.classList.toggle('performance',!!result.text&&!result.error);box.classList.toggle('hidden',!result.text);}catch(_){box.classList.add('hidden');}
  }
  async function refreshSceneShaderRenderStatus(){
    const box=$('sceneBgShaderStatus'),bg=state.scene?.background;if(!box)return;
    if(!bg||bg.mode!=='shader'||!bg.shader_id){box.classList.add('hidden');box.textContent='';return;}
    try{const result=shaderStatusText(await api('/api/shaders/status/__background__'));box.textContent=result.text;box.classList.toggle('performance',!!result.text&&!result.error);box.classList.toggle('hidden',!result.text);}catch(_){box.classList.add('hidden');}
  }

  function populateFonts(){
    for(const id of ['msgFont','layerFont','widgetFont']){const el=$(id);if(!el)continue;const current=el.value;el.innerHTML=option('','Default font')+state.fonts.map(f=>option(f.path,f.name)).join('');if([...el.options].some(o=>o.value===current))el.value=current;}
  }
  function populateAssets(){
    for(const [id,empty] of [['msgImage','No graphic'],['layerImage','Choose an image']]){const el=$(id);if(!el)continue;const current=el.value;el.innerHTML=option('',empty)+state.assets.map(a=>option(a.path,a.name+(a.animated?` · ${a.frames} frames`:''))).join('');if([...el.options].some(o=>o.value===current))el.value=current;}
  }
  function populateVideos(){
    const el=$('layerVideo');if(!el)return;const current=el.value;el.innerHTML=option('','Choose a video')+state.videos.map(v=>option(v.path,`${v.name} · ${Number(v.duration||0).toFixed(1)}s · ${v.frames||0} frames`)).join('');if([...el.options].some(o=>o.value===current))el.value=current;
  }
  function populateShaders(){
    const built=(state.shaders||[]).filter(x=>x.origin==='built-in'),uploaded=(state.shaders||[]).filter(x=>x.origin!=='built-in');let html=option('','Choose a shader');if(built.length)html+=`<optgroup label="Built-in">${built.map(x=>option(x.id,x.name)).join('')}</optgroup>`;if(uploaded.length)html+=`<optgroup label="Uploaded">${uploaded.map(x=>option(x.id,x.name)).join('')}</optgroup>`;
    for(const id of ['layerShader','sceneBgShader']){const el=$(id);if(!el)continue;const current=el.value;el.innerHTML=html;if([...el.options].some(o=>o.value===current))el.value=current;}
  }
  function shaderAsset(id){return (state.shaders||[]).find(x=>x.id===id)||null;}
  function syncShaderWeatherFields(target,prefix){
    const sky=target?.shader_id==='builtin:Sky-Weather.fs',box=$(prefix==='layer'?'shaderWeatherFields':'sceneBgShaderWeatherFields');if(!box)return;box.classList.toggle('hidden',!sky);if(!sky)return;
    $(prefix==='layer'?'layerShaderLiveWeather':'sceneBgShaderLiveWeather').checked=!!target.shader_live_weather;
    $(prefix==='layer'?'layerShaderWeatherLat':'sceneBgShaderWeatherLat').value=target.shader_weather_lat??53.55;
    $(prefix==='layer'?'layerShaderWeatherLon':'sceneBgShaderWeatherLon').value=target.shader_weather_lon??-2.52;
    $(prefix==='layer'?'layerShaderWeatherRefresh':'sceneBgShaderWeatherRefresh').value=target.shader_weather_refresh??600;
  }
  function rgbArrayToHex(v){if(!Array.isArray(v))return '#ffffff';const a=[0,1,2].map(i=>clamp(Math.round((+v[i]||0)*255),0,255).toString(16).padStart(2,'0'));return '#'+a.join('');}
  function hexToRgbArray(v){const h=normaliseHex(v,'#ffffff').slice(1);return [parseInt(h.slice(0,2),16)/255,parseInt(h.slice(2,4),16)/255,parseInt(h.slice(4,6),16)/255,1];}
  function renderShaderParameterFields(layer=selectedLayer()){
    const box=$('shaderParameterFields'),info=$('shaderAssetInfo');if(!box||!layer||layer.type!=='shader')return;syncShaderWeatherFields(layer,'layer');const asset=shaderAsset(layer.shader_id);if(!asset){box.innerHTML='';info.textContent='Choose a shader to expose its controls.';return;}
    const meta=[asset.origin==='built-in'?'Built-in':'Uploaded',asset.credit?`Credit: ${asset.credit}`:'',...(asset.categories||[])].filter(Boolean).join(' · ');info.innerHTML=`<strong>${esc(asset.name)}</strong>${asset.description?` — ${esc(asset.description)}`:''}<br><small>${esc(meta)}</small>`;layer.shader_params=layer.shader_params&&typeof layer.shader_params==='object'?layer.shader_params:{};syncShaderWeatherFields(layer,'layer');const defs=shaderDefaults(asset);
    box.innerHTML=(asset.inputs||[]).map((item,idx)=>{const name=item.name,type=String(item.type||'float').toLowerCase(),value=layer.shader_params[name]??defs[name],label=esc(item.label||name),min=item.min,max=item.max;if(Array.isArray(item.values)&&item.values.length){return `<div class="shader-param"><span>${label}</span><select data-shader-param="${esc(name)}" data-shader-type="select">${item.values.map((v,i)=>option(String(v),String(item.labels?.[i]??v),String(value)===String(v))).join('')}</select></div>`;}if(type==='bool'||type==='event')return `<div class="shader-param"><label class="checkline"><input type="checkbox" data-shader-param="${esc(name)}" data-shader-type="bool" ${value?'checked':''}> ${label}</label></div>`;if(type==='color'){const id=`shaderParamColor${idx}`;return `<div class="shader-param"><span>${label}</span><input type="color" id="${id}" data-shader-param="${esc(name)}" data-shader-type="color" value="${rgbArrayToHex(value)}"></div>`;}if(type==='point2d'){const v=Array.isArray(value)?value:[0,0];return `<div class="shader-param"><span>${label}</span><div class="shader-point"><label>X<input type="number" step="0.01" ${min!==undefined?`min="${esc(Array.isArray(min)?min[0]:min)}"`:''} ${max!==undefined?`max="${esc(Array.isArray(max)?max[0]:max)}"`:''} data-shader-param="${esc(name)}" data-shader-axis="0" value="${esc(v[0]??0)}"></label><label>Y<input type="number" step="0.01" ${min!==undefined?`min="${esc(Array.isArray(min)?min[1]:min)}"`:''} ${max!==undefined?`max="${esc(Array.isArray(max)?max[1]:max)}"`:''} data-shader-param="${esc(name)}" data-shader-axis="1" value="${esc(v[1]??0)}"></label></div></div>`;}const step=type==='long'||type==='int'?'1':(min!==undefined&&max!==undefined?String(Math.max(.001,(+max-(+min))/100)):'0.01');return `<div class="shader-param"><span>${label}</span><input type="number" data-shader-param="${esc(name)}" data-shader-type="${type}" value="${esc(value??0)}" step="${esc(step)}" ${min!==undefined?`min="${esc(min)}"`:''} ${max!==undefined?`max="${esc(max)}"`:''}><small>${min!==undefined||max!==undefined?`${min!==undefined?esc(min):'…'} – ${max!==undefined?esc(max):'…'}`:''}</small></div>`;}).join('')||'<div class="muted">This shader has no exposed parameters.</div>';
    $$('[data-shader-param]').forEach(el=>el.addEventListener('input',updateShaderParamsFromUI));enhanceColourPickers();syncAllColourPickers();
  }
  function updateShaderParamsFromUI(){const l=selectedLayer();if(!l||l.type!=='shader')return;beginHistoryBurst();l.shader_params=l.shader_params&&typeof l.shader_params==='object'?l.shader_params:{};const points={};$$('#shaderParameterFields [data-shader-param]').forEach(el=>{const name=el.dataset.shaderParam,type=el.dataset.shaderType,axis=el.dataset.shaderAxis;if(axis!==undefined){points[name]=points[name]||Array.isArray(l.shader_params[name])?[...l.shader_params[name]]:[0,0];points[name][+axis]=+el.value||0;}else if(type==='bool')l.shader_params[name]=el.checked;else if(type==='color')l.shader_params[name]=hexToRgbArray(el.value);else if(type==='long'||type==='int')l.shader_params[name]=Math.round(+el.value||0);else if(type==='select'){const asset=shaderAsset(l.shader_id),def=asset?.inputs?.find(x=>x.name===name),raw=el.value;if(def?.values?.some(v=>typeof v==='number'))l.shader_params[name]=+raw;else l.shader_params[name]=raw;}else l.shader_params[name]=+el.value||0;});Object.entries(points).forEach(([k,v])=>l.shader_params[k]=v);scheduleEditorPreview();}
  function renderBackgroundShaderParameterFields(){
    const box=$('sceneBgShaderParameterFields'),info=$('sceneBgShaderAssetInfo'),bg=state.scene?.background;if(!box||!info||!bg)return;syncShaderWeatherFields(bg,'background');const asset=shaderAsset(bg.shader_id);if(bg.mode!=='shader'||!asset){box.innerHTML='';info.textContent='Choose a shader to expose its controls.';return;}
    const meta=[asset.origin==='built-in'?'Built-in':'Uploaded',asset.credit?`Credit: ${asset.credit}`:'',...(asset.categories||[])].filter(Boolean).join(' · ');info.innerHTML=`<strong>${esc(asset.name)}</strong>${asset.description?` — ${esc(asset.description)}`:''}<br><small>${esc(meta)}</small>`;bg.shader_params=bg.shader_params&&typeof bg.shader_params==='object'?bg.shader_params:{};syncShaderWeatherFields(bg,'background');const defs=shaderDefaults(asset);
    box.innerHTML=(asset.inputs||[]).map((item,idx)=>{const name=item.name,type=String(item.type||'float').toLowerCase(),value=bg.shader_params[name]??defs[name],label=esc(item.label||name),min=item.min,max=item.max;if(Array.isArray(item.values)&&item.values.length){return `<div class="shader-param"><span>${label}</span><select data-bg-shader-param="${esc(name)}" data-bg-shader-type="select">${item.values.map((v,i)=>option(String(v),String(item.labels?.[i]??v),String(value)===String(v))).join('')}</select></div>`;}if(type==='bool'||type==='event')return `<div class="shader-param"><label class="checkline"><input type="checkbox" data-bg-shader-param="${esc(name)}" data-bg-shader-type="bool" ${value?'checked':''}> ${label}</label></div>`;if(type==='color'){const id=`sceneBgShaderParamColor${idx}`;return `<div class="shader-param"><span>${label}</span><input type="color" id="${id}" data-bg-shader-param="${esc(name)}" data-bg-shader-type="color" value="${rgbArrayToHex(value)}"></div>`;}if(type==='point2d'){const v=Array.isArray(value)?value:[0,0];return `<div class="shader-param"><span>${label}</span><div class="shader-point"><label>X<input type="number" step="0.01" ${min!==undefined?`min="${esc(Array.isArray(min)?min[0]:min)}"`:''} ${max!==undefined?`max="${esc(Array.isArray(max)?max[0]:max)}"`:''} data-bg-shader-param="${esc(name)}" data-bg-shader-axis="0" value="${esc(v[0]??0)}"></label><label>Y<input type="number" step="0.01" ${min!==undefined?`min="${esc(Array.isArray(min)?min[1]:min)}"`:''} ${max!==undefined?`max="${esc(Array.isArray(max)?max[1]:max)}"`:''} data-bg-shader-param="${esc(name)}" data-bg-shader-axis="1" value="${esc(v[1]??0)}"></label></div></div>`;}const step=type==='long'||type==='int'?'1':(min!==undefined&&max!==undefined?String(Math.max(.001,(+max-(+min))/100)):'0.01');return `<div class="shader-param"><span>${label}</span><input type="number" data-bg-shader-param="${esc(name)}" data-bg-shader-type="${type}" value="${esc(value??0)}" step="${esc(step)}" ${min!==undefined?`min="${esc(min)}"`:''} ${max!==undefined?`max="${esc(max)}"`:''}><small>${min!==undefined||max!==undefined?`${min!==undefined?esc(min):'…'} – ${max!==undefined?esc(max):'…'}`:''}</small></div>`;}).join('')||'<div class="muted">This shader has no exposed parameters.</div>';
    $$('[data-bg-shader-param]').forEach(el=>el.addEventListener('input',updateBackgroundShaderParamsFromUI));enhanceColourPickers();syncAllColourPickers();
  }
  function updateBackgroundShaderParamsFromUI(){const bg=state.scene?.background;if(!bg||bg.mode!=='shader')return;beginHistoryBurst();bg.shader_params=bg.shader_params&&typeof bg.shader_params==='object'?bg.shader_params:{};const points={};$$('#sceneBgShaderParameterFields [data-bg-shader-param]').forEach(el=>{const name=el.dataset.bgShaderParam,type=el.dataset.bgShaderType,axis=el.dataset.bgShaderAxis;if(axis!==undefined){points[name]=points[name]||Array.isArray(bg.shader_params[name])?[...bg.shader_params[name]]:[0,0];points[name][+axis]=+el.value||0;}else if(type==='bool')bg.shader_params[name]=el.checked;else if(type==='color')bg.shader_params[name]=hexToRgbArray(el.value);else if(type==='long'||type==='int')bg.shader_params[name]=Math.round(+el.value||0);else if(type==='select'){const asset=shaderAsset(bg.shader_id),def=asset?.inputs?.find(x=>x.name===name),raw=el.value;if(def?.values?.some(v=>typeof v==='number'))bg.shader_params[name]=+raw;else bg.shader_params[name]=raw;}else bg.shader_params[name]=+el.value||0;});Object.entries(points).forEach(([k,v])=>bg.shader_params[k]=v);scheduleEditorPreview();}

  async function uploadBackgroundShader(input){
    const file=input.files[0];if(!file||!state.scene)return;const fd=new FormData();fd.append('file',file);
    try{const uploaded=await api('/api/upload/shader',{method:'POST',body:fd});state.shaders=await api('/api/shaders');populateShaders();const bg=state.scene.background||(state.scene.background={});recordHistory();bg.mode='shader';bg.shader_id=uploaded.id;bg.shader_params=shaderDefaults(shaderAsset(uploaded.id));bg.shader_fps=bg.shader_fps||15;bg.shader_time_scale=bg.shader_time_scale??1;bg.shader_quality=bg.shader_quality||'auto';input.value='';syncSceneBackgroundControls();scheduleEditorPreview();toast('Shader uploaded and set as background');}catch(e){input.value='';toast(e.message,true);}
  }

  function setVideoUploadProgress(stage, percent=null, detail='', opts={}){
    const box=$('videoUploadProgress'),bar=$('videoUploadBar'),stageEl=$('videoUploadStage'),pctEl=$('videoUploadPercent'),detailEl=$('videoUploadDetail');
    if(!box||!bar)return;
    box.classList.toggle('hidden',opts.hidden===true);
    box.classList.toggle('error',opts.error===true);
    box.classList.toggle('complete',opts.complete===true);
    box.classList.toggle('indeterminate',percent===null&&!opts.complete&&!opts.error);
    stageEl.textContent=stage||'';
    pctEl.textContent=percent===null?'':`${Math.round(percent)}%`;
    detailEl.textContent=detail||'';
    if(percent!==null)bar.style.width=`${clamp(+percent||0,0,100)}%`;else bar.style.width='35%';
    if($('designerVideoUpload'))$('designerVideoUpload').disabled=state.videoUploadBusy;
  }
  function xhrUploadJson(url,fd,onProgress){
    return new Promise((resolve,reject)=>{
      const xhr=new XMLHttpRequest();xhr.open('POST',url,true);xhr.responseType='json';if(state.auth?.csrf_token)xhr.setRequestHeader('X-CSRF-Token',state.auth.csrf_token);
      xhr.upload.onprogress=(ev)=>{if(ev.lengthComputable&&onProgress)onProgress((ev.loaded/ev.total)*100,ev.loaded,ev.total);};
      xhr.onerror=()=>reject(new Error('Upload failed: network error'));
      xhr.onabort=()=>reject(new Error('Upload cancelled'));
      xhr.onload=()=>{
        let data=xhr.response;
        if(typeof data==='string'){try{data=JSON.parse(data);}catch(_){data=null;}}
        if(xhr.status<200||xhr.status>=300)return reject(new Error(data?.error||`${xhr.status} ${xhr.statusText}`));
        resolve(data||{});
      };
      xhr.send(fd);
    });
  }
  async function waitForVideoJob(jobId){
    for(;;){
      const job=await api(`/api/upload/video/status/${encodeURIComponent(jobId)}`);
      if(job.state==='failed')throw new Error(job.error||job.message||'Video processing failed');
      if(job.state==='complete')return job.result;
      const stage=job.state==='queued'?'Queued':job.state==='finalising'?'Finalising video':'Creating LED frames';
      setVideoUploadProgress(stage,Number.isFinite(+job.progress)?+job.progress:null,job.message||'The physical LED display continues normally while this is processed.');
      await new Promise(r=>setTimeout(r,450));
    }
  }
  async function uploadVideo(input){
    const file=input.files[0];if(!file||state.videoUploadBusy)return;
    state.videoUploadBusy=true;
    const fd=new FormData();fd.append('file',file);fd.append('fps','12');fd.append('max_seconds','300');
    const mb=(file.size/1024/1024).toFixed(file.size>=10*1024*1024?1:2);
    setVideoUploadProgress('Uploading',0,`${file.name} · ${mb} MB`);
    try{
      const started=await xhrUploadJson('/api/upload/video/start',fd,(pct,loaded,total)=>{
        const done=(loaded/1024/1024).toFixed(1),all=(total/1024/1024).toFixed(1);
        setVideoUploadProgress('Uploading',pct,`${file.name} · ${done} / ${all} MB`);
      });
      setVideoUploadProgress('Processing video',null,'Upload complete. Preparing the video for the LED canvas…');
      const uploaded=await waitForVideoJob(started.job_id);
      state.videos=await api('/api/videos');populateVideos();
      let layer=selectedLayer();if(!layer||layer.type!=='video'){layer=defaultVideoLayer();state.scene.layers.push(layer);setSelection([layer.id],layer.id);}layer.video_path=uploaded.path;renderLayerList();loadSelectedLayerControls();
      input.value='';scheduleEditorPreview();
      setVideoUploadProgress('Complete',100,`${uploaded.frames||0} LED frames · ${Number(uploaded.duration||0).toFixed(1)}s`,{complete:true});
      toast('Video processed and added');
      setTimeout(()=>{if(!state.videoUploadBusy)setVideoUploadProgress('',0,'',{hidden:true});},5000);
    }catch(e){
      input.value='';setVideoUploadProgress('Upload failed',100,e.message,{error:true});toast(e.message,true);
    }finally{
      state.videoUploadBusy=false;if($('designerVideoUpload'))$('designerVideoUpload').disabled=false;
    }
  }
  async function upload(kind,input){
    if(kind==='video')return uploadVideo(input);
    const file=input.files[0];if(!file)return;const fd=new FormData();fd.append('file',file);
    try{
      const uploaded=await api(`/api/upload/${kind}`,{method:'POST',body:fd});
      if(kind==='image'){state.assets=await api('/api/assets');populateAssets();}
      else if(kind==='shader'){state.shaders=await api('/api/shaders');populateShaders();}
      else {state.fonts=await api('/api/fonts');populateFonts();}
      if(kind==='image'){
        if($('msgEditorMode').value==='designer'){
          let layer=selectedLayer();if(!layer||layer.type!=='image'){layer=defaultImageLayer();state.scene.layers.push(layer);setSelection([layer.id],layer.id);}layer.image_path=uploaded.path;renderLayerList();loadSelectedLayerControls();
        }else{$('msgImage').value=uploaded.path;$('msgImageMode').value=$('msgText').value?'logo-left':'logo-center';}
      } else if(kind==='shader'){
        let layer=selectedLayer();if(!layer||layer.type!=='shader'){layer=defaultShaderLayer();state.scene.layers.push(layer);setSelection([layer.id],layer.id);}layer.shader_id=uploaded.id;layer.shader_params=shaderDefaults(shaderAsset(uploaded.id));renderLayerList();loadSelectedLayerControls();
      } else {
        if($('msgEditorMode').value==='designer'&&['text','widget'].includes(selectedLayer()?.type)){selectedLayer().font=uploaded.path;loadSelectedLayerControls();}else $('msgFont').value=uploaded.path;
      }
      input.value='';scheduleEditorPreview();toast(`${kind==='image'?'Image':kind==='shader'?'Shader':'Font'} uploaded`);
    }catch(e){input.value='';toast(e.message,true);}
  }

  // Designer layers
  function selectedLayer(){return state.scene?.layers?.find(l=>l.id===state.selectedLayerId)||null;}
  function layerLabel(l){
    if(l.type==='text')return l.text||l.name;
    if(l.type==='widget')return `${l.widget_type||'widget'} · ${l.widget_format||l.weather_template||l.data_url||''}`;
    if(l.type==='image')return state.assets.find(a=>a.path===l.image_path)?.name||l.name;
    if(l.type==='video')return state.videos.find(v=>v.path===l.video_path)?.name||l.name;
    if(l.type==='shader')return shaderAsset(l.shader_id)?.name||l.name;
    if(l.type==='icon')return `${l.icon_name||'icon'}${l.icon_effect&&l.icon_effect!=='none'?` · ${l.icon_effect}`:''}`;
    return l.name;
  }
  function layerIcon(l){return ({text:'T',image:'I',video:'▶',shader:'✦',widget:'W',icon:'◆',shape:'S'})[l.type]||'?';}
  function renderLayerList(){
    if(!state.scene)return;
    const selected=new Set(state.selectedLayerIds||[]);if(state.selectedLayerId)selected.add(state.selectedLayerId);
    $('designerLayerList').innerHTML=state.scene.layers.length?[...state.scene.layers].sort((a,b)=>(+b.z||0)-(+a.z||0)).map(l=>`<div class="designer-layer-item ${selected.has(l.id)?'active':''}" data-layer-id="${esc(l.id)}"><span class="designer-layer-icon">${esc(layerIcon(l))}</span><div><strong>${esc(l.name||l.type)}${l.group_id?' <span class="group-badge">G</span>':''}</strong><small>${esc(layerLabel(l)||'')}${l.zone_id?` · zone: ${esc(state.scene.zones.find(z=>z.id===l.zone_id)?.name||'')}`:''}</small></div><input class="visibility" type="checkbox" title="Visible" data-layer-visible="${esc(l.id)}" ${l.enabled!==false?'checked':''}></div>`).join(''):'<div class="muted">No layers. Add text, image, video, shader, widget, icon or shape.</div>';
    $$('#designerLayerList [data-layer-id]').forEach(el=>el.addEventListener('click',ev=>{
      if(ev.target.matches('[data-layer-visible]'))return;const id=el.dataset.layerId,l=state.scene.layers.find(x=>x.id===id);let ids=[...(state.selectedLayerIds||[])];
      if(ev.shiftKey||ev.metaKey||ev.ctrlKey){ids=ids.includes(id)?ids.filter(x=>x!==id):[...ids,id];setSelection(ids,id);}
      else if(l?.group_id){setSelection(state.scene.layers.filter(x=>x.group_id===l.group_id).map(x=>x.id),id);}
      else setSelection([id],id);
      renderLayerList();loadSelectedLayerControls();scheduleEditorPreview();
    }));
    $$('[data-layer-visible]').forEach(el=>el.addEventListener('change',()=>{const l=state.scene.layers.find(x=>x.id===el.dataset.layerVisible);if(l){recordHistory();l.enabled=el.checked;}renderTimeline();scheduleEditorPreview();}));
    renderZones();renderTimeline();updateSelectionOverlay();updateHistoryButtons();
  }

  function renderZones(){
    if(!state.scene||!$('designerZoneList'))return;
    const zones=state.scene.zones||[];
    $('designerZoneList').innerHTML=zones.length?zones.map(z=>`<div class="zone-item ${z.id===state.selectedZoneId?'active':''}" data-zone-id="${esc(z.id)}"><div><input class="zone-name" data-zone-name="${esc(z.id)}" value="${esc(z.name||'Zone')}"></div><div class="zone-geometry"><label>X<input type="number" data-zone-field="x" data-zone-ref="${esc(z.id)}" value="${Math.round(+z.x||0)}"></label><label>Y<input type="number" data-zone-field="y" data-zone-ref="${esc(z.id)}" value="${Math.round(+z.y||0)}"></label><label>W<input type="number" min="1" data-zone-field="w" data-zone-ref="${esc(z.id)}" value="${Math.max(1,Math.round(+z.w||1))}"></label><label>H<input type="number" min="1" data-zone-field="h" data-zone-ref="${esc(z.id)}" value="${Math.max(1,Math.round(+z.h||1))}"></label></div></div>`).join(''):'<div class="muted">No zones yet.</div>';
    $$('[data-zone-id]').forEach(el=>el.addEventListener('click',ev=>{if(ev.target.matches('input'))return;state.selectedZoneId=el.dataset.zoneId;renderZones();updateSelectionOverlay();}));
    $$('[data-zone-name]').forEach(el=>el.addEventListener('input',()=>{beginHistoryBurst();const z=zones.find(x=>x.id===el.dataset.zoneName);if(z)z.name=el.value||'Zone';populateLayerZoneSelect();scheduleEditorPreview();}));
    $$('[data-zone-field]').forEach(el=>el.addEventListener('input',()=>{beginHistoryBurst();const z=zones.find(x=>x.id===el.dataset.zoneRef);if(!z)return;const f=el.dataset.zoneField;z[f]=f==='w'||f==='h'?Math.max(1,+el.value||1):(+el.value||0);renderZoneOverlays();scheduleEditorPreview();}));
    populateLayerZoneSelect();renderZoneOverlays();
  }
  function populateLayerZoneSelect(){const el=$('layerZone');if(!el||!state.scene)return;const current=selectedLayer()?.zone_id||'';el.innerHTML=option('','No zone')+(state.scene.zones||[]).map(z=>option(z.id,z.name||'Zone')).join('');el.value=(state.scene.zones||[]).some(z=>z.id===current)?current:'';}
  function addZone(){if(!state.scene)return;recordHistory();const {w,h}=logicalSize(),n=(state.scene.zones||[]).length+1;const z={id:`Z${uid().slice(1)}`,name:`Zone ${n}`,x:0,y:0,w:Math.max(1,Math.round(w/2)),h,color:'#4aa3ff'};state.scene.zones.push(z);state.selectedZoneId=z.id;renderZones();scheduleEditorPreview();}
  function deleteZone(){if(!state.scene||!state.selectedZoneId)return;const z=state.scene.zones.find(x=>x.id===state.selectedZoneId);if(!z)return;if(!confirm(`Delete ${z.name||'this zone'}? Layers will remain but will no longer be clipped to it.`))return;recordHistory();state.scene.layers.forEach(l=>{if(l.zone_id===z.id)l.zone_id='';});state.scene.zones=state.scene.zones.filter(x=>x.id!==z.id);state.selectedZoneId=null;renderLayerList();loadSelectedLayerControls();scheduleEditorPreview();}
  function assignSelectionToZone(){const ls=selectionLayers();if(!ls.length){toast('Select one or more layers first',true);return;}if(!state.selectedZoneId){toast('Select a zone first',true);return;}recordHistory();ls.forEach(l=>l.zone_id=state.selectedZoneId);renderLayerList();loadSelectedLayerControls();scheduleEditorPreview();}
  function clearSelectionZone(){const ls=selectionLayers();if(!ls.length)return;recordHistory();ls.forEach(l=>l.zone_id='');renderLayerList();loadSelectedLayerControls();scheduleEditorPreview();}
  function renderZoneOverlays(){const wrap=$('zoneOverlays'),img=$('editorPreview');if(!wrap||!state.scene||!img.complete||!img.naturalWidth){if(wrap)wrap.innerHTML='';return;}const stage=$('designerStage').getBoundingClientRect(),r=img.getBoundingClientRect(),dw=state.scene.design_width||logicalSize().w,dh=state.scene.design_height||logicalSize().h;wrap.innerHTML=(state.scene.zones||[]).map(z=>`<div class="zone-overlay ${z.id===state.selectedZoneId?'active':''}" style="left:${r.left-stage.left+(+z.x||0)/dw*r.width}px;top:${r.top-stage.top+(+z.y||0)/dh*r.height}px;width:${Math.max(2,(+z.w||1)/dw*r.width)}px;height:${Math.max(2,(+z.h||1)/dh*r.height)}px"><span>${esc(z.name||'Zone')}</span></div>`).join('');}

  function syncSceneBackgroundControls(){
    if(!state.scene)return;const bg=state.scene.background||{};const mode=bg.mode||'solid';$('sceneBgMode').value=mode;$('sceneBgColor1').value=bg.color1||'#000000';$('sceneBgColor2').value=bg.color2||bg.color1||'#000000';
    const shaderMode=mode==='shader';$('sceneBgShaderFields').classList.toggle('hidden',!shaderMode);$('sceneBgColor2Wrap').classList.toggle('hidden',shaderMode||mode==='solid');$('sceneBgColor1Label').textContent=shaderMode?'Fallback colour':'Colour 1';
    populateShaders();if($('sceneBgShader'))$('sceneBgShader').value=bg.shader_id||'';if($('sceneBgShaderFps'))$('sceneBgShaderFps').value=String(bg.shader_fps||15);if($('sceneBgShaderTimeScale'))$('sceneBgShaderTimeScale').value=bg.shader_time_scale??1;if($('sceneBgShaderQuality'))$('sceneBgShaderQuality').value=bg.shader_quality||'auto';syncShaderWeatherFields(bg,'background');
    if(shaderMode)renderBackgroundShaderParameterFields();else{$('sceneBgShaderParameterFields').innerHTML='';$('sceneBgShaderStatus').classList.add('hidden');}
    $('sceneDuration').value=state.scene.duration||10;$('sceneTransitionIn').value=state.scene.transition_in||'none';$('sceneTransitionInDuration').value=state.scene.transition_in_duration??.5;$('sceneTransitionOut').value=state.scene.transition_out||'none';$('sceneTransitionOutDuration').value=state.scene.transition_out_duration??.5;
    syncAllColourPickers();updatePreviewTimelineRange();renderTimeline();
  }
  function sceneDuration(){return clamp(Number(state.scene?.duration)||10,.25,3600);}
  function layerEndTime(l){const duration=sceneDuration(),delay=Math.max(0,+l.delay||0),after=Math.max(0,+l.exit_after||0),ed=Math.max(.05,+l.exit_duration||.5);return after>0?Math.min(duration,delay+after+ed):duration;}
  function updatePreviewTimelineRange(){
    if(!state.scene)return;let maxTime=sceneDuration();for(const l of state.scene.layers||[])maxTime=Math.max(maxTime,layerEndTime(l));maxTime=Math.min(3600,Math.max(.25,maxTime));
    const slider=$('designerPreviewTime');slider.max=String(maxTime);if(+slider.value>maxTime)slider.value=String(maxTime);$('designerPreviewTimeValue').textContent=`${Number(slider.value).toFixed(2)}s`;renderTimeline();
  }
  function renderTimeline(){
    if(!state.scene||!$('timelineLanes'))return;const duration=sceneDuration(),elapsed=clamp(previewElapsed(),0,duration);$('timelineTime').textContent=`${elapsed.toFixed(2)}s / ${duration.toFixed(2)}s`;
    const ticks=[];const divisions=duration<=10?10:duration<=30?6:duration<=120?8:10;for(let i=0;i<=divisions;i++){const t=duration*i/divisions;ticks.push(`<span style="left:${(i/divisions)*100}%">${t<10?t.toFixed(1):Math.round(t)}s</span>`);}$('timelineRuler').innerHTML=ticks.join('');
    const layers=[...state.scene.layers].sort((a,b)=>(+b.z||0)-(+a.z||0));
    const tin=Math.min(duration,Math.max(0,+state.scene.transition_in_duration||0)),tout=Math.min(duration,Math.max(0,+state.scene.transition_out_duration||0));
    const sceneLane=`<div class="timeline-lane scene-lane"><div class="timeline-label">SCENE</div><div class="timeline-track"><div class="timeline-playhead" style="left:${elapsed/duration*100}%"></div>${state.scene.transition_in&&state.scene.transition_in!=='none'?`<div class="scene-transition-bar scene-in" style="left:0;width:${tin/duration*100}%" title="Entrance: ${esc(state.scene.transition_in)} · ${tin.toFixed(2)}s">IN</div>`:''}${state.scene.transition_out&&state.scene.transition_out!=='none'?`<div class="scene-transition-bar scene-out" style="right:0;width:${tout/duration*100}%" title="Exit: ${esc(state.scene.transition_out)} · ${tout.toFixed(2)}s">OUT</div>`:''}</div></div>`;
    $('timelineLanes').innerHTML=sceneLane+(layers.length?layers.map(l=>{const start=clamp(+l.delay||0,0,duration),end=clamp(layerEndTime(l),start,duration),left=start/duration*100,width=Math.max(.5,(end-start)/duration*100),exit=+l.exit_after>0;return `<div class="timeline-lane ${(state.selectedLayerIds||[]).includes(l.id)||l.id===state.selectedLayerId?'active':''}" data-timeline-lane="${esc(l.id)}"><button class="timeline-label" data-timeline-select="${esc(l.id)}">${esc(layerIcon(l))} ${esc(l.name||l.type)}</button><div class="timeline-track"><div class="timeline-playhead" style="left:${elapsed/duration*100}%"></div><div class="timeline-bar ${l.enabled===false?'disabled':''}" data-timeline-bar="${esc(l.id)}" style="left:${left}%;width:${width}%" title="${start.toFixed(2)}s → ${end.toFixed(2)}s"><span class="timeline-in"></span>${exit?'<span class="timeline-out"></span>':''}<span class="timeline-resize" data-timeline-resize="${esc(l.id)}"></span></div></div></div>`;}).join(''):'<div class="muted timeline-empty">No layers yet.</div>');
    $$('[data-timeline-select]').forEach(b=>b.addEventListener('click',ev=>{const id=b.dataset.timelineSelect,l=state.scene.layers.find(x=>x.id===id);if(ev.shiftKey||ev.metaKey||ev.ctrlKey){let ids=[...(state.selectedLayerIds||[])];ids=ids.includes(id)?ids.filter(x=>x!==id):[...ids,id];setSelection(ids,id);}else if(l?.group_id)setSelection(state.scene.layers.filter(x=>x.group_id===l.group_id).map(x=>x.id),id);else setSelection([id],id);renderLayerList();loadSelectedLayerControls();}));
    $$('.timeline-track').forEach(track=>track.addEventListener('pointerdown',ev=>{if(ev.target.closest('.timeline-bar'))return;const rect=track.getBoundingClientRect(),t=clamp((ev.clientX-rect.left)/rect.width*duration,0,duration);$('designerAnimatePreview').checked=false;$('designerPreviewTime').value=t;$('designerPreviewTimeValue').textContent=`${t.toFixed(2)}s`;renderTimeline();scheduleEditorPreview();}));
    $$('[data-timeline-bar]').forEach(bar=>bar.addEventListener('pointerdown',ev=>beginTimelineDrag(ev,bar.dataset.timelineBar,'move')));
    $$('[data-timeline-resize]').forEach(handle=>handle.addEventListener('pointerdown',ev=>{ev.stopPropagation();beginTimelineDrag(ev,handle.dataset.timelineResize,'resize');}));
  }
  function beginTimelineDrag(ev,id,mode){
    const l=state.scene.layers.find(x=>x.id===id);if(!l)return;ev.preventDefault();recordHistory();if(!(state.selectedLayerIds||[]).includes(id))setSelection(l.group_id?state.scene.layers.filter(x=>x.group_id===l.group_id).map(x=>x.id):[id],id);else state.selectedLayerId=id;const track=ev.currentTarget.closest('.timeline-track');const rect=track.getBoundingClientRect();state.timelineDrag={id,mode,startX:ev.clientX,width:rect.width,duration:sceneDuration(),delay:+l.delay||0,exitAfter:+l.exit_after||0,delays:new Map(selectionLayers().map(x=>[x.id,+x.delay||0]))};renderLayerList();loadSelectedLayerControls();
  }
  function moveTimelineDrag(ev){
    const d=state.timelineDrag;if(!d)return;const l=state.scene.layers.find(x=>x.id===d.id);if(!l)return;const dt=(ev.clientX-d.startX)/Math.max(1,d.width)*d.duration;
    if(d.mode==='move'){for(const sl of selectionLayers()){const base=d.delays?.get(sl.id)??(+sl.delay||0);sl.delay=clamp(base+dt,0,Math.max(0,d.duration-.05));}}
    else{const end=clamp((d.delay+(d.exitAfter>0?d.exitAfter:d.duration-d.delay))+dt,d.delay+.05,d.duration);l.exit_after=Math.max(.05,end-l.delay);if((l.exit_effect||'none')==='none')l.exit_effect='fade';}
    loadSelectedLayerControls();scheduleEditorPreview();
  }
  function endTimelineDrag(){if(state.timelineDrag){state.timelineDrag=null;renderTimeline();}}
  function updateWidgetFieldVisibility(){
    const kind=$('layerWidgetType').value,remote=['weather','json','rss'].includes(kind),analog=kind==='analog-clock',weather=kind==='weather';
    $('widgetAnalogFields').classList.toggle('hidden',!analog);$('widgetCountdownFields').classList.toggle('hidden',kind!=='countdown');$('widgetWeatherFields').classList.toggle('hidden',!weather);$('widgetDataFields').classList.toggle('hidden',!['json','rss'].includes(kind));$('layerJsonPath').closest('label').classList.toggle('hidden',kind!=='json');$('layerRssItem').closest('label').classList.toggle('hidden',kind!=='rss');
    $('layerWidgetFormat').closest('label').classList.toggle('hidden',!['clock','date'].includes(kind));$('layerWidgetRefresh').closest('label').classList.toggle('hidden',!remote);$('widgetTextStyle').classList.toggle('hidden',analog);
    if(weather){const textOnly=$('layerWeatherDisplay').value==='text';$('weatherAnimatedOptions').classList.toggle('hidden',textOnly);$('weatherTemplateOptions').classList.toggle('hidden',!textOnly);}
  }
  function loadSelectedLayerControls(){
    const l=selectedLayer();$('noLayerSelected').classList.toggle('hidden',!!l);$('layerProperties').classList.toggle('hidden',!l);if(!l){$('designerSelection').classList.add('hidden');renderTimeline();return;}
    $('layerName').value=l.name||'';$('layerType').value=l.type||'text';populateLayerZoneSelect();$('layerZone').value=l.zone_id||'';$('layerEnabled').checked=l.enabled!==false;$('layerX').value=Math.round(+l.x||0);$('layerY').value=Math.round(+l.y||0);$('layerW').value=Math.max(1,Math.round(+l.w||1));$('layerH').value=Math.max(1,Math.round(+l.h||1));$('layerOpacity').value=l.opacity??100;$('layerRotation').value=l.rotation||0;$('layerDelay').value=l.delay||0;$('layerAnimation').value=l.animation||'static';$('layerSpeed').value=l.speed??30;$('layerEffectPeriod').value=l.effect_period??1;$('layerBlinkDuty').value=Math.round((l.blink_duty??.5)*100);$('layerEntranceEffect').value=l.entrance_effect||'none';$('layerEntranceDuration').value=l.entrance_duration??.5;$('layerExitEffect').value=l.exit_effect||'none';$('layerExitAfter').value=l.exit_after??0;$('layerExitDuration').value=l.exit_duration??.5;$('layerTransitionProperties').classList.toggle('hidden',!['text','image','video','widget','icon','shader'].includes(l.type));
    $('textLayerProperties').classList.toggle('hidden',l.type!=='text');$('imageLayerProperties').classList.toggle('hidden',l.type!=='image');$('videoLayerProperties').classList.toggle('hidden',l.type!=='video');$('shaderLayerProperties').classList.toggle('hidden',l.type!=='shader');$('widgetLayerProperties').classList.toggle('hidden',l.type!=='widget');$('iconLayerProperties').classList.toggle('hidden',l.type!=='icon');$('shapeLayerProperties').classList.toggle('hidden',l.type!=='shape');
    if(l.type==='text'){
      $('layerText').value=l.text||'';$('layerFont').value=l.font||'';$('layerFontSize').value=l.font_size||18;$('layerRenderMode').value=l.render_mode||'pixel';$('layerPixelScale').value=l.pixel_scale||1;$('layerPixelBold').checked=!!l.pixel_bold;$('layerLetterSpacing').value=l.letter_spacing||0;$('layerAutoFit').checked=!!l.auto_fit;$('layerWrap').checked=!!l.wrap;$('layerOverflow').value=l.overflow||'manual';$('layerTextTransform').value=l.text_transform||'none';$('layerTypewriterSpeed').value=l.typewriter_speed??12;$('layerColorEffect').value=l.color_effect||'none';$('layerColor2').value=l.color2||'#ff00ff';$('layerColorSpeed').value=l.color_speed??1;$('layerColorPalette').value=l.color_palette||'';$('layerGlow').value=l.glow||0;$('layerGlowColor').value=l.glow_color||l.color||'#ffffff';$('layerTextColor').value=l.color||'#ffffff';$('layerOutlineColor').value=l.outline_color||'#000000';$('layerOutlineWidth').value=l.outline_width||0;$('layerPadding').value=l.padding||0;$('layerAlign').value=l.align||'center';$('layerVAlign').value=l.valign||'middle';$('layerLineSpacing').value=l.line_spacing??.12;$('layerShadowColor').value=l.shadow_color||'#000000';$('layerShadowX').value=l.shadow_x||0;$('layerShadowY').value=l.shadow_y||0;
    }
    if(l.type==='image'){$('layerImage').value=l.image_path||'';$('layerImageFit').value=l.fit||'contain';$('layerMediaSpeed').value=l.media_speed??1;$('layerMediaLoop').checked=l.media_loop!==false;}
    if(l.type==='video'){$('layerVideo').value=l.video_path||'';$('layerVideoFit').value=l.fit||'contain';$('layerVideoSpeed').value=l.media_speed??1;$('layerVideoLoop').checked=l.media_loop!==false;}
    if(l.type==='shader'){$('layerShader').value=l.shader_id||'';$('layerShaderFps').value=String(l.shader_fps||15);$('layerShaderTimeScale').value=l.shader_time_scale??1;$('layerShaderQuality').value=l.shader_quality||'auto';renderShaderParameterFields(l);}
    if(l.type==='widget'){
      $('layerWidgetType').value=l.widget_type||'clock';$('layerWidgetFormat').value=l.widget_format||'';$('layerWidgetRefresh').value=l.refresh_seconds??300;$('clockRingColor').value=l.clock_ring_color||'#ffffff';$('clockTickColor').value=l.clock_tick_color||'#ffffff';$('clockHourColor').value=l.clock_hour_color||'#ffffff';$('clockMinuteColor').value=l.clock_minute_color||'#ffffff';$('clockSecondColor').value=l.clock_second_color||'#ff3030';$('clockFaceColor').value=l.clock_face_color||'#000000';$('clockShowSeconds').checked=l.clock_show_seconds!==false;$('clockFillFace').checked=!!l.clock_fill_face;$('layerCountdownTarget').value=String(l.countdown_target||'').slice(0,16);$('layerCountdownFormat').value=l.countdown_format||'{D}d {HH}:{MM}:{SS}';$('layerWeatherLat').value=l.weather_lat??53.55;$('layerWeatherLon').value=l.weather_lon??-2.52;$('layerWeatherDisplay').value=l.weather_display||'text';$('layerWeatherTempUnit').value=l.weather_temp_unit||'c';$('layerWeatherWindUnit').value=l.weather_wind_unit||'mph';$('weatherShowIcon').checked=l.weather_show_icon!==false;$('weatherAnimateIcon').checked=l.weather_animate_icon!==false;$('weatherShowCondition').checked=l.weather_show_condition!==false;$('weatherShowFeels').checked=l.weather_show_feels!==false;$('weatherShowWind').checked=l.weather_show_wind!==false;$('weatherShowGusts').checked=!!l.weather_show_gusts;$('weatherShowHumidity').checked=!!l.weather_show_humidity;$('weatherShowPrecip').checked=!!l.weather_show_precip;$('weatherCycleDetails').checked=l.weather_cycle_details!==false;$('weatherDetailPeriod').value=l.weather_detail_period??2.5;$('layerWeatherTemplate').value=l.weather_template||'{TEMP}{TEMP_UNIT} {CONDITION}';$('layerDataUrl').value=l.data_url||'';$('layerJsonPath').value=l.json_path||'';$('layerRssItem').value=(+l.rss_item||0)+1;$('layerDataPrefix').value=l.widget_prefix||'';$('layerDataSuffix').value=l.widget_suffix||'';$('widgetFont').value=l.font||'';$('widgetFontSize').value=l.font_size||18;$('widgetRenderMode').value=l.render_mode||'pixel';$('widgetColor').value=l.color||'#ffffff';$('widgetAutoFit').checked=l.auto_fit!==false;$('widgetAlign').value=l.align||'center';$('widgetVAlign').value=l.valign||'middle';$('widgetPadding').value=l.padding??1;updateWidgetFieldVisibility();
    }
    if(l.type==='icon'){$('layerIconName').value=l.icon_name||'info';$('layerIconColor').value=l.icon_color||'#ffffff';$('layerIconColor2').value=l.icon_color2||'#31506a';$('layerIconEffect').value=l.icon_effect||'none';$('layerIconPeriod').value=l.icon_period??1;}
    if(l.type==='shape'){$('layerShape').value=l.shape||'rectangle';$('layerFill').value=l.fill||'#2255aa';$('layerBorderColor').value=l.border_color||'#ffffff';$('layerBorderWidth').value=l.border_width||0;$('layerRadius').value=l.radius||0;}
    syncAllColourPickers();updatePreviewTimelineRange();updateSelectionOverlay();
  }
  function updateSelectedFromControls(){
    const l=selectedLayer();if(!l)return;beginHistoryBurst();l.name=$('layerName').value.trim()||l.type;l.zone_id=$('layerZone').value||'';l.enabled=$('layerEnabled').checked;l.x=+$('layerX').value||0;l.y=+$('layerY').value||0;l.w=Math.max(1,+$('layerW').value||1);l.h=Math.max(1,+$('layerH').value||1);l.opacity=clamp(+$('layerOpacity').value||0,0,100);l.rotation=+$('layerRotation').value||0;l.delay=Math.max(0,+$('layerDelay').value||0);l.animation=$('layerAnimation').value;l.speed=Math.max(0,+$('layerSpeed').value||0);l.effect_period=Math.max(.1,+$('layerEffectPeriod').value||1);l.blink_duty=clamp((+$('layerBlinkDuty').value||50)/100,.05,.95);
    if(['text','image','video','widget','icon','shader'].includes(l.type)){l.entrance_effect=$('layerEntranceEffect').value;l.entrance_duration=Math.max(.05,+$('layerEntranceDuration').value||.5);l.exit_effect=$('layerExitEffect').value;l.exit_after=Math.max(0,+$('layerExitAfter').value||0);l.exit_duration=Math.max(.05,+$('layerExitDuration').value||.5);}
    if(l.type==='text'){l.text=$('layerText').value;l.font=$('layerFont').value;l.font_size=Math.max(4,+$('layerFontSize').value||18);l.render_mode=$('layerRenderMode').value;l.pixel_scale=Math.max(1,Math.min(8,+$('layerPixelScale').value||1));l.pixel_bold=$('layerPixelBold').checked;l.letter_spacing=Math.max(0,Math.min(8,+$('layerLetterSpacing').value||0));l.auto_fit=$('layerAutoFit').checked;l.wrap=$('layerWrap').checked;l.overflow=$('layerOverflow').value;l.text_transform=$('layerTextTransform').value;l.typewriter_speed=Math.max(.1,+$('layerTypewriterSpeed').value||12);l.color_effect=$('layerColorEffect').value;l.color2=$('layerColor2').value;l.color_speed=Math.max(.05,+$('layerColorSpeed').value||1);l.color_palette=$('layerColorPalette').value;l.glow=Math.max(0,+$('layerGlow').value||0);l.glow_color=$('layerGlowColor').value;l.color=$('layerTextColor').value;l.outline_color=$('layerOutlineColor').value;l.outline_width=Math.max(0,+$('layerOutlineWidth').value||0);l.padding=Math.max(0,+$('layerPadding').value||0);l.align=$('layerAlign').value;l.valign=$('layerVAlign').value;l.line_spacing=clamp(+$('layerLineSpacing').value||0,0,1);l.shadow_color=$('layerShadowColor').value;l.shadow_x=+$('layerShadowX').value||0;l.shadow_y=+$('layerShadowY').value||0;}
    if(l.type==='image'){l.image_path=$('layerImage').value;l.fit=$('layerImageFit').value;l.media_speed=Math.max(.05,+$('layerMediaSpeed').value||1);l.media_loop=$('layerMediaLoop').checked;}
    if(l.type==='video'){l.video_path=$('layerVideo').value;l.fit=$('layerVideoFit').value;l.media_speed=Math.max(.05,+$('layerVideoSpeed').value||1);l.media_loop=$('layerVideoLoop').checked;}
    if(l.type==='shader'){const next=$('layerShader').value;if(l.shader_id!==next){l.shader_id=next;l.shader_params=shaderDefaults(shaderAsset(next));}l.shader_fps=clamp(+$('layerShaderFps').value||15,1,30);l.shader_time_scale=clamp(+$('layerShaderTimeScale').value||1,-10,10);l.shader_quality=$('layerShaderQuality').value||'auto';l.shader_live_weather=$('layerShaderLiveWeather').checked;l.shader_weather_lat=+$('layerShaderWeatherLat').value||0;l.shader_weather_lon=+$('layerShaderWeatherLon').value||0;l.shader_weather_refresh=clamp(+$('layerShaderWeatherRefresh').value||600,60,3600);}
    if(l.type==='widget'){l.widget_type=$('layerWidgetType').value;l.widget_format=$('layerWidgetFormat').value;l.refresh_seconds=Math.max(5,+$('layerWidgetRefresh').value||300);l.clock_ring_color=$('clockRingColor').value;l.clock_tick_color=$('clockTickColor').value;l.clock_hour_color=$('clockHourColor').value;l.clock_minute_color=$('clockMinuteColor').value;l.clock_second_color=$('clockSecondColor').value;l.clock_face_color=$('clockFaceColor').value;l.clock_show_seconds=$('clockShowSeconds').checked;l.clock_fill_face=$('clockFillFace').checked;l.countdown_target=$('layerCountdownTarget').value;l.countdown_format=$('layerCountdownFormat').value;l.weather_lat=+$('layerWeatherLat').value||0;l.weather_lon=+$('layerWeatherLon').value||0;l.weather_display=$('layerWeatherDisplay').value;l.weather_temp_unit=$('layerWeatherTempUnit').value;l.weather_wind_unit=$('layerWeatherWindUnit').value;l.weather_show_icon=$('weatherShowIcon').checked;l.weather_animate_icon=$('weatherAnimateIcon').checked;l.weather_show_condition=$('weatherShowCondition').checked;l.weather_show_feels=$('weatherShowFeels').checked;l.weather_show_wind=$('weatherShowWind').checked;l.weather_show_gusts=$('weatherShowGusts').checked;l.weather_show_humidity=$('weatherShowHumidity').checked;l.weather_show_precip=$('weatherShowPrecip').checked;l.weather_cycle_details=$('weatherCycleDetails').checked;l.weather_detail_period=Math.max(1,+$('weatherDetailPeriod').value||2.5);l.weather_template=$('layerWeatherTemplate').value;l.data_url=$('layerDataUrl').value.trim();l.json_path=$('layerJsonPath').value.trim();l.rss_item=Math.max(0,(+$('layerRssItem').value||1)-1);l.widget_prefix=$('layerDataPrefix').value;l.widget_suffix=$('layerDataSuffix').value;l.font=$('widgetFont').value;l.font_size=Math.max(4,+$('widgetFontSize').value||18);l.render_mode=$('widgetRenderMode').value;l.color=$('widgetColor').value;l.auto_fit=$('widgetAutoFit').checked;l.align=$('widgetAlign').value;l.valign=$('widgetVAlign').value;l.padding=Math.max(0,+$('widgetPadding').value||0);updateWidgetFieldVisibility();}
    if(l.type==='icon'){l.icon_name=$('layerIconName').value;l.icon_color=$('layerIconColor').value;l.icon_color2=$('layerIconColor2').value;l.icon_effect=$('layerIconEffect').value;l.icon_period=Math.max(.15,+$('layerIconPeriod').value||1);}
    if(l.type==='shape'){l.shape=$('layerShape').value;l.fill=$('layerFill').value;l.border_color=$('layerBorderColor').value;l.border_width=Math.max(0,+$('layerBorderWidth').value||0);l.radius=Math.max(0,+$('layerRadius').value||0);}
    updatePreviewTimelineRange();renderLayerList();scheduleEditorPreview();
  }
  function addLayer(type){
    if(!state.scene)state.scene=templateScene('blank');recordHistory();let l;if(type==='image')l=defaultImageLayer();else if(type==='video')l=defaultVideoLayer();else if(type==='shader')l=defaultShaderLayer();else if(type==='widget')l=defaultWidgetLayer();else if(type==='icon')l=defaultIconLayer();else if(type==='shape')l=defaultShapeLayer();else l=defaultTextLayer();const maxZ=state.scene.layers.reduce((m,x)=>Math.max(m,+x.z||0),0);l.z=maxZ+10;state.scene.layers.push(l);setSelection([l.id],l.id);renderLayerList();loadSelectedLayerControls();scheduleEditorPreview();
  }
  function deleteLayer(){const ls=selectionLayers();if(!ls.length)return;recordHistory();const ids=new Set(ls.map(l=>l.id));state.scene.layers=state.scene.layers.filter(x=>!ids.has(x.id));const next=state.scene.layers.at(-1)?.id||null;setSelection(next?[next]:[],next);renderLayerList();loadSelectedLayerControls();scheduleEditorPreview();}
  function duplicateLayer(){const ls=selectionLayers();if(!ls.length)return;recordHistory();const maxZ=state.scene.layers.reduce((m,x)=>Math.max(m,+x.z||0),0);const groupMap=new Map(),copies=ls.map((l,i)=>{const c=deepClone(l);c.id=uid();c.name=`${l.name||l.type} copy`;c.x=(+c.x||0)+2;c.y=(+c.y||0)+2;c.z=maxZ+10+i*10;if(c.group_id){if(!groupMap.has(c.group_id))groupMap.set(c.group_id,uid());c.group_id=groupMap.get(c.group_id);}return c;});state.scene.layers.push(...copies);setSelection(copies.map(c=>c.id),copies[0]?.id);renderLayerList();loadSelectedLayerControls();scheduleEditorPreview();}
  function moveLayer(delta){const ls=selectionLayers();if(!ls.length)return;recordHistory();const amount=delta>0?10:-10;ls.forEach(l=>l.z=(+l.z||0)+amount);const ordered=[...state.scene.layers].sort((a,b)=>(+a.z||0)-(+b.z||0));ordered.forEach((l,i)=>l.z=i*10);renderLayerList();scheduleEditorPreview();}
  function applyTemplate(kind){if(state.scene?.layers?.length&&!confirm('Replace the current Designer layers with this template?'))return;recordHistory();state.scene=templateScene(kind);const id=state.scene.layers.at(-1)?.id||null;setSelection(id?[id]:[],id);state.selectedZoneId=null;syncSceneBackgroundControls();renderLayerList();loadSelectedLayerControls();state.previewStarted=performance.now();scheduleEditorPreview();}
  function groupSelected(){const ls=selectionLayers();if(ls.length<2){toast('Select at least two layers to group',true);return;}recordHistory();const gid=uid().replace(/^L/,'G');ls.forEach(l=>l.group_id=gid);renderLayerList();toast(`${ls.length} layers grouped`);}
  function ungroupSelected(){const ls=selectionLayers();if(!ls.length)return;recordHistory();const gids=new Set(ls.map(l=>l.group_id).filter(Boolean));state.scene.layers.forEach(l=>{if(gids.has(l.group_id)||ls.includes(l))l.group_id='';});renderLayerList();toast('Group removed');}
  function alignSelection(mode){const ls=selectionLayers();if(!ls.length)return;recordHistory();const dw=state.scene.design_width||logicalSize().w,dh=state.scene.design_height||logicalSize().h,b=selectionBounds(ls);if(!b)return;
    if(mode==='distribute-h'&&ls.length>=3){const ordered=[...ls].sort((a,b)=>(+a.x||0)-(+b.x||0)),left=Math.min(...ordered.map(l=>+l.x||0)),right=Math.max(...ordered.map(l=>(+l.x||0)+(+l.w||1))),total=ordered.reduce((n,l)=>n+(+l.w||1),0),gap=(right-left-total)/(ordered.length-1);let x=left;ordered.forEach(l=>{l.x=Math.round(x);x+=(+l.w||1)+gap;});}
    else if(mode==='distribute-v'&&ls.length>=3){const ordered=[...ls].sort((a,b)=>(+a.y||0)-(+b.y||0)),top=Math.min(...ordered.map(l=>+l.y||0)),bottom=Math.max(...ordered.map(l=>(+l.y||0)+(+l.h||1))),total=ordered.reduce((n,l)=>n+(+l.h||1),0),gap=(bottom-top-total)/(ordered.length-1);let y=top;ordered.forEach(l=>{l.y=Math.round(y);y+=(+l.h||1)+gap;});}
    else{const ref=ls.length===1?{x:0,y:0,w:dw,h:dh,x2:dw,y2:dh}:b;for(const l of ls){if(mode==='left')l.x=Math.round(ref.x);if(mode==='hcenter')l.x=Math.round(ref.x+ref.w/2-(+l.w||1)/2);if(mode==='right')l.x=Math.round(ref.x2-(+l.w||1));if(mode==='top')l.y=Math.round(ref.y);if(mode==='vcenter')l.y=Math.round(ref.y+ref.h/2-(+l.h||1)/2);if(mode==='bottom')l.y=Math.round(ref.y2-(+l.h||1));}}
    loadSelectedLayerControls();renderLayerList();scheduleEditorPreview();
  }
  function snapPosition(x,y,w,h,ignoreIds=new Set()){
    const grid=Math.max(1,+$('designerSnapGrid')?.value||1);x=Math.round(x/grid)*grid;y=Math.round(y/grid)*grid;if(!$('designerSnapObjects')?.checked)return{x,y};
    const dw=state.scene.design_width||logicalSize().w,dh=state.scene.design_height||logicalSize().h,threshold=2.25;const tx=[0,dw/2,dw],ty=[0,dh/2,dh];
    for(const l of state.scene.layers||[]){if(ignoreIds.has(l.id))continue;tx.push(+l.x||0,(+l.x||0)+(+l.w||1),(+l.x||0)+(+l.w||1)/2);ty.push(+l.y||0,(+l.y||0)+(+l.h||1),(+l.y||0)+(+l.h||1)/2);}
    for(const z of state.scene.zones||[]){tx.push(+z.x||0,(+z.x||0)+(+z.w||1),(+z.x||0)+(+z.w||1)/2);ty.push(+z.y||0,(+z.y||0)+(+z.h||1),(+z.y||0)+(+z.h||1)/2);}
    const xs=[[x,0],[x+w,w],[x+w/2,w/2]],ys=[[y,0],[y+h,h],[y+h/2,h/2]];let bestX=x,bestDX=threshold+1;for(const [v,offset] of xs)for(const t of tx){const d=Math.abs(v-t);if(d<bestDX&&d<=threshold){bestDX=d;bestX=t-offset;}}let bestY=y,bestDY=threshold+1;for(const [v,offset] of ys)for(const t of ty){const d=Math.abs(v-t);if(d<bestDY&&d<=threshold){bestDY=d;bestY=t-offset;}}return{x:Math.round(bestX),y:Math.round(bestY)};
  }
  function updateSelectionOverlay(){
    const sel=$('designerSelection'),ls=selectionLayers(),img=$('editorPreview');renderZoneOverlays();if($('msgEditorMode').value!=='designer'||!ls.length||!img.complete||!img.naturalWidth){sel.classList.add('hidden');return;}const b=selectionBounds(ls),stage=$('designerStage').getBoundingClientRect(),r=img.getBoundingClientRect(),dw=state.scene.design_width||logicalSize().w,dh=state.scene.design_height||logicalSize().h;sel.style.left=`${r.left-stage.left+b.x/dw*r.width}px`;sel.style.top=`${r.top-stage.top+b.y/dh*r.height}px`;sel.style.width=`${Math.max(4,b.w/dw*r.width)}px`;sel.style.height=`${Math.max(4,b.h/dh*r.height)}px`;sel.style.transform=ls.length===1?`rotate(${+ls[0].rotation||0}deg)`:'none';sel.classList.toggle('multi',ls.length>1);sel.classList.remove('hidden');
  }
  function beginDesignerDrag(ev,mode){
    const ls=selectionLayers(),img=$('editorPreview');if(!ls.length||!img.complete)return;ev.preventDefault();recordHistory();const r=img.getBoundingClientRect(),dw=state.scene.design_width,dh=state.scene.design_height,b=selectionBounds(ls);state.drag={mode,startX:ev.clientX,startY:ev.clientY,bounds:b,layers:ls.map(l=>({id:l.id,x:+l.x||0,y:+l.y||0,w:+l.w||1,h:+l.h||1})),pxToX:dw/r.width,pxToY:dh/r.height};$('designerStage').classList.add(mode==='resize'?'resizing':'dragging');
  }
  function moveDesignerDrag(ev){
    if(!state.drag)return;const d=state.drag,dx=(ev.clientX-d.startX)*d.pxToX,dy=(ev.clientY-d.startY)*d.pxToY,ids=new Set(d.layers.map(a=>a.id));if(d.mode==='resize'){
      const primary=selectedLayer();if(!primary)return;const base=d.layers.find(a=>a.id===primary.id)||d.layers[0];const grid=Math.max(1,+$('designerSnapGrid')?.value||1);primary.w=Math.max(1,Math.round((base.w+dx)/grid)*grid);primary.h=Math.max(1,Math.round((base.h+dy)/grid)*grid);
    }else{const proposed=snapPosition(d.bounds.x+dx,d.bounds.y+dy,d.bounds.w,d.bounds.h,ids),mx=proposed.x-d.bounds.x,my=proposed.y-d.bounds.y;for(const a of d.layers){const l=state.scene.layers.find(x=>x.id===a.id);if(l){l.x=Math.round(a.x+mx);l.y=Math.round(a.y+my);}}}loadSelectedLayerControls();updateSelectionOverlay();scheduleEditorPreview();
  }
  function endDesignerDrag(){if(!state.drag)return;state.drag=null;$('designerStage').classList.remove('dragging','resizing');state.historyBurst=false;}

  async function saveSelectionAsComponent(){const ls=selectionLayers();if(!ls.length){toast('Select one or more layers first',true);return;}const name=prompt('Component name','Reusable component');if(!name)return;const b=selectionBounds(ls),ids=new Set(ls.map(l=>l.id)),zoneIds=new Set(ls.map(l=>l.zone_id).filter(Boolean)),zones=(state.scene.zones||[]).filter(z=>zoneIds.has(z.id)).map(z=>{const c=deepClone(z);c.x=(+c.x||0)-b.x;c.y=(+c.y||0)-b.y;return c;}),layers=ls.map(l=>{const c=deepClone(l);c.x=(+c.x||0)-b.x;c.y=(+c.y||0)-b.y;return c;});try{await api('/api/components',{method:'POST',body:{name,component:{version:1,width:b.w,height:b.h,layers,zones}}});state.components=await api('/api/components');populateComponents();toast('Component saved');}catch(e){toast(e.message,true);}}
  function populateComponents(){const el=$('componentPicker');if(!el)return;const current=el.value;el.innerHTML=option('','Choose component…')+(state.components||[]).map(c=>option(c.id,c.name)).join('');if([...el.options].some(o=>o.value===current))el.value=current;}
  function insertComponent(){const cid=+$('componentPicker').value,c=state.components.find(x=>+x.id===cid);if(!c?.component)return;recordHistory();const comp=deepClone(c.component),dw=state.scene.design_width||logicalSize().w,dh=state.scene.design_height||logicalSize().h,ox=Math.round((dw-(+comp.width||dw))/2),oy=Math.round((dh-(+comp.height||dh))/2),zoneMap=new Map(),groupMap=new Map(),componentGroup=uid().replace(/^L/,'G');for(const z of comp.zones||[]){const old=z.id,zid=`Z${uid().slice(1)}`;zoneMap.set(old,zid);z.id=zid;z.name=`${c.name}: ${z.name||'Zone'}`;z.x=(+z.x||0)+ox;z.y=(+z.y||0)+oy;state.scene.zones.push(z);}const maxZ=state.scene.layers.reduce((m,x)=>Math.max(m,+x.z||0),0),added=[];(comp.layers||[]).forEach((l,i)=>{l.id=uid();l.name=l.name||c.name;l.x=(+l.x||0)+ox;l.y=(+l.y||0)+oy;l.z=maxZ+10+i*10;if(l.zone_id&&zoneMap.has(l.zone_id))l.zone_id=zoneMap.get(l.zone_id);if(l.group_id){if(!groupMap.has(l.group_id))groupMap.set(l.group_id,componentGroup);l.group_id=groupMap.get(l.group_id);}else l.group_id=componentGroup;state.scene.layers.push(l);added.push(l.id);});setSelection(added,added[0]);renderLayerList();loadSelectedLayerControls();scheduleEditorPreview();toast(`Inserted ${c.name}`);}
  async function deleteComponent(){const cid=+$('componentPicker').value,c=state.components.find(x=>+x.id===cid);if(!c)return;if(!confirm(`Delete component "${c.name}"? Existing messages are not changed.`))return;try{await api(`/api/components/${cid}`,{method:'DELETE'});state.components=await api('/api/components');populateComponents();toast('Component deleted');}catch(e){toast(e.message,true);}}

  async function refreshContent(){
    const options=await api('/api/content-options');state.messageOptions=options.messages||[];state.playlistOptions=options.playlists||[];
    const jobs=[];if(can('messages'))jobs.push(api('/api/messages').then(v=>state.messages=v));if(can('playlists'))jobs.push(api('/api/playlists').then(v=>state.playlists=v));if(can('schedules'))jobs.push(Promise.all([api('/api/schedules'),api('/api/conditional-rules'),api('/api/brightness-schedules')]).then(([a,b,c])=>{state.schedules=a;state.conditionalRules=b;state.brightnessSchedules=c;}));await Promise.all(jobs);
    if(can('messages'))renderMessageList();if(can('playlists'))renderPlaylistList();if(can('schedules')){renderScheduleList();renderConditionalRuleList();renderBrightnessScheduleList();}populateSharedSelectors();
  }
  function populateSharedSelectors(){const msgOpts=state.messageOptions.map(m=>option(m.id,m.name)).join('');const quick=$('quickMessage').value,picker=$('playlistMessagePicker').value,def=$('defaultMessage').value;$('quickMessage').innerHTML=msgOpts;$('playlistMessagePicker').innerHTML=msgOpts;$('defaultMessage').innerHTML=option('','No default / blank')+msgOpts;if([...$('quickMessage').options].some(o=>o.value===quick))$('quickMessage').value=quick;if([...$('playlistMessagePicker').options].some(o=>o.value===picker))$('playlistMessagePicker').value=picker;if([...$('defaultMessage').options].some(o=>o.value===def))$('defaultMessage').value=def;updateScheduleTargetOptions();if($('conditionalTarget'))updateConditionalTargetOptions();if($('emergencyMessageSetting'))populateEmergencySetting();}


  // Playlists
  function renderPlaylistList(){ $('playlistList').innerHTML=state.playlists.length?state.playlists.map(p=>`<div class="list-item ${+state.selectedPlaylist===+p.id?'active':''}" data-playlist-id="${p.id}"><strong>${esc(p.name)}</strong><small>${p.items.length} item${p.items.length===1?'':'s'}</small></div>`).join(''):'<p class="muted">No playlists yet.</p>';$$('#playlistList [data-playlist-id]').forEach(el=>el.addEventListener('click',()=>selectPlaylist(+el.dataset.playlistId))); }
  function blankPlaylist(){ state.selectedPlaylist=null;state.playlistItems=[];$('playlistId').value='';$('playlistName').value='New playlist';renderPlaylistList();renderPlaylistItems(); }
  function selectPlaylist(id){const p=state.playlists.find(x=>+x.id===+id);if(!p)return;state.selectedPlaylist=p.id;$('playlistId').value=p.id;$('playlistName').value=p.name;state.playlistItems=p.items.map(i=>({message_id:+i.message_id,duration:+i.duration}));renderPlaylistList();renderPlaylistItems();}
  function renderPlaylistItems(){ $('playlistItems').innerHTML=state.playlistItems.length?state.playlistItems.map((it,i)=>{const m=state.messageOptions.find(x=>+x.id===+it.message_id);return `<div class="playlist-item"><div class="reorder"><button title="Move up" data-up="${i}">▲</button><button title="Move down" data-down="${i}">▼</button></div><strong>${esc(m?m.name:'Missing message')}</strong><label>Seconds<input type="number" min="0.5" step="0.5" value="${it.duration}" data-duration="${i}"></label><button class="remove-item" title="Remove" data-remove="${i}">×</button></div>`}).join(''):'<div class="callout">Add one or more saved messages above. The playlist will loop continuously.</div>';$$('[data-duration]').forEach(el=>el.addEventListener('change',()=>state.playlistItems[+el.dataset.duration].duration=Math.max(.5,+el.value||10)));$$('[data-remove]').forEach(el=>el.addEventListener('click',()=>{state.playlistItems.splice(+el.dataset.remove,1);renderPlaylistItems();}));$$('[data-up]').forEach(el=>el.addEventListener('click',()=>movePlaylistItem(+el.dataset.up,-1)));$$('[data-down]').forEach(el=>el.addEventListener('click',()=>movePlaylistItem(+el.dataset.down,1))); }
  function movePlaylistItem(i,d){const j=i+d;if(j<0||j>=state.playlistItems.length)return;[state.playlistItems[i],state.playlistItems[j]]=[state.playlistItems[j],state.playlistItems[i]];renderPlaylistItems();}
  async function savePlaylist(showAfter=false){try{const id=$('playlistId').value;const p=await api(id?`/api/playlists/${id}`:'/api/playlists',{method:id?'PUT':'POST',body:{name:$('playlistName').value.trim()||'Playlist',enabled:true,items:state.playlistItems}});state.selectedPlaylist=p.id;await refreshContent();selectPlaylist(p.id);toast('Playlist saved');if(showAfter){await api(`/api/playlists/${p.id}/show`,{method:'POST',body:{duration:0}});toast('Showing playlist now');}}catch(e){toast(e.message,true);}}
  async function deletePlaylist(){const id=$('playlistId').value;if(!id)return;if(!confirm('Delete this playlist?'))return;try{await api(`/api/playlists/${id}`,{method:'DELETE'});state.selectedPlaylist=null;await refreshContent();state.playlists.length?selectPlaylist(state.playlists[0].id):blankPlaylist();toast('Playlist deleted');}catch(e){toast(e.message,true);}}

  // Schedules
  function renderScheduleList(){ $('scheduleList').innerHTML=state.schedules.length?state.schedules.map(s=>`<div class="list-item ${+state.selectedSchedule===+s.id?'active':''}" data-schedule-id="${s.id}"><strong>${esc(s.name)}</strong><small>${esc(s.start_time)}–${esc(s.end_time)} · priority ${s.priority}${s.enabled?'':' · disabled'}</small></div>`).join(''):'<p class="muted">No timed schedules yet.</p>';$$('#scheduleList [data-schedule-id]').forEach(el=>el.addEventListener('click',()=>selectSchedule(+el.dataset.scheduleId))); }
  function blankSchedule(){state.selectedSchedule=null;$('scheduleId').value='';$('scheduleName').value='New schedule';$('scheduleTargetType').value='message';updateScheduleTargetOptions();$('schedulePriority').value=100;$('scheduleStartTime').value='00:00';$('scheduleEndTime').value='23:59';$('scheduleStartDate').value='';$('scheduleEndDate').value='';$('scheduleEnabled').checked=true;$$('.day-picker [data-day]').forEach(x=>x.checked=true);renderScheduleList();}
  function updateScheduleTargetOptions(selected){const type=$('scheduleTargetType').value;const list=type==='playlist'?state.playlistOptions:state.messageOptions;$('scheduleTarget').innerHTML=list.map(x=>option(x.id,x.name,+x.id===+selected)).join('');}
  function selectSchedule(id){const s=state.schedules.find(x=>+x.id===+id);if(!s)return;state.selectedSchedule=s.id;$('scheduleId').value=s.id;$('scheduleName').value=s.name;$('scheduleTargetType').value=s.target_type;updateScheduleTargetOptions(s.target_id);$('schedulePriority').value=s.priority;$('scheduleStartTime').value=s.start_time||'00:00';$('scheduleEndTime').value=s.end_time||'23:59';$('scheduleStartDate').value=s.start_date||'';$('scheduleEndDate').value=s.end_date||'';$('scheduleEnabled').checked=!!s.enabled;const days=new Set(String(s.days||'').split(','));$$('.day-picker [data-day]').forEach(x=>x.checked=days.has(x.dataset.day));renderScheduleList();}
  async function saveSchedule(){try{const id=$('scheduleId').value;const days=$$('.day-picker [data-day]:checked').map(x=>x.dataset.day).join(',');if(!days)throw new Error('Select at least one day');if(!$('scheduleTarget').value)throw new Error('Create content first, then choose it here');const body={name:$('scheduleName').value.trim()||'Schedule',target_type:$('scheduleTargetType').value,target_id:+$('scheduleTarget').value,days,start_date:$('scheduleStartDate').value,end_date:$('scheduleEndDate').value,start_time:$('scheduleStartTime').value||'00:00',end_time:$('scheduleEndTime').value||'23:59',priority:+$('schedulePriority').value||0,enabled:$('scheduleEnabled').checked};const s=await api(id?`/api/schedules/${id}`:'/api/schedules',{method:id?'PUT':'POST',body});state.selectedSchedule=s.id;await refreshContent();selectSchedule(s.id);toast('Schedule saved');}catch(e){toast(e.message,true);}}
  async function deleteSchedule(){const id=$('scheduleId').value;if(!id)return;if(!confirm('Delete this schedule?'))return;try{await api(`/api/schedules/${id}`,{method:'DELETE'});state.selectedSchedule=null;await refreshContent();state.schedules.length?selectSchedule(state.schedules[0].id):blankSchedule();toast('Schedule deleted');}catch(e){toast(e.message,true);}}

  // Conditional content
  function conditionSummary(r){const rt=r.runtime||{};if(!r.enabled)return 'Disabled';if(rt.eligible)return `ACTIVE · ${rt.detail||''}`;if(rt.matching)return `Waiting · ${rt.detail||''}`;return rt.detail||'Not matched';}
  function renderConditionalRuleList(){$('conditionalRuleList').innerHTML=state.conditionalRules.length?state.conditionalRules.map(r=>`<div class="list-item ${+state.selectedConditionalRule===+r.id?'active':''}" data-rule-id="${r.id}"><strong>${esc(r.name)}</strong><small>priority ${r.priority} · ${esc(conditionSummary(r))}</small></div>`).join(''):'<p class="muted">No conditional rules yet.</p>';$$('[data-rule-id]').forEach(el=>el.addEventListener('click',()=>selectConditionalRule(+el.dataset.ruleId)));}
  function updateConditionalTargetOptions(selected){const type=$('conditionalTargetType').value,list=type==='playlist'?state.playlistOptions:state.messageOptions;$('conditionalTarget').innerHTML=list.map(x=>option(x.id,x.name,+x.id===+selected)).join('');}
  function syncConditionFields(){const json=$('conditionalType').value==='json';$('conditionalJsonFields').classList.toggle('hidden',!json);$('conditionalWeatherFields').classList.toggle('hidden',json);}
  function blankConditionalRule(){state.selectedConditionalRule=null;$('conditionalRuleId').value='';$('conditionalRuleName').value='New condition';$('conditionalRulePriority').value=150;$('conditionalTargetType').value='message';updateConditionalTargetOptions();$('conditionalType').value='weather_temp';$('conditionalOperator').value='gt';$('conditionalValue').value='';$('conditionalWeatherLat').value='';$('conditionalWeatherLon').value='';$('conditionalWeatherUnits').value='c|mph';$('conditionalJsonUrl').value='';$('conditionalJsonPath').value='';$('conditionalTrueFor').value=0;$('conditionalHold').value=30;$('conditionalEnabled').checked=true;$('conditionalRuntime').textContent='Not evaluated yet.';syncConditionFields();renderConditionalRuleList();}
  function selectConditionalRule(id){const r=state.conditionalRules.find(x=>+x.id===+id);if(!r)return;state.selectedConditionalRule=+r.id;$('conditionalRuleId').value=r.id;$('conditionalRuleName').value=r.name;$('conditionalRulePriority').value=r.priority;$('conditionalTargetType').value=r.target_type;updateConditionalTargetOptions(r.target_id);$('conditionalType').value=r.condition_type;$('conditionalOperator').value=r.operator;$('conditionalValue').value=r.compare_value??'';const c=r.config||{};$('conditionalWeatherLat').value=c.lat??'';$('conditionalWeatherLon').value=c.lon??'';$('conditionalWeatherUnits').value=`${c.temp_unit||'c'}|${c.wind_unit||'mph'}`;$('conditionalJsonUrl').value=c.url||'';$('conditionalJsonPath').value=c.path||'';$('conditionalTrueFor').value=r.true_for_seconds||0;$('conditionalHold').value=r.minimum_hold_seconds||0;$('conditionalEnabled').checked=!!r.enabled;$('conditionalRuntime').textContent=conditionSummary(r);syncConditionFields();renderConditionalRuleList();}
  async function saveConditionalRule(){try{if(!$('conditionalTarget').value)throw new Error('Choose content for this rule');const [temp_unit,wind_unit]=$('conditionalWeatherUnits').value.split('|');const isJson=$('conditionalType').value==='json';if(!isJson&&($('conditionalWeatherLat').value.trim()===''||$('conditionalWeatherLon').value.trim()===''))throw new Error('Enter latitude and longitude for the weather condition');if(isJson&&!$('conditionalJsonUrl').value.trim())throw new Error('Enter the JSON/API URL');const config=isJson?{url:$('conditionalJsonUrl').value.trim(),path:$('conditionalJsonPath').value.trim(),refresh_seconds:60}:{lat:+$('conditionalWeatherLat').value,lon:+$('conditionalWeatherLon').value,temp_unit,wind_unit,refresh_seconds:300};const body={name:$('conditionalRuleName').value.trim()||'Conditional rule',target_type:$('conditionalTargetType').value,target_id:+$('conditionalTarget').value,condition_type:$('conditionalType').value,operator:$('conditionalOperator').value,compare_value:$('conditionalValue').value.trim(),config,priority:+$('conditionalRulePriority').value||0,true_for_seconds:+$('conditionalTrueFor').value||0,minimum_hold_seconds:+$('conditionalHold').value||0,enabled:$('conditionalEnabled').checked};const id=$('conditionalRuleId').value,r=await api(id?`/api/conditional-rules/${id}`:'/api/conditional-rules',{method:id?'PUT':'POST',body});state.selectedConditionalRule=r.id;await refreshContent();const rules=await api('/api/conditional-rules');state.conditionalRules=rules;selectConditionalRule(r.id);toast('Conditional rule saved');}catch(e){toast(e.message,true);}}
  async function deleteConditionalRule(){const id=$('conditionalRuleId').value;if(!id)return;if(!confirm('Delete this conditional rule?'))return;try{await api(`/api/conditional-rules/${id}`,{method:'DELETE'});state.selectedConditionalRule=null;state.conditionalRules=await api('/api/conditional-rules');state.conditionalRules.length?selectConditionalRule(state.conditionalRules[0].id):blankConditionalRule();toast('Conditional rule deleted');}catch(e){toast(e.message,true);}}

  // Brightness schedules
  function renderBrightnessScheduleList(){$('brightnessScheduleList').innerHTML=state.brightnessSchedules.length?state.brightnessSchedules.map(b=>`<div class="list-item ${+state.selectedBrightnessSchedule===+b.id?'active':''}" data-bright-id="${b.id}"><strong>${esc(b.name)}</strong><small>${esc(b.start_time)}–${esc(b.end_time)} · ${b.brightness}% · priority ${b.priority}${b.enabled?'':' · disabled'}</small></div>`).join(''):'<p class="muted">No brightness profiles yet.</p>';$$('[data-bright-id]').forEach(el=>el.addEventListener('click',()=>selectBrightnessSchedule(+el.dataset.brightId)));}
  function blankBrightnessSchedule(){state.selectedBrightnessSchedule=null;$('brightnessScheduleId').value='';$('brightnessScheduleName').value='Evening';$('brightnessSchedulePriority').value=100;$('brightnessStartTime').value='18:00';$('brightnessEndTime').value='22:00';$('brightnessScheduleBrightness').value=40;$('brightnessScheduleValue').textContent='40%';$('brightnessScheduleEnabled').checked=true;$$('[data-brightness-day]').forEach(x=>x.checked=true);renderBrightnessScheduleList();}
  function selectBrightnessSchedule(id){const b=state.brightnessSchedules.find(x=>+x.id===+id);if(!b)return;state.selectedBrightnessSchedule=+b.id;$('brightnessScheduleId').value=b.id;$('brightnessScheduleName').value=b.name;$('brightnessSchedulePriority').value=b.priority;$('brightnessStartTime').value=b.start_time||'00:00';$('brightnessEndTime').value=b.end_time||'23:59';$('brightnessScheduleBrightness').value=b.brightness;$('brightnessScheduleValue').textContent=`${b.brightness}%`;$('brightnessScheduleEnabled').checked=!!b.enabled;const days=new Set(String(b.days||'').split(','));$$('[data-brightness-day]').forEach(x=>x.checked=days.has(x.dataset.brightnessDay));renderBrightnessScheduleList();}
  async function saveBrightnessSchedule(){try{const days=$$('[data-brightness-day]:checked').map(x=>x.dataset.brightnessDay).join(',');if(!days)throw new Error('Select at least one day');const body={name:$('brightnessScheduleName').value.trim()||'Brightness schedule',days,start_time:$('brightnessStartTime').value||'00:00',end_time:$('brightnessEndTime').value||'23:59',brightness:+$('brightnessScheduleBrightness').value,priority:+$('brightnessSchedulePriority').value||0,enabled:$('brightnessScheduleEnabled').checked},id=$('brightnessScheduleId').value,b=await api(id?`/api/brightness-schedules/${id}`:'/api/brightness-schedules',{method:id?'PUT':'POST',body});state.selectedBrightnessSchedule=b.id;state.brightnessSchedules=await api('/api/brightness-schedules');selectBrightnessSchedule(b.id);toast('Brightness profile saved');}catch(e){toast(e.message,true);}}
  async function deleteBrightnessSchedule(){const id=$('brightnessScheduleId').value;if(!id)return;if(!confirm('Delete this brightness profile?'))return;try{await api(`/api/brightness-schedules/${id}`,{method:'DELETE'});state.selectedBrightnessSchedule=null;state.brightnessSchedules=await api('/api/brightness-schedules');state.brightnessSchedules.length?selectBrightnessSchedule(state.brightnessSchedules[0].id):blankBrightnessSchedule();toast('Brightness profile deleted');}catch(e){toast(e.message,true);}}
  function populateEmergencySetting(){if(!$('emergencyMessageSetting'))return;const current=state.settings?.emergency_message_id||'';$('emergencyMessageSetting').innerHTML=option('','Not configured')+state.messageOptions.map(m=>option(m.id,m.name,+m.id===+current)).join('');updateEmergencyDashboard();}
  function updateEmergencyDashboard(){if(!$('emergencyConfigured'))return;const id=state.settings?.emergency_message_id,m=state.messageOptions.find(x=>+x.id===+id);$('emergencyConfigured').textContent=m?`Configured message: ${m.name}`:'No emergency message configured. Set one under Schedules → Emergency mode.';$('activateEmergency').disabled=!m;}
  async function saveEmergencySetting(){try{const r=await api('/api/operations/settings',{method:'PUT',body:{emergency_message_id:$('emergencyMessageSetting').value?+$('emergencyMessageSetting').value:null}});state.settings.emergency_message_id=r.emergency_message_id;populateEmergencySetting();toast('Emergency message saved');}catch(e){toast(e.message,true);}}

  // Users
  function userRightsSummary(u){
    const labels=[];if(u.can_messages)labels.push('Messages');if(u.can_playlists)labels.push('Playlists');if(u.can_schedules)labels.push('Schedules');if(u.can_display_setup)labels.push('Display setup');if(u.can_backup)labels.push('Backup');if(u.can_users)labels.push('Users');return labels.length?labels.join(' · '):'Dashboard only';
  }
  function renderUserList(){
    if(!$('userList'))return;
    $('userList').innerHTML=state.users.length?state.users.map(u=>`<div class="list-item ${+state.selectedUser===+u.id?'active':''} ${u.is_active?'':'disabled-item'}" data-user-id="${u.id}"><strong>${esc(u.display_name||u.username)}${+u.id===+state.auth?.user?.id?' · You':''}</strong><small>@${esc(u.username)} · ${u.is_active?esc(userRightsSummary(u)):'Disabled'}</small></div>`).join(''):'<p class="muted">No users.</p>';
    $$('#userList [data-user-id]').forEach(el=>el.addEventListener('click',()=>selectUser(+el.dataset.userId)));
  }
  function blankUser(){
    state.selectedUser=null;$('userId').value='';$('userEditorTitle').textContent='New user';$('userUsername').value='';$('userDisplayName').value='';$('userActive').checked=true;
    ['permMessages','permPlaylists','permSchedules','permDisplaySetup','permBackup','permUsers'].forEach(id=>$(id).checked=false);
    $('userPassword').value='';$('userMustChange').checked=true;$('userPasswordHint').textContent='required for a new user';$('deleteUser').disabled=true;$('currentUserRightsNotice').classList.add('hidden');renderUserList();
  }
  function selectUser(id){
    const u=state.users.find(x=>+x.id===+id);if(!u)return;state.selectedUser=+u.id;$('userId').value=u.id;$('userEditorTitle').textContent=u.display_name||u.username;$('userUsername').value=u.username;$('userDisplayName').value=u.display_name||'';$('userActive').checked=!!u.is_active;
    $('permMessages').checked=!!u.can_messages;$('permPlaylists').checked=!!u.can_playlists;$('permSchedules').checked=!!u.can_schedules;$('permDisplaySetup').checked=!!u.can_display_setup;$('permBackup').checked=!!u.can_backup;$('permUsers').checked=!!u.can_users;
    $('userPassword').value='';$('userMustChange').checked=!!u.must_change_password;$('userPasswordHint').textContent='leave blank to keep current password';$('deleteUser').disabled=+u.id===+state.auth?.user?.id;$('currentUserRightsNotice').classList.toggle('hidden',+u.id!==+state.auth?.user?.id);renderUserList();
  }
  async function loadUsers(){
    if(!can('users'))return;try{state.users=await api('/api/users');renderUserList();if(state.selectedUser&&state.users.some(u=>+u.id===+state.selectedUser))selectUser(state.selectedUser);else if(state.users.length)selectUser(state.users[0].id);else blankUser();}catch(e){toast(e.message,true);}
  }
  function userPayload(){return {username:$('userUsername').value.trim(),display_name:$('userDisplayName').value.trim(),is_active:$('userActive').checked,messages:$('permMessages').checked,playlists:$('permPlaylists').checked,schedules:$('permSchedules').checked,display_setup:$('permDisplaySetup').checked,backup:$('permBackup').checked,users:$('permUsers').checked,password:$('userPassword').value,must_change_password:$('userMustChange').checked};}
  async function saveUser(){
    try{const id=$('userId').value,body=userPayload();if(!body.username)throw new Error('Enter a username');if(!id&&!body.password)throw new Error('Enter an initial password');const saved=await api(id?`/api/users/${id}`:'/api/users',{method:id?'PUT':'POST',body});state.selectedUser=+saved.id;await refreshAuth();if(!can('users')){toast('User saved. Your access rights have changed.');showDashboard();return;}await loadUsers();selectUser(saved.id);toast(id?'User updated':'User created');}catch(e){toast(e.message,true);}
  }
  async function deleteUser(){
    const id=+$('userId').value;if(!id)return;if(!confirm('Delete this user account?'))return;try{await api(`/api/users/${id}`,{method:'DELETE'});state.selectedUser=null;await loadUsers();toast('User deleted');}catch(e){toast(e.message,true);}
  }


  // Backup & restore ----------------------------------------------------
  function backupTabVisible(){return document.querySelector('.tab.active')?.dataset.tab==='backup'&&!document.hidden;}
  function backupStateBusy(name){return ['queued','creating','safety_backup','restoring','restoring_fpp'].includes(String(name||'').toLowerCase());}
  function renderBackupStatus(status={}){
    const st=String(status.state||'ready').toLowerCase(),busy=backupStateBusy(st);state.backupBusy=busy;
    const labels={ready:'Ready',queued:'Queued',creating:'Creating backup…',safety_backup:'Creating safety backup…',restoring:'Restoring Pi Matrix Signage…',restoring_fpp:'Restoring FPP…',success:'Complete',failed:'Failed'};
    $('backupState').textContent=labels[st]||st||'Ready';$('backupOperation').textContent=status.operation?String(status.operation).replace(/^./,c=>c.toUpperCase()):'—';$('backupStatusFile').textContent=status.filename||'—';$('backupSafety').textContent=status.safety_backup||'—';$('backupMessage').textContent=status.message||'Ready to create or restore a backup.';
    $('backupMessage').classList.toggle('warn',st==='failed');$('createBackup').disabled=busy;$('backupRestoreFile').disabled=busy;
    const progress=$('backupProgress');progress.classList.toggle('hidden',!busy);$('backupProgressBar').style.width=st==='queued'?'10%':st==='creating'?'45%':st==='safety_backup'?'25%':st==='restoring'?'55%':st==='restoring_fpp'?'80%':'100%';
    return busy;
  }
  function renderBackupList(){
    const list=$('backupList');if(!list)return;
    if(!state.backups.length){list.innerHTML='<p class="muted">No saved backups yet. Create one above, then download a copy somewhere safe.</p>';return;}
    list.innerHTML=state.backups.map(b=>{
      const invalid=b.invalid?'<span class="backup-pill error">Invalid</span>':b.reason==='pre-restore'?'<span class="backup-pill safety">Safety</span>':'<span class="backup-pill">Full</span>';
      const when=b.created_at?new Date(b.created_at).toLocaleString():new Date(b.modified_at).toLocaleString();
      return `<div class="backup-row ${b.invalid?'invalid':''}"><div class="backup-row-main"><div><strong>${esc(b.filename)}</strong>${invalid}</div><small>${esc(when)} · ${formatBytes(b.size)}${b.app_version?` · app v${esc(b.app_version)}`:''}${b.hostname?` · ${esc(b.hostname)}`:''}</small>${b.invalid?`<small class="error-text">${esc(b.error||'Invalid backup')}</small>`:''}</div><div class="backup-row-actions">${b.invalid?'':`<a class="btn secondary small" href="/api/backups/${encodeURIComponent(b.filename)}/download">Download</a><button class="btn secondary small" data-backup-restore="${esc(b.filename)}">Restore</button>`}<button class="btn danger ghost small" data-backup-delete="${esc(b.filename)}">Delete</button></div></div>`;
    }).join('');
    $$('[data-backup-restore]').forEach(btn=>btn.addEventListener('click',()=>restoreExistingBackup(btn.dataset.backupRestore)));
    $$('[data-backup-delete]').forEach(btn=>btn.addEventListener('click',()=>deleteBackup(btn.dataset.backupDelete)));
  }
  async function loadBackups(quiet=false){
    if(!can('backup'))return;
    try{const data=await api('/api/backups');state.backups=data.backups||[];renderBackupList();const busy=renderBackupStatus(data.status||{});if(busy)scheduleBackupPoll();}
    catch(e){if(!quiet)toast(e.message,true);}
  }
  function scheduleBackupPoll(){clearTimeout(state.backupPollTimer);state.backupPollTimer=setTimeout(async()=>{if(!backupTabVisible())return;try{const data=await api('/api/backups/status');const busy=renderBackupStatus(data.status||{});if(!busy){await loadBackups(true);if(data.status?.state==='success'&&data.status?.operation==='restore'){setTimeout(()=>location.reload(),1200);return;}}if(busy)scheduleBackupPoll();}catch(_){scheduleBackupPoll();}},900);}
  async function createBackup(){
    if(state.backupBusy)return;
    try{await api('/api/backups/create',{method:'POST',body:{}});renderBackupStatus({state:'queued',operation:'backup',message:'Backup requested; collecting Pi Matrix Signage data and FPP configuration…'});scheduleBackupPoll();toast('Backup started');}
    catch(e){toast(e.message,true);}
  }
  function restoreOptions(){return {keep_network:$('backupKeepNetwork').checked,keep_mode:$('backupKeepMode').checked};}
  async function restoreExistingBackup(filename){
    if(state.backupBusy)return;
    const network=$('backupKeepNetwork').checked?'Current FPP network settings will be kept.':'WARNING: FPP network settings WILL be restored and this Pi may change IP/network.';
    if(!confirm(`Restore ${filename}?\n\n${network}\n\nThe current database/media will be replaced. An automatic safety backup is created first.`))return;
    if(!confirm('Final confirmation: start the restore now? The display and web service will restart briefly.'))return;
    try{await api(`/api/backups/${encodeURIComponent(filename)}/restore`,{method:'POST',body:restoreOptions()});renderBackupStatus({state:'queued',operation:'restore',filename,message:'Restore queued. Creating a safety backup first…'});scheduleBackupPoll();}
    catch(e){toast(e.message,true);}
  }
  async function deleteBackup(filename){
    if(!confirm(`Delete backup ${filename}? This cannot be undone.`))return;
    try{await api(`/api/backups/${encodeURIComponent(filename)}`,{method:'DELETE'});await loadBackups(true);toast('Backup deleted');}catch(e){toast(e.message,true);}
  }
  function setBackupUploadProgress(percent,detail=''){
    const box=$('backupUploadProgress');box.classList.remove('hidden');$('backupUploadPercent').textContent=`${Math.round(percent)}%`;$('backupUploadBar').style.width=`${clamp(percent,0,100)}%`;$('backupUploadDetail').textContent=detail;
  }
  async function restoreUploadedBackup(file){
    if(!file||state.backupBusy)return;
    if(!confirm(`Restore from uploaded backup ${file.name}?\n\nA safety backup of the current system will be created automatically before anything is replaced.`)){$('backupRestoreFile').value='';return;}
    const fd=new FormData();fd.append('file',file);fd.append('keep_network',$('backupKeepNetwork').checked?'1':'0');fd.append('keep_mode',$('backupKeepMode').checked?'1':'0');
    try{setBackupUploadProgress(0,`Uploading ${file.name}…`);const result=await xhrUploadJson('/api/backups/restore-upload',fd,(pct,loaded,total)=>setBackupUploadProgress(pct,`${formatBytes(loaded)} of ${formatBytes(total)}`));setBackupUploadProgress(100,'Upload complete. Creating safety backup and restoring…');renderBackupStatus({state:'queued',operation:'restore',filename:result.filename,message:'Backup uploaded. Restore queued; creating safety backup first…'});scheduleBackupPoll();}
    catch(e){toast(e.message,true);$('backupUploadDetail').textContent=e.message;}
    finally{$('backupRestoreFile').value='';}
  }

  // Commercial licensing ---------------------------------------------------
  function fmtLicenceDate(value){if(!value)return '—';const d=new Date(value);return Number.isNaN(d.getTime())?String(value):d.toLocaleString();}
  function renderLicence(){
    const l=state.license;if(!l)return;
    const banner=$('licenseBanner'),card=$('licenceCard'),badge=$('licenceStatusBadge');
    if($('licenceStatus'))$('licenceStatus').textContent=l.status||'Unknown';
    if($('licenceMessage'))$('licenceMessage').textContent=l.message||'';
    if($('licenceDeviceId'))$('licenceDeviceId').textContent=l.device_id||'—';
    if($('licenceDeviceSource'))$('licenceDeviceSource').textContent=l.device_source?`Bound using ${l.device_source}`:'—';
    if($('licenceKeyMasked'))$('licenceKeyMasked').textContent=l.license_key_masked||'Not installed';
    if($('licenceCustomer'))$('licenceCustomer').textContent=l.customer||l.product_name||'—';
    if($('licenceVerifiedUntil'))$('licenceVerifiedUntil').textContent=l.mode==='development'?(l.test_licensed?`Test verified until ${fmtLicenceDate(l.valid_until)}`:'Not enforced'):`Online until ${fmtLicenceDate(l.valid_until)}`;
    if($('licenceGraceUntil'))$('licenceGraceUntil').textContent=l.mode==='development'?(l.test_licensed?`Test grace until ${fmtLicenceDate(l.grace_until)}`:'Development configuration'):`Offline grace until ${fmtLicenceDate(l.grace_until)}`;
    if(badge){badge.textContent=l.status||'Unknown';badge.classList.remove('active','warn','error');badge.classList.add(l.licensed?(l.status==='Offline grace'?'warn':'active'):'error');}
    if(card){card.classList.toggle('licence-active',!!l.licensed);card.classList.toggle('licence-invalid',l.mode==='whmcs'&&!l.licensed);}
    const whmcs=l.mode==='whmcs',hasKey=!!l.license_key_masked;
    // Development mode disables enforcement only.  Keep activation available so a
    // real WHMCS licence can be tested safely before switching the controller live.
    if($('licenceKey'))$('licenceKey').disabled=false;
    if($('activateLicence'))$('activateLicence').disabled=false;
    if($('checkLicence'))$('checkLicence').disabled=!hasKey;
    if($('clearLocalLicence'))$('clearLocalLicence').disabled=!hasKey;
    if($('licenceHelp')){
      if(!whmcs)$('licenceHelp').innerHTML=l.test_licensed?'<strong>WHMCS test activation passed:</strong> this licence is bound to this controller, but enforcement is still disabled while we complete testing.':'<strong>Development mode:</strong> the display remains unlocked, but you can enter a real PMS licence above to test WHMCS activation and device binding.';
      else if(!l.endpoint_configured||(!l.public_key_configured&&!l.public_key_url_configured))$('licenceHelp').innerHTML=`<strong>Commercial licensing needs configuration:</strong> ${!l.endpoint_configured?'WHMCS addon endpoint is missing. ':''}${(!l.public_key_configured&&!l.public_key_url_configured)?'Signing public key source is missing.':''}`;
      else if(!l.public_key_configured)$('licenceHelp').innerHTML="<strong>Ready to activate:</strong> the signing public key will be downloaded automatically from the WHMCS addon over HTTPS on the first licence check.";
      else $('licenceHelp').innerHTML="<strong>Device locking:</strong> one WHMCS licence is bound to this controller's Device ID. Use WHMCS Reissue before moving the licence to replacement hardware.";
    }
    const showBanner=whmcs&&!l.licensed;
    if(banner){banner.classList.toggle('hidden',!showBanner);$('licenseBannerTitle').textContent=l.status||'Licence required';$('licenseBannerText').textContent=l.message||'Activate Pi Matrix Signage under Display setup.';}
  }
  async function loadLicence(){try{state.license=await api('/api/license');renderLicence();return state.license;}catch(e){toast(e.message,true);return null;}}
  async function activateLicence(){const key=String($('licenceKey')?.value||'').trim();if(!key){toast('Enter a licence key',true);return;}try{state.license=await api('/api/license/activate',{method:'POST',body:{license_key:key}});$('licenceKey').value='';renderLicence();toast('Licence activated');}catch(e){await loadLicence();toast(e.message,true);}}
  async function checkLicence(){try{state.license=await api('/api/license/check',{method:'POST',body:{}});renderLicence();toast('Licence checked');}catch(e){await loadLicence();toast(e.message,true);}}
  async function clearLocalLicence(){if(!confirm('Clear the licence key and signed entitlement stored on this Pi?\n\nThis does not reissue the licence in WHMCS.'))return;try{state.license=await api('/api/license/deactivate-local',{method:'POST',body:{}});renderLicence();toast('Local licence cleared');}catch(e){toast(e.message,true);}}
  function openLicenceSetup(){const tab=document.querySelector('[data-tab="setup"]');if(tab){tab.click();setTimeout(()=>$('licenceCard')?.scrollIntoView({behavior:'smooth',block:'start'}),60);}}

  // Settings
  function populateSettings(){const s=state.settings;if(!s)return;$('panelWidth').value=s.panel_width;$('panelHeight').value=s.panel_height;$('panelScan').value=s.panel_scan||'1/16';$('panelsAcross').value=s.panels_across;$('panelsDown').value=s.panels_down;$('displayRotation').value=s.display_rotation;$('brightness').value=s.brightness;$('brightnessValue').textContent=`${s.brightness}%`;$('frameRate').value=s.frame_rate;$('colorOrder').value=s.color_order;$('timezone').value=s.timezone;$('ddpHost').value=s.ddp_host;$('ddpPort').value=s.ddp_port;$('ddpOffset').value=s.ddp_offset;$('defaultMessage').value=s.default_message_id||'';updateLayoutSummary();}
  function updateLayoutSummary(){const pw=+$('panelWidth').value||0,ph=+$('panelHeight').value||0,ac=+$('panelsAcross').value||0,dn=+$('panelsDown').value||0;const w=pw*ac,h=ph*dn;$('layoutSummary').textContent=`${ac} × ${dn} panels = ${w} × ${h} pixels (${(w*h*3).toLocaleString()} RGB channels)`;}
  async function saveSettings(){try{const body={panel_width:+$('panelWidth').value,panel_height:+$('panelHeight').value,panel_scan:$('panelScan').value,panels_across:+$('panelsAcross').value,panels_down:+$('panelsDown').value,display_rotation:+$('displayRotation').value,brightness:+$('brightness').value,frame_rate:+$('frameRate').value,color_order:$('colorOrder').value,timezone:$('timezone').value.trim(),ddp_host:$('ddpHost').value.trim(),ddp_port:+$('ddpPort').value,ddp_offset:+$('ddpOffset').value,default_message_id:$('defaultMessage').value?+$('defaultMessage').value:null};state.settings=await api('/api/settings',{method:'PUT',body});populateSettings();await loadFppSetup();toast('Display settings saved');}catch(e){toast(e.message,true);}}
  async function loadFppSetup(){try{const f=await api('/api/fpp-setup');$('fppSetup').innerHTML=`<div class="fpp-value"><span>Panel arrangement</span><strong>${f.panels_across} across × ${f.panels_down} down</strong></div><div class="fpp-value"><span>Panel pixel size</span><strong>${esc(f.panel_size)} · ${esc(f.panel_scan)} scan</strong></div><div class="fpp-value"><span>Total canvas</span><strong>${esc(f.display_size)}</strong></div><div class="fpp-value"><span>FPP channel range</span><strong>${f.start_channel} – ${(f.start_channel+f.channel_count-1).toLocaleString()}</strong></div><div class="fpp-value"><span>Channel count</span><strong>${f.channel_count.toLocaleString()}</strong></div><div class="fpp-value"><span>DDP destination</span><strong>${esc(state.settings?.ddp_host||'127.0.0.1')}:${f.ddp_port}</strong></div><ol class="fpp-notes">${f.notes.map(n=>`<li>${esc(n)}</li>`).join('')}</ol>`;}catch(e){$('fppSetup').innerHTML=`<p class="muted">${esc(e.message)}</p>`;}}

  // GPIO / physical controls
  function gpioRow(id){return document.querySelector(`[data-gpio-input="${id}"]`);}
  function syncGpioEmergencyFields(){for(const row of $$('.gpio-input-row')){const action=row.querySelector('[data-gpio-field="action"]')?.value||'none';const field=row.querySelector('.gpio-emergency-behaviour');if(field)field.style.display=action==='emergency'?'flex':'none';}}
  function renderGpioControls(data){if(!data)return;state.gpioStatus=data;$('gpioControlsEnabled').checked=!!data.enabled;$('gpioBackendStatus').textContent=data.backend==='unavailable'?'libgpiod/gpiomon is unavailable on this Pi':`${data.profile||'GPIO'} · ${data.backend||'monitor'}`;for(const item of data.inputs||[]){const row=gpioRow(item.id);if(!row)continue;for(const field of row.querySelectorAll('[data-gpio-field]')){const key=field.dataset.gpioField;if(key==='enabled')field.checked=!!item.enabled;else if(item[key]!=null)field.value=item[key];}const badge=row.querySelector(`[data-gpio-state="${item.id}"]`);if(badge){badge.className='gpio-state';if(!data.enabled||!item.enabled){badge.textContent='Disabled';}else if(item.error){badge.textContent=item.error;badge.classList.add('error');}else if(item.active){badge.textContent='ACTIVE';badge.classList.add('active');}else if(item.available){badge.textContent=item.level==null?'Ready':`Ready · level ${item.level}`;badge.classList.add('ready');}else{badge.textContent='Starting…';}}}syncGpioEmergencyFields();}
  async function loadGpioControls(syncForm=false){if(!can('display_setup')||!$('gpioInputGrid'))return;try{const data=await api('/api/gpio-controls');if(syncForm||!state.gpioStatus)renderGpioControls(data);else{state.gpioStatus=data;for(const item of data.inputs||[]){const row=gpioRow(item.id),badge=row?.querySelector(`[data-gpio-state="${item.id}"]`);if(!badge)continue;badge.className='gpio-state';if(!data.enabled||!item.enabled)badge.textContent='Disabled';else if(item.error){badge.textContent=item.error;badge.classList.add('error');}else if(item.active){badge.textContent='ACTIVE';badge.classList.add('active');}else if(item.available){badge.textContent=item.level==null?'Ready':`Ready · level ${item.level}`;badge.classList.add('ready');}else badge.textContent='Starting…';}$('gpioBackendStatus').textContent=data.backend==='unavailable'?'libgpiod/gpiomon is unavailable on this Pi':`${data.profile||'GPIO'} · ${data.backend||'monitor'}`;}}catch(e){if(syncForm)toast(e.message,true);}}
  function gpioPayload(){return {enabled:$('gpioControlsEnabled').checked,inputs:$$('.gpio-input-row').map(row=>{const get=k=>row.querySelector(`[data-gpio-field="${k}"]`);return{id:row.dataset.gpioInput,enabled:get('enabled').checked,action:get('action').value,contact_type:get('contact_type').value,emergency_behaviour:get('emergency_behaviour').value,debounce_ms:+get('debounce_ms').value||100};})};}
  async function saveGpioControls(){try{const data=await api('/api/gpio-controls',{method:'PUT',body:gpioPayload()});renderGpioControls(data);toast('Physical controls saved');setTimeout(()=>loadGpioControls(false),900);}catch(e){toast(e.message,true);}}
  async function testGpioAction(id){try{await api(`/api/gpio-controls/${encodeURIComponent(id)}/test`,{method:'POST',body:{}});toast(`Input ${id} action tested`);setTimeout(()=>loadGpioControls(false),150);}catch(e){toast(e.message,true);}}

  function formatBytes(value){
    const n=Number(value)||0;if(n<=0)return '0 MB';const units=['B','KB','MB','GB','TB'];let v=n,i=0;while(v>=1024&&i<units.length-1){v/=1024;i++;}return `${v>=100||i<2?v.toFixed(0):v.toFixed(1)} ${units[i]}`;
  }
  function formatUptime(seconds){
    let s=Math.max(0,Math.floor(Number(seconds)||0)),d=Math.floor(s/86400);s%=86400;const h=Math.floor(s/3600),m=Math.floor((s%3600)/60);return d?`${d}d ${h}h ${m}m`:`${h}h ${m}m`;
  }
  function setupTabVisible(){return document.querySelector('.tab.active')?.dataset.tab==='setup';}
  function renderDiagnostics(d,syncControls=false){
    if(!d||d.error){$('diagOverall').textContent=d?.error||'Diagnostics unavailable';$('diagOverall').className='health-badge error';return;}
    state.lastDiagnostics=d;const overall=d.overall||'warn';$('diagOverall').textContent=overall==='ok'?'All systems healthy':overall==='error'?'Attention required':'Warnings';$('diagOverall').className=`health-badge ${overall}`;
    $('diagChecks').innerHTML=(d.checks||[]).map(c=>`<div class="diagnostic-check ${esc(c.level||'warn')}"><i></i><div><strong>${esc(c.name)}</strong><small>${esc(c.message)}</small></div></div>`).join('');
    const sys=d.system||{},ren=d.renderer||{},svc=d.services||{},widgets=d.widgets||{};const mem=sys.memory||{},disk=sys.disk||{};
    $('diagCpu').textContent=sys.cpu_percent==null?'—':`${Number(sys.cpu_percent).toFixed(1)}%`;$('diagLoad').textContent=`Load ${(sys.load||[]).map(v=>Number(v).toFixed(2)).join(' / ')||'—'}`;
    $('diagTemp').textContent=sys.temperature_c==null?'Unavailable':`${Number(sys.temperature_c).toFixed(1)}°C`;
    $('diagMemory').textContent=mem.percent==null?'—':`${Number(mem.percent).toFixed(1)}%`;$('diagProcessMemory').textContent=`App ${formatBytes(sys.process_rss_bytes)}`;
    $('diagDisk').textContent=formatBytes(disk.free_bytes);$('diagDiskUsed').textContent=`${disk.percent==null?'—':Number(disk.percent).toFixed(1)+'%'} used of ${formatBytes(disk.total_bytes)}`;
    $('diagUptime').textContent=formatUptime(sys.uptime_seconds);$('diagIps').textContent=`IP ${(sys.ips||[]).join(' · ')||'not assigned'}`;
    $('diagRenderer').textContent=`${Number(ren.actual_fps||0).toFixed(1)} fps`;$('diagRendererDetail').textContent=`${Number(ren.frames_sent||0).toLocaleString()} frames · ${Number(ren.dropped_frames||0).toLocaleString()} dropped · ${Number(ren.renderer_restarts||0)} restarts`;
    $('diagFppd').textContent=String(svc.fppd||'unknown');$('diagDdp').textContent=svc.ddp_listening?`DDP UDP ${svc.ddp_port} listening`:`No DDP listener on UDP ${svc.ddp_port}`;
    $('diagInternet').textContent=sys.internet?.ok?'Connected':'Unavailable';$('diagWidgets').textContent=`${widgets.count||0} live · ${widgets.errors||0} errors · ${widgets.fetching||0} fetching`;
    $('diagCollected').textContent=d.collected_at?`Last checked ${new Date(d.collected_at*1000).toLocaleTimeString()}`:'Not checked yet';
    const recovery=d.recovery||{};
    if(syncControls||!$('autoRecoveryEnabled').dataset.loaded){$('autoRecoveryEnabled').checked=!!recovery.enabled;$('autoRecoverRenderer').checked=!!recovery.renderer;$('autoRecoverFppd').checked=!!recovery.fppd;$('rendererStallSeconds').value=recovery.renderer_stall_seconds??5;$('recoveryCooldownSeconds').value=recovery.cooldown_seconds??60;$('autoRecoveryEnabled').dataset.loaded='1';}
    const events=recovery.events||[];$('recoveryHistory').innerHTML=events.length?events.map(e=>`<div class="recovery-row"><span>${esc(String(e.created_at||'').replace('T',' '))}</span><strong>${esc(e.action||e.event_type||'Recovery')}</strong><span class="result ${esc(e.result||'')}">${esc(e.result||'')}</span><span class="details" title="${esc(e.details||'')}">${esc(e.details||'')}</span></div>`).join(''):'<div class="recovery-empty">No automatic or manual recovery actions have been needed.</div>';
  }
  async function loadDiagnostics(syncControls=false){
    if(!can('display_setup')||state.diagnosticsBusy)return;state.diagnosticsBusy=true;try{renderDiagnostics(await api('/api/diagnostics'),syncControls);}catch(e){if(setupTabVisible())toast(e.message,true);$('diagOverall').textContent='Diagnostics unavailable';$('diagOverall').className='health-badge error';}finally{state.diagnosticsBusy=false;}
  }
  async function saveRecoverySettings(){
    try{const body={auto_recovery_enabled:$('autoRecoveryEnabled').checked,auto_recover_renderer:$('autoRecoverRenderer').checked,auto_recover_fppd:$('autoRecoverFppd').checked,renderer_stall_seconds:+$('rendererStallSeconds').value,recovery_cooldown_seconds:+$('recoveryCooldownSeconds').value};state.settings=await api('/api/settings',{method:'PUT',body});toast('Recovery settings saved');await loadDiagnostics(true);}catch(e){toast(e.message,true);}
  }
  async function diagnosticsAction(action,confirmText=''){
    if(confirmText&&!confirm(confirmText))return;try{const r=await api('/api/diagnostics/action',{method:'POST',body:{action}});toast(r.message||'Action completed');setTimeout(()=>loadDiagnostics(true),900);}catch(e){toast(e.message,true);}
  }

  async function shutdownPi(){
    if(!confirm('Shut down the Raspberry Pi now? The display and web interface will go offline.'))return;
    if(!confirm('Confirm safe shutdown. Wait for the Pi activity LED to stop before removing power.'))return;
    try{const r=await api('/api/shutdown',{method:'POST',body:{confirm:'SHUTDOWN'}});toast(r.message||'Raspberry Pi is shutting down');$('shutdownPi').disabled=true;$('statusPill').querySelector('span:last-child').textContent='Shutting down…';}catch(e){toast(e.message,true);}
  }

  // ----------------------- Browser upgrades -----------------------
  let upgradePollTimer=null;
  function setUpgradeProgress(stateName){
    const wrap=$('upgradeProgress'), bar=$('upgradeProgressBar');
    const active=['uploading','queued','validating','installing','restarting'].includes(stateName);
    wrap.classList.toggle('hidden',!active);
    const pct={uploading:12,queued:22,validating:38,installing:64,restarting:86,success:100,failed:100}[stateName]||0;
    bar.style.width=`${pct}%`;bar.classList.toggle('failed',stateName==='failed');
  }
  function shortBackup(value){
    if(!value)return '—';const parts=String(value).split('/');return parts[parts.length-1]||value;
  }
  function renderUpgradeStatus(data){
    const status=data?.status||{};
    $('upgradeCurrentVersion').textContent=`v${data?.current_version||'—'}`;
    $('upgradeHelperNotice').classList.toggle('hidden',!!data?.helper_ready);
    const enabled=!!data?.helper_ready;
    $('upgradeFile').disabled=!enabled;
    $('upgradeDropZone').classList.toggle('disabled',!enabled);
    const stateName=String(status.state||'ready').toLowerCase();
    $('upgradeState').textContent=stateName==='ready'?'Ready':stateName.charAt(0).toUpperCase()+stateName.slice(1);
    $('upgradeFrom').textContent=status.from_version?`v${status.from_version}`:'—';
    $('upgradeTo').textContent=status.to_version?`v${status.to_version}`:'—';
    $('upgradeBackup').textContent=shortBackup(status.backup);
    $('upgradeMessage').textContent=status.message||(enabled?'Drop a newer Pi Matrix Signage ZIP above when you are ready to upgrade.':'The privileged upgrade helper must be installed before browser upgrades can run.');
    $('upgradeMessage').classList.toggle('warn',stateName==='failed');
    $('upgradeCompleted').textContent=status.completed_at?`Completed: ${status.completed_at}${status.rolled_back?' · previous version restored automatically':''}`:'';
    setUpgradeProgress(stateName);
    return {stateName,current:data?.current_version,target:status.to_version};
  }
  async function loadUpgradeStatus(quiet=false){
    try{return renderUpgradeStatus(await api('/api/upgrade/status'));}
    catch(e){if(!quiet)toast(e.message,true);throw e;}
  }
  function releaseVersionFromFilename(name){
    const m=String(name||'').match(/(?:PiMatrixSignage[-_ ]*)?v?(\d+\.\d+\.\d+(?:[-+][A-Za-z0-9._-]+)?)/i);
    return m?m[1]:null;
  }
  function showUpgradeRestarting(message='The web interface is temporarily offline while the service restarts. This is expected.'){
    $('upgradeState').textContent='Restarting…';$('upgradeMessage').textContent=message;$('upgradeMessage').classList.remove('warn');setUpgradeProgress('restarting');
  }
  async function probeUpgradeHealth(){
    // /health deliberately requires no login/session.  It is therefore the
    // authoritative signal that the *new* service is listening after an
    // upgrade, even while the authenticated application session is settling.
    const controller=new AbortController();
    const timer=setTimeout(()=>controller.abort(),2500);
    try{
      const r=await fetch(`/health?upgrade_probe=${Date.now()}`,{cache:'no-store',credentials:'same-origin',signal:controller.signal,headers:{'Cache-Control':'no-cache'}});
      if(!r.ok)return null;
      const d=await r.json();
      return d?.ok?String(d.version||''):null;
    }catch(_){return null;}finally{clearTimeout(timer);}
  }
  function forceReloadAfterUpgrade(version){
    clearTimeout(upgradePollTimer);upgradePollTimer=null;
    const installed=version||'new version';
    $('upgradeSelected').textContent=`v${installed} installed successfully. Loading the updated interface…`;
    $('upgradeState').textContent='Success';$('upgradeMessage').textContent=`Upgrade to v${installed} completed successfully.`;$('upgradeMessage').classList.remove('warn');setUpgradeProgress('success');
    // Change the page URL as well as using versioned static assets.  This
    // forces the browser/proxy to request a fresh HTML document after the
    // service restart rather than reusing the pre-upgrade page from cache.
    setTimeout(()=>{
      const u=new URL(window.location.href);u.searchParams.set('upgraded',`${installed}-${Date.now()}`);window.location.replace(u.toString());
    },700);
  }
  function pollUpgrade(targetVersion=null,{alreadyDisconnected=false}={}){
    clearTimeout(upgradePollTimer);
    let disconnected=!!alreadyDisconnected,seenUpgrade=false,lastHealthVersion=null;
    const started=Date.now();
    const poll=async()=>{
      // Check the session-free health endpoint first.  The moment the target
      // version is serving HTTP, the upgrade has succeeded from the browser's
      // point of view and we can load the new UI without waiting for an
      // authenticated status request.
      const healthVersion=await probeUpgradeHealth();
      if(healthVersion){
        lastHealthVersion=healthVersion;
        if(targetVersion&&healthVersion===String(targetVersion)){forceReloadAfterUpgrade(healthVersion);return;}
      }else{
        disconnected=true;
        showUpgradeRestarting('Pi Matrix Signage is restarting. Waiting for the updated service to come back online…');
      }

      try{
        const result=await loadUpgradeStatus(true);
        if(result.target)targetVersion=result.target;
        if(['queued','validating','installing','restarting','success','failed'].includes(result.stateName))seenUpgrade=true;
        if(disconnected&&healthVersion){toast('Signage service is back online');disconnected=false;}
        // Re-check using the version returned by status in case targetVersion
        // was not known until this request (for example after a transport
        // disconnect during upload).
        if(healthVersion&&targetVersion&&healthVersion===String(targetVersion)){forceReloadAfterUpgrade(healthVersion);return;}
        if(result.stateName==='success'&&result.current&&(result.current===targetVersion||!targetVersion)){
          forceReloadAfterUpgrade(result.current);return;
        }
        if(result.stateName==='failed'){
          clearTimeout(upgradePollTimer);upgradePollTimer=null;return;
        }
      }catch(_){
        // An authenticated status request can legitimately fail while the
        // application restarts.  Do not turn that into a user-visible error;
        // /health above is the recovery path.
        if(!healthVersion){disconnected=true;showUpgradeRestarting('The web interface is temporarily offline while Pi Matrix Signage restarts. Waiting for it to return…');}
      }
      if(Date.now()-started>120000){
        clearTimeout(upgradePollTimer);upgradePollTimer=null;
        $('upgradeState').textContent='Check status';
        $('upgradeMessage').textContent=lastHealthVersion?`Pi Matrix Signage is online as v${lastHealthVersion}, but the requested target could not be confirmed automatically. Reloading the interface now…`:(seenUpgrade?'The updater is taking longer than expected. The upgrade may still be running; reload to check the installed version.':'Could not confirm that the upgrade started. Reload to check the installed version.');
        // Even in the unusual timeout case, if a healthy service is present,
        // load it instead of leaving the user stranded on the old page.
        if(lastHealthVersion){setTimeout(()=>{const u=new URL(window.location.href);u.searchParams.set('upgrade_check',Date.now());window.location.replace(u.toString());},1000);}
        return;
      }
      upgradePollTimer=setTimeout(poll,1200);
    };
    upgradePollTimer=setTimeout(poll,alreadyDisconnected?700:500);
  }
  async function startUpgrade(file){
    if(!file)return;
    if(!file.name.toLowerCase().endsWith('.zip')){toast('Please choose a Pi Matrix Signage ZIP release',true);return;}
    $('upgradeSelected').textContent=`Uploading ${file.name} · ${(file.size/1024/1024).toFixed(2)} MB`;
    $('upgradeState').textContent='Uploading';$('upgradeMessage').textContent='Uploading and validating release…';setUpgradeProgress('uploading');
    const form=new FormData();form.append('file',file,file.name);
    try{
      const result=await api('/api/upgrade',{method:'POST',body:form});
      $('upgradeSelected').textContent=`Validated v${result.version} · SHA-256 ${result.sha256.slice(0,12)}…`;
      $('upgradeState').textContent='Queued';$('upgradeTo').textContent=`v${result.version}`;$('upgradeMessage').textContent='Update accepted. The service will restart automatically; keep this page open.';setUpgradeProgress('queued');
      pollUpgrade(result.version);
    }catch(e){
      // If the service restarts before the upload request can flush its final
      // JSON response, fetch() reports a network error even though the updater
      // was successfully queued.  Treat only transport errors this way; real
      // HTTP validation/permission errors still show as failures.
      if(!e.status){
        const guessed=releaseVersionFromFilename(file.name);
        if(guessed)$('upgradeTo').textContent=`v${guessed}`;
        $('upgradeSelected').textContent=`${file.name} uploaded. Verifying the restarted service…`;
        showUpgradeRestarting('The upload connection closed while the service restarted. Verifying the installed version now…');
        pollUpgrade(guessed,{alreadyDisconnected:true});
      }else{
        $('upgradeState').textContent='Failed';$('upgradeMessage').textContent=e.message;setUpgradeProgress('failed');toast(e.message,true);
      }
    }finally{$('upgradeFile').value='';}
  }

  function initDesignerPanelPreferences(){
    const panels=[['.designer-background','sceneAppearance'],['.scene-playback','sceneTiming'],['.timeline-panel','timeline'],['.designer-help','designerHelp'],['.sidebar-group:nth-of-type(1)','zones'],['.sidebar-group:nth-of-type(2)','components'],['.inspector-layout','layerLayout'],['.inspector-motion','layerMotion'],['.inspector-transitions','layerTransitions'],['.font-manager','fontManager']];
    for(const [selector,key] of panels){const el=document.querySelector(selector);if(!el)continue;const saved=localStorage.getItem(`pimatrixPanel:${key}`);if(saved!==null)el.open=saved==='1';el.addEventListener('toggle',()=>localStorage.setItem(`pimatrixPanel:${key}`,el.open?'1':'0'));}
  }


  async function refreshStatus(){try{const s=await api('/api/status');const p=$('statusPill');p.classList.toggle('ok',s.running&&!s.last_error&&!s.emergency);p.classList.toggle('error',!!s.last_error||!!s.emergency);p.querySelector('span:last-child').textContent=s.emergency?'EMERGENCY':s.last_error?'Output error':'Running';state.displayWidth=+s.width||0;state.displayHeight=+s.height||0;$('displaySize').textContent=`${s.width} × ${s.height} pixels`;$('framesSent').textContent=Number(s.frames_sent).toLocaleString();$('lastError').textContent=s.last_error||'None';$('activeSource').textContent=s.transition?`Exiting message #${s.transition.outgoing_message_id} · ${Number(s.transition.remaining||0).toFixed(1)}s`:s.emergency?`EMERGENCY · message #${s.emergency.id}`:s.manual?`Manual ${s.manual.type}${s.manual.id?' #'+s.manual.id:''}`:s.active?`${s.active.source} · ${s.active.type} #${s.active.id}`:'Blank';$('outputTarget').textContent=state.settings?`${state.settings.ddp_host}:${state.settings.ddp_port} · ${s.brightness?.effective??state.settings.brightness}%`:'DDP';if($('emergencyPanel'))$('emergencyPanel').classList.toggle('active',!!s.emergency);$('activateEmergency').disabled=!!s.emergency||!state.settings?.emergency_message_id;$('clearEmergency').disabled=!s.emergency;if(can('schedules')&&$('page-schedules').classList.contains('active')&&Date.now()-(state._lastRuleRefresh||0)>4000){state._lastRuleRefresh=Date.now();api('/api/conditional-rules').then(v=>{state.conditionalRules=v;renderConditionalRuleList();if(state.selectedConditionalRule)selectConditionalRule(state.selectedConditionalRule);}).catch(()=>{});}}catch(e){const p=$('statusPill');p.classList.add('error');p.querySelector('span:last-child').textContent='Disconnected';}}
    function setLivePreviewEnabled(on){state.livePreviewEnabled=!!on;localStorage.setItem('pimatrixLivePreview',on?'1':'0');$('livePreviewEnabled').checked=!!on;$('livePreviewOff').classList.toggle('hidden',!!on);$('livePreview').classList.toggle('hidden',!on);if(on)scheduleLivePreview(0);else{clearTimeout(state.livePreviewTimer);state.livePreviewTimer=null;}}
  function scheduleLivePreview(delay=null){clearTimeout(state.livePreviewTimer);if(!state.livePreviewEnabled)return;const fps=clamp(+$('livePreviewRate').value||8,1,20),ms=delay===null?Math.round(1000/fps):delay;state.livePreviewTimer=setTimeout(async()=>{const dashboard=$('page-dashboard').classList.contains('active');if(!dashboard||document.hidden){scheduleLivePreview(300);return;}await refreshLivePreview(false);scheduleLivePreview();},ms);}
  async function refreshLivePreview(force=true){if(state.livePreviewBusy)return;if(!state.livePreviewEnabled&&!force)return;state.livePreviewBusy=true;try{const r=await fetch(`/api/preview.png?scale=6&t=${Date.now()}`,{cache:'no-store'});if(!r.ok)throw new Error('Preview failed');const blob=await r.blob(),url=URL.createObjectURL(blob),pre=new Image();await new Promise((resolve,reject)=>{pre.onload=resolve;pre.onerror=reject;pre.src=url;});const im=$('livePreview'),old=state.livePreviewObjectUrl;im.onload=()=>refreshPreviewSimulation();im.src=url;state.livePreviewObjectUrl=url;if(old)setTimeout(()=>URL.revokeObjectURL(old),500);}catch(_){/* status poll reports connection errors */}finally{state.livePreviewBusy=false;}}

  // Events – messages
  $('newMessage').addEventListener('click',blankMessage);$('backToMessages').addEventListener('click',()=>showMessageLibrary(true));$('saveMessage').addEventListener('click',()=>saveMessage(false));$('showEditedMessage').addEventListener('click',()=>saveMessage(true));$('duplicateMessage').addEventListener('click',duplicateMessage);$('deleteMessage').addEventListener('click',deleteMessage);$('messageHistoryButton').addEventListener('click',()=>{$('messageHistoryPanel').open=!$('messageHistoryPanel').open;});$('messageHistoryPanel').addEventListener('toggle',()=>{if($('messageHistoryPanel').open)loadMessageVersions();});$('exportMessage').addEventListener('click',()=>downloadPortable('message',+$('messageId').value));$('importMessageFile').addEventListener('change',async()=>{const f=$('importMessageFile').files?.[0];if(f)await importPortableFile(f,'message');$('importMessageFile').value='';});$('importMessageLibraryFile').addEventListener('change',async()=>{const f=$('importMessageLibraryFile').files?.[0];if(f)await importPortableFile(f,'message');$('importMessageLibraryFile').value='';});
  $('messageSearch').addEventListener('input',renderMessageList);
  ['msgName','msgText','msgFont','msgFontSize','msgRenderMode','msgPixelScale','msgPixelBold','msgLetterSpacing','msgAutoFit','msgTextColor','msgBgColor','msgOutlineColor','msgOutlineWidth','msgDirection','msgSpeed','msgAlign','msgVAlign','msgImage','msgImageMode','msgImageScale','msgPadding'].forEach(id=>$(id).addEventListener('input',scheduleEditorPreview));
  $('msgSpeed').addEventListener('input',()=>{$('speedValue').textContent=`${$('msgSpeed').value} px/s`;});
  $$('.quick-token-bar button').forEach(b=>b.addEventListener('click',()=>{const t=$('msgText'),start=t.selectionStart,end=t.selectionEnd;t.value=t.value.slice(0,start)+b.dataset.token+t.value.slice(end);t.focus();t.selectionStart=t.selectionEnd=start+b.dataset.token.length;scheduleEditorPreview();}));
  $$('.designer-token-bar button').forEach(b=>b.addEventListener('click',()=>{const t=$('layerText'),start=t.selectionStart,end=t.selectionEnd;t.value=t.value.slice(0,start)+b.dataset.token+t.value.slice(end);t.focus();t.selectionStart=t.selectionEnd=start+b.dataset.token.length;updateSelectedFromControls();}));
  $('imageUpload').addEventListener('change',()=>upload('image',$('imageUpload')));$('designerImageUpload').addEventListener('change',()=>upload('image',$('designerImageUpload')));$('designerVideoUpload').addEventListener('change',()=>upload('video',$('designerVideoUpload')));$('designerShaderUpload').addEventListener('change',()=>upload('shader',$('designerShaderUpload')));$('fontUpload').addEventListener('change',()=>upload('font',$('fontUpload')));$('backgroundShaderUpload').addEventListener('change',()=>uploadBackgroundShader($('backgroundShaderUpload')));
  $$('.template-button').forEach(b=>b.addEventListener('click',()=>applyTemplate(b.dataset.template)));$('applyTemplateLibrary').addEventListener('click',()=>{const kind=$('templateLibrary').value;if(kind)applyTemplate(kind);});$('addTextLayer').addEventListener('click',()=>addLayer('text'));$('addImageLayer').addEventListener('click',()=>addLayer('image'));$('addVideoLayer').addEventListener('click',()=>addLayer('video'));$('addShaderLayer').addEventListener('click',()=>addLayer('shader'));$('addWidgetLayer').addEventListener('click',()=>addLayer('widget'));$('addIconLayer').addEventListener('click',()=>addLayer('icon'));$('addShapeLayer').addEventListener('click',()=>addLayer('shape'));$('deleteLayer').addEventListener('click',deleteLayer);$('duplicateLayer').addEventListener('click',duplicateLayer);$('layerUp').addEventListener('click',()=>moveLayer(1));$('layerDown').addEventListener('click',()=>moveLayer(-1));$('undoDesigner').addEventListener('click',undoDesigner);$('redoDesigner').addEventListener('click',redoDesigner);$('groupLayers').addEventListener('click',groupSelected);$('ungroupLayers').addEventListener('click',ungroupSelected);$('copyLayers').addEventListener('click',copySelectedLayers);$('pasteLayers').addEventListener('click',pasteCopiedLayers);$('showShortcuts').addEventListener('click',()=>showShortcutHelp(true));$('closeShortcuts').addEventListener('click',()=>showShortcutHelp(false));$('shortcutModal').addEventListener('click',ev=>{if(ev.target===$('shortcutModal'))showShortcutHelp(false);});$$('[data-align]').forEach(b=>b.addEventListener('click',()=>alignSelection(b.dataset.align)));$('addZone').addEventListener('click',addZone);$('deleteZone').addEventListener('click',deleteZone);$('assignZone').addEventListener('click',assignSelectionToZone);$('clearZone').addEventListener('click',clearSelectionZone);$('saveComponent').addEventListener('click',saveSelectionAsComponent);$('insertComponent').addEventListener('click',insertComponent);$('deleteComponent').addEventListener('click',deleteComponent);$('exportComponent').addEventListener('click',()=>downloadPortable('component',+$('componentPicker').value));$('importComponentFile').addEventListener('change',async()=>{const f=$('importComponentFile').files?.[0];if(f){await importPortableFile(f,'component');state.components=await api('/api/components');populateComponents();}$('importComponentFile').value='';});
  ['sceneBgMode','sceneBgColor1','sceneBgColor2'].forEach(id=>$(id).addEventListener('input',()=>{if(!state.scene)return;beginHistoryBurst();const bg=state.scene.background||(state.scene.background={});bg.mode=$('sceneBgMode').value;bg.color1=$('sceneBgColor1').value;bg.color2=$('sceneBgColor2').value;syncSceneBackgroundControls();scheduleEditorPreview();}));
  ['sceneBgShader','sceneBgShaderFps','sceneBgShaderTimeScale','sceneBgShaderQuality'].forEach(id=>$(id).addEventListener('input',()=>{if(!state.scene)return;beginHistoryBurst();const bg=state.scene.background||(state.scene.background={});const next=$('sceneBgShader').value;if(bg.shader_id!==next){bg.shader_id=next;bg.shader_params=shaderDefaults(shaderAsset(next));}bg.shader_fps=clamp(+$('sceneBgShaderFps').value||15,1,30);bg.shader_time_scale=clamp(+$('sceneBgShaderTimeScale').value||1,-10,10);bg.shader_quality=$('sceneBgShaderQuality').value||'auto';renderBackgroundShaderParameterFields();scheduleEditorPreview();}));
  ['sceneBgShaderLiveWeather','sceneBgShaderWeatherLat','sceneBgShaderWeatherLon','sceneBgShaderWeatherRefresh'].forEach(id=>$(id).addEventListener('input',()=>{if(!state.scene)return;beginHistoryBurst();const bg=state.scene.background||(state.scene.background={});bg.shader_live_weather=$('sceneBgShaderLiveWeather').checked;bg.shader_weather_lat=+$('sceneBgShaderWeatherLat').value||0;bg.shader_weather_lon=+$('sceneBgShaderWeatherLon').value||0;bg.shader_weather_refresh=clamp(+$('sceneBgShaderWeatherRefresh').value||600,60,3600);scheduleEditorPreview();}));
  ['sceneDuration','sceneTransitionIn','sceneTransitionInDuration','sceneTransitionOut','sceneTransitionOutDuration'].forEach(id=>$(id).addEventListener('input',()=>{if(!state.scene)return;beginHistoryBurst();state.scene.duration=clamp(+$('sceneDuration').value||10,.25,3600);state.scene.transition_in=$('sceneTransitionIn').value;state.scene.transition_in_duration=clamp(+$('sceneTransitionInDuration').value||.5,.05,30);state.scene.transition_out=$('sceneTransitionOut').value;state.scene.transition_out_duration=clamp(+$('sceneTransitionOutDuration').value||.5,.05,30);updatePreviewTimelineRange();scheduleEditorPreview();}));
  ['layerName','layerZone','layerEnabled','layerX','layerY','layerW','layerH','layerOpacity','layerRotation','layerDelay','layerAnimation','layerSpeed','layerEffectPeriod','layerBlinkDuty','layerEntranceEffect','layerEntranceDuration','layerExitEffect','layerExitAfter','layerExitDuration','layerText','layerFont','layerFontSize','layerRenderMode','layerPixelScale','layerPixelBold','layerLetterSpacing','layerAutoFit','layerWrap','layerOverflow','layerTextTransform','layerTypewriterSpeed','layerColorEffect','layerColor2','layerColorSpeed','layerColorPalette','layerGlow','layerGlowColor','layerTextColor','layerOutlineColor','layerOutlineWidth','layerPadding','layerAlign','layerVAlign','layerLineSpacing','layerShadowColor','layerShadowX','layerShadowY','layerImage','layerImageFit','layerMediaSpeed','layerMediaLoop','layerVideo','layerVideoFit','layerVideoSpeed','layerVideoLoop','layerShader','layerShaderFps','layerShaderTimeScale','layerShaderQuality','layerShaderLiveWeather','layerShaderWeatherLat','layerShaderWeatherLon','layerShaderWeatherRefresh','layerWidgetType','layerWidgetFormat','layerWidgetRefresh','clockRingColor','clockTickColor','clockHourColor','clockMinuteColor','clockSecondColor','clockFaceColor','clockShowSeconds','clockFillFace','layerCountdownTarget','layerCountdownFormat','layerWeatherLat','layerWeatherLon','layerWeatherDisplay','layerWeatherTempUnit','layerWeatherWindUnit','weatherShowIcon','weatherAnimateIcon','weatherShowCondition','weatherShowFeels','weatherShowWind','weatherShowGusts','weatherShowHumidity','weatherShowPrecip','weatherCycleDetails','weatherDetailPeriod','layerWeatherTemplate','layerDataUrl','layerJsonPath','layerRssItem','layerDataPrefix','layerDataSuffix','widgetFont','widgetFontSize','widgetRenderMode','widgetColor','widgetAutoFit','widgetAlign','widgetVAlign','widgetPadding','layerIconName','layerIconColor','layerIconColor2','layerIconEffect','layerIconPeriod','layerShape','layerFill','layerBorderColor','layerBorderWidth','layerRadius'].forEach(id=>$(id).addEventListener('input',updateSelectedFromControls));
  $('layerShader').addEventListener('change',()=>{updateSelectedFromControls();renderShaderParameterFields();});
  $('designerPreviewTime').addEventListener('input',()=>{$('designerPreviewTimeValue').textContent=`${Number($('designerPreviewTime').value).toFixed(2)}s`;renderTimeline();scheduleEditorPreview();});$('designerAnimatePreview').addEventListener('change',()=>{state.previewStarted=performance.now();scheduleEditorPreview();});$('designerPreviewMode').addEventListener('change',()=>setPreviewMode('designer',$('designerPreviewMode').value));$('livePreviewMode').addEventListener('change',()=>setPreviewMode('live',$('livePreviewMode').value));
  $('designerSelection').addEventListener('pointerdown',ev=>{if(ev.target.classList.contains('resize-handle'))return;beginDesignerDrag(ev,'move');});$('designerSelection').querySelector('.resize-handle').addEventListener('pointerdown',ev=>beginDesignerDrag(ev,'resize'));window.addEventListener('pointermove',ev=>{moveDesignerDrag(ev);moveTimelineDrag(ev);});window.addEventListener('pointerup',()=>{endDesignerDrag();endTimelineDrag();});window.addEventListener('resize',()=>{updateSelectionOverlay();renderTimeline();});
  document.addEventListener('keydown',ev=>{
    const typing=isTypingTarget();const meta=ev.metaKey||ev.ctrlKey,key=String(ev.key||'').toLowerCase(),messagesActive=messagesTabVisible();
    if(!typing&&ev.key==='?'){ev.preventDefault();showShortcutHelp(true);return;}
    if(!messagesActive||$('msgEditorMode').value!=='designer')return;
    if(meta&&key==='s'&&!typing){ev.preventDefault();saveMessage(false);return;}
    if(meta&&key==='c'&&!typing){ev.preventDefault();copySelectedLayers();return;}
    if(meta&&key==='v'&&!typing){ev.preventDefault();pasteCopiedLayers();return;}
    if(meta&&key==='d'&&!typing){ev.preventDefault();duplicateLayer();return;}
    if(meta&&key==='a'&&!typing){ev.preventDefault();const ids=(state.scene?.layers||[]).map(l=>l.id);setSelection(ids,ids[0]);renderLayerList();loadSelectedLayerControls();return;}
    if(meta&&key==='g'&&!typing){ev.preventDefault();ev.shiftKey?ungroupSelected():groupSelected();return;}
    if(meta&&key==='z'&&!typing){ev.preventDefault();ev.shiftKey?redoDesigner():undoDesigner();return;}
    if(meta&&key==='y'&&!typing){ev.preventDefault();redoDesigner();return;}
    if(typing)return;
    if(ev.key==='Escape'){setSelection([],null);renderLayerList();loadSelectedLayerControls();return;}
    if(ev.key===' '){ev.preventDefault();$('designerAnimatePreview').checked=!$('designerAnimatePreview').checked;state.previewStarted=performance.now();scheduleEditorPreview();return;}
    if((ev.key==='Delete'||ev.key==='Backspace')&&selectionLayers().length){ev.preventDefault();deleteLayer();return;}
    if(ev.key==='['&&selectionLayers().length){ev.preventDefault();moveLayer(-1);return;}if(ev.key===']'&&selectionLayers().length){ev.preventDefault();moveLayer(1);return;}
    if(!selectedLayer())return;const map={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]};if(!map[ev.key])return;ev.preventDefault();recordHistory();const step=ev.shiftKey?5:1;for(const l of selectionLayers()){l.x=(+l.x||0)+map[ev.key][0]*step;l.y=(+l.y||0)+map[ev.key][1]*step;}loadSelectedLayerControls();renderLayerList();scheduleEditorPreview();
  });
  setInterval(()=>{
    if($('msgEditorMode').value!=='designer'||!messagesTabVisible())return;
    if($('designerAnimatePreview').checked){renderTimeline();updateEditorPreview();return;}
    // Static Designer previews still need to refresh live widgets.  The first
    // render intentionally returns Loading… while the Pi fetches data off-thread;
    // this follow-up render is what replaces it with the fetched value/error.
    if((sceneHasShader()&&performance.now()-state.lastWidgetPreviewAt>=320)||(sceneHasLiveWidget()&&performance.now()-state.lastWidgetPreviewAt>=900)){
      state.lastWidgetPreviewAt=performance.now();updateEditorPreview();
    }
  },180);

  // Events – dashboard/playlists/schedules/settings
  $('quickShow').addEventListener('click',async()=>{if(!$('quickMessage').value)return;try{await api(`/api/messages/${$('quickMessage').value}/show`,{method:'POST',body:{duration:+$('quickDuration').value}});toast('Showing message now');}catch(e){toast(e.message,true);}});
  $('clearOverride').addEventListener('click',async()=>{try{await api('/api/show/clear',{method:'POST'});toast('Returned to automatic schedule');}catch(e){toast(e.message,true);}});$('refreshPreview').addEventListener('click',()=>refreshLivePreview(true));$('livePreviewEnabled').addEventListener('change',()=>setLivePreviewEnabled($('livePreviewEnabled').checked));$('livePreviewRate').addEventListener('change',()=>{localStorage.setItem('pimatrixLivePreviewRate',$('livePreviewRate').value);scheduleLivePreview(0);});document.addEventListener('visibilitychange',()=>{if(!document.hidden)scheduleLivePreview(0);});
  $$('.test-pattern').forEach(b=>b.addEventListener('click',async()=>{try{await api('/api/test-pattern',{method:'POST',body:{kind:b.dataset.pattern,duration:30}});toast(`${b.textContent} test for 30 seconds`);}catch(e){toast(e.message,true);}}));
  $('newPlaylist').addEventListener('click',blankPlaylist);$('addPlaylistItem').addEventListener('click',()=>{if(!$('playlistMessagePicker').value)return;state.playlistItems.push({message_id:+$('playlistMessagePicker').value,duration:Math.max(.5,+$('playlistDuration').value||10)});renderPlaylistItems();});$('savePlaylist').addEventListener('click',()=>savePlaylist(false));$('showPlaylist').addEventListener('click',()=>savePlaylist(true));$('deletePlaylist').addEventListener('click',deletePlaylist);$('exportPlaylist').addEventListener('click',()=>downloadPortable('playlist',+$('playlistId').value));$('importPlaylistFile').addEventListener('change',async()=>{const f=$('importPlaylistFile').files?.[0];if(f)await importPortableFile(f,'playlist');$('importPlaylistFile').value='';});
  $('newSchedule').addEventListener('click',blankSchedule);$('scheduleTargetType').addEventListener('change',()=>updateScheduleTargetOptions());$('saveSchedule').addEventListener('click',saveSchedule);$('deleteSchedule').addEventListener('click',deleteSchedule);$('newConditionalRule').addEventListener('click',blankConditionalRule);$('conditionalTargetType').addEventListener('change',()=>updateConditionalTargetOptions());$('conditionalType').addEventListener('change',syncConditionFields);$('saveConditionalRule').addEventListener('click',saveConditionalRule);$('deleteConditionalRule').addEventListener('click',deleteConditionalRule);$('newBrightnessSchedule').addEventListener('click',blankBrightnessSchedule);$('brightnessScheduleBrightness').addEventListener('input',()=>$('brightnessScheduleValue').textContent=`${$('brightnessScheduleBrightness').value}%`);$('saveBrightnessSchedule').addEventListener('click',saveBrightnessSchedule);$('deleteBrightnessSchedule').addEventListener('click',deleteBrightnessSchedule);$('saveEmergencySetting').addEventListener('click',saveEmergencySetting);$('activateEmergency').addEventListener('click',async()=>{if(!confirm('Activate the configured emergency message now?'))return;try{await api('/api/emergency/activate',{method:'POST',body:{}});toast('Emergency mode activated');}catch(e){toast(e.message,true);}});$('clearEmergency').addEventListener('click',async()=>{try{await api('/api/emergency/clear',{method:'POST',body:{}});toast('Emergency mode ended');}catch(e){toast(e.message,true);}});
  $('newUser').addEventListener('click',blankUser);$('saveUser').addEventListener('click',saveUser);$('deleteUser').addEventListener('click',deleteUser);
    ['panelWidth','panelHeight','panelsAcross','panelsDown'].forEach(id=>$(id).addEventListener('input',updateLayoutSummary));$('brightness').addEventListener('input',()=>{$('brightnessValue').textContent=`${$('brightness').value}%`;});$('saveSettings').addEventListener('click',saveSettings);$('activateLicence').addEventListener('click',activateLicence);$('checkLicence').addEventListener('click',checkLicence);$('clearLocalLicence').addEventListener('click',clearLocalLicence);$('openLicenseSetup').addEventListener('click',openLicenceSetup);$('refreshFpp').addEventListener('click',loadFppSetup);$('saveGpioControls').addEventListener('click',saveGpioControls);$$('[data-gpio-field="action"]').forEach(x=>x.addEventListener('change',syncGpioEmergencyFields));$$('[data-gpio-test]').forEach(x=>x.addEventListener('click',()=>testGpioAction(x.dataset.gpioTest)));$('shutdownPi').addEventListener('click',shutdownPi);$('refreshDiagnostics').addEventListener('click',()=>loadDiagnostics(true));$('saveRecoverySettings').addEventListener('click',saveRecoverySettings);$('restartRenderer').addEventListener('click',()=>diagnosticsAction('restart-renderer','Restart the LED renderer now? The web interface stays online.'));$('restartFppd').addEventListener('click',()=>diagnosticsAction('restart-fppd','Restart FPPD now? The LED output may pause briefly.'));$('clearRecoveryHistory').addEventListener('click',()=>diagnosticsAction('clear-history','Clear the recovery history?'));

  $('createBackup').addEventListener('click',createBackup);$('refreshBackups').addEventListener('click',()=>loadBackups());$('exportConfiguration').addEventListener('click',()=>downloadPortable('configuration'));$('importConfigurationFile').addEventListener('change',async()=>{const f=$('importConfigurationFile').files?.[0];if(f){const r=await importPortableFile(f,'configuration');if(r){await loadAll();toast('Portable configuration imported');}}$('importConfigurationFile').value='';});
  const backupZone=$('backupDropZone');
  ['dragenter','dragover'].forEach(name=>backupZone.addEventListener(name,ev=>{ev.preventDefault();if(!$('backupRestoreFile').disabled)backupZone.classList.add('dragover');}));
  ['dragleave','drop'].forEach(name=>backupZone.addEventListener(name,ev=>{ev.preventDefault();backupZone.classList.remove('dragover');}));
  backupZone.addEventListener('drop',ev=>{if($('backupRestoreFile').disabled)return;const file=ev.dataTransfer?.files?.[0];if(file)restoreUploadedBackup(file);});
  $('backupRestoreFile').addEventListener('change',()=>{const file=$('backupRestoreFile').files?.[0];if(file)restoreUploadedBackup(file);});

  // The customer-facing Upgrade tab was removed in v0.6.7. Keep these
  // listeners conditional so the legacy browser-upgrade engine can remain
  // packaged for rollback/service-maintenance use without requiring its UI.
  const upgradeZone=$('upgradeDropZone');
  if(upgradeZone){
    ['dragenter','dragover'].forEach(name=>upgradeZone.addEventListener(name,ev=>{ev.preventDefault();if(!$('upgradeFile').disabled)upgradeZone.classList.add('dragover');}));
    ['dragleave','drop'].forEach(name=>upgradeZone.addEventListener(name,ev=>{ev.preventDefault();upgradeZone.classList.remove('dragover');}));
    upgradeZone.addEventListener('drop',ev=>{if($('upgradeFile').disabled)return;const file=ev.dataTransfer?.files?.[0];if(file)startUpgrade(file);});
    $('upgradeFile').addEventListener('change',()=>{const file=$('upgradeFile').files?.[0];if(file)startUpgrade(file);});
    $('refreshUpgradeStatus')?.addEventListener('click',()=>loadUpgradeStatus());
  }
  $('logoutButton').addEventListener('click',async()=>{try{await api('/api/auth/logout',{method:'POST'});}finally{location.href='/login';}});

  setupMessageEditorWorkspace();
  enhanceColourPickers();
  initDesignerPanelPreferences();
  loadAll().then(()=>{refreshStatus();setInterval(refreshStatus,1600);setInterval(()=>{if(setupTabVisible())loadDiagnostics(false);},3000);setInterval(()=>{if(setupTabVisible()&&can('display_setup'))loadGpioControls(false);},900);const saved=localStorage.getItem('pimatrixLivePreview');const rate=localStorage.getItem('pimatrixLivePreviewRate');if(rate&&[...$('livePreviewRate').options].some(o=>o.value===rate))$('livePreviewRate').value=rate;const liveMode=localStorage.getItem('pimatrixPreviewMode:live')||'p5',designerMode=localStorage.getItem('pimatrixPreviewMode:designer')||'p5';if([...$('livePreviewMode').options].some(o=>o.value===liveMode))$('livePreviewMode').value=liveMode;if([...$('designerPreviewMode').options].some(o=>o.value===designerMode))$('designerPreviewMode').value=designerMode;setLivePreviewEnabled(saved!=='0');updateHistoryButtons();updateClipboardButton();refreshPreviewSimulation();});
})();
