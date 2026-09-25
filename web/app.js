(() => {
  const $=s=>document.querySelector(s), R=ReaderRender, reader=$('#reader'), host=$('#messages'), pop=$('#copy-popover'), focusBody=$('#focus-body');
  let settings={},token='',library={threads:[],projects:[]},current=null,revision=null,items=[],sel=null,pending=null,hits=[],hitIndex=-1,busy=false,saveTimer,toastTimer,multiMode=false,turnRAF=null,focusIndex=-1,dragging=false,navSig='';
  let queuedRender=null;
  const mtimeOf=new Map();
  let autoSync=true,syncTimer=null,idlePolls=0;
  const SYNC_FAST=3000,SYNC_IDLE=8000;
  const cards=new Map();
  const renderCache=new Map();
  const preview=s=>s.replace(/\s+/g,' ').slice(0,90);
  function toast(text){$('#toast').textContent=text;$('#toast').classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').classList.remove('show'),3200);}
  async function api(path,body){const res=await fetch('/api/'+path,body?{method:'POST',headers:{'Content-Type':'application/json','X-Reader-Token':token},body:JSON.stringify(body)}:{});const data=await res.json();if(!res.ok)throw Error(data.error||'连接失败');return data;}
  function save(){clearTimeout(saveTimer);saveTimer=setTimeout(()=>api('settings',settings).catch(()=>{}),900);}
  function theme(){const mode=settings.theme||'system';document.documentElement.dataset.theme=mode==='system'?(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'):mode;$('#theme').value=mode;}
  function applyLayout(){
    const ws=document.querySelector('.workspace'),split=document.querySelector('.right-split');
    ws.style.setProperty('--left-w',(settings.leftCollapsed?0:(settings.leftW||274))+'px');
    ws.style.setProperty('--gap-l',(settings.leftCollapsed?0:6)+'px');
    ws.style.setProperty('--right-w',(settings.rightCollapsed?0:(settings.rightW||306))+'px');
    ws.style.setProperty('--gap-r',(settings.rightCollapsed?0:6)+'px');
    split.style.setProperty('--turn-h',(settings.turnH||42)+'%');
  }
  function sidebars(){document.body.classList.toggle('left-collapsed',!!settings.leftCollapsed);document.body.classList.toggle('right-collapsed',!!settings.rightCollapsed);applyLayout();}
  $('#theme').onchange=e=>{settings.theme=e.target.value;theme();save();};
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change',theme);
  for(const side of ['left','right'])$('#toggle-'+side).onclick=()=>{
    settings[side+'Collapsed']=!settings[side+'Collapsed'];
    if(innerWidth<=850&&!settings[side+'Collapsed'])settings[(side==='left'?'right':'left')+'Collapsed']=true;
    sidebars();save();
  };

  /* ---------- selection model (atomic: line / formula / whole message) ---------- */
  function cloneBody(card){const d=document.createElement('div');d.append(card.querySelector('.message-body').cloneNode(true));return d;}
  function liveRect(it){
    const el=it.whole?it.card:it.el;if(!el)return null;
    const r=el.getBoundingClientRect();return (r.width||r.height)?r:null;
  }
  function syncChecks(){host.querySelectorAll('.message').forEach(c=>{const chk=c.querySelector('.msg-check');if(chk)chk.checked=!!(sel&&sel.items.some(it=>it.card===c));});}
  function syncNav(){
    if(!sel||!sel.items.length)return;
    const card=sel.items[sel.items.length-1].card;if(!card)return;
    const turnNav=$('#turn-nav');
    if(!turnNav.hidden){const row=turnNav.querySelector('.turn-node[data-turn="'+card._turn+'"]');if(row){turnNav.querySelectorAll('.turn-node.active').forEach(n=>n.classList.remove('active'));row.classList.add('active');row.scrollIntoView({block:'nearest'});}}
    const msgNav=$('#message-nav');
    const b=msgNav.querySelector('.nav-item[data-message="'+card.dataset.id+'"]');
    if(b){msgNav.querySelectorAll('.nav-item.active').forEach(n=>n.classList.remove('active'));b.classList.add('active');b.scrollIntoView({block:'nearest'});}
  }
  function markSelected(){
    for(const scope of [host,focusBody])scope.querySelectorAll('.message.selected,.sel-line').forEach(n=>n.classList.remove('selected','sel-line'));
    if(!sel)return;
    for(const it of sel.items){
      if(it.el&&!(it.whole&&it.el===it.card))it.el.classList.add('sel-line');
      if(it.whole&&it.card)it.card.classList.add('selected');
    }
    syncChecks();syncNav();
  }
  function updateCopyUI(){
    const n=sel?sel.items.length:0;
    $('#copy-obsidian').disabled=n===0;$('#copy-word').disabled=n===0;$('#copy-wps').disabled=n===0;$('#copy-latex').disabled=n===0;
    const hasF=sel?sel.items.some(it=>it.node&&it.node.querySelector('.formula:not(.error)')):false;
    $('#copy-formula').disabled=n===0||!hasF;
    const total=host.querySelectorAll('.message').length;
    $('#select-all').textContent=(n&&n===total)?'清除选择':'全选内容';
    $('#selection-label').textContent=n?('已选择 '+n+' 条'+(multiMode?' · 多选模式':'')):'未选择';
  }
  function placePopover(){
    if(!sel||!sel.items.length)return;
    const it=sel.items[sel.items.length-1];
    const rect=liveRect(it)||sel.rect;
    if(!rect)return;
    sel.rect=rect;
    const w=pop.offsetWidth||280,h=pop.offsetHeight||100;
    const left=Math.max(8,Math.min(innerWidth-w-8,rect.left+rect.width/2-w/2));
    let y=rect.top-h-10;
    if(y<76)y=rect.bottom+10;
    y=Math.max(76,Math.min(innerHeight-h-8,y));
    pop.style.left=left+'px';pop.style.top=y+'px';
  }
  function setSelection(list,label){clearSelection(false);sel={items:list};$('#selection-label-pop').textContent=label;pop.hidden=false;markSelected();updateCopyUI();placePopover();}
  function chooseSingle(node,label,anchor,raw=null){
    clearSelection(false);
    const el=anchor&&anchor.closest?anchor.closest('.formula,.source-line'):null;
    const card=anchor&&anchor.closest?anchor.closest('.message'):null;
    const whole=!el;
    const d=document.createElement('div');d.append(node.cloneNode(true));
    sel={items:[{node:d,raw,card,el,whole}]};
    $('#selection-label-pop').textContent=label;pop.hidden=false;markSelected();updateCopyUI();placePopover();
  }
  function toggleCard(card){
    if(sel&&sel.items.some(it=>it.card===card)){sel.items=sel.items.filter(it=>it.card!==card);if(!sel.items.length){clearSelection();return;}}
    else{if(!sel)sel={items:[]};sel.items.push({node:cloneBody(card),raw:card._raw,card,el:null,whole:true});}
    $('#selection-label-pop').textContent='已选择 '+sel.items.length+' 条 · 可继续点击增减';pop.hidden=false;markSelected();updateCopyUI();placePopover();
  }
  function clearSelection(apply=true){
    sel=null;pop.hidden=true;
    for(const scope of [host,focusBody])scope.querySelectorAll('.selected,.sel-line').forEach(n=>n.classList.remove('selected','sel-line'));
    host.querySelectorAll('.msg-check').forEach(c=>c.checked=false);
    updateCopyUI();
    if(apply&&pending){const data=pending;pending=null;applyThread(data);}
  }
  function answersOf(card){const all=[...host.querySelectorAll('.message')],i=all.indexOf(card),picked=[];for(let j=i+1;j<all.length;j++){if(all[j].classList.contains('user'))break;picked.push(all[j]);}return picked;}
  function selectAll(){
    const msgs=[...host.querySelectorAll('.message')];if(!msgs.length)return;
    if(sel&&sel.items.length===msgs.length){clearSelection();return;}
    setSelection(msgs.map(c=>({node:cloneBody(c),raw:c._raw,card:c,el:null,whole:true})),'已选择全部 '+msgs.length+' 条');
  }
  function selectTurn(card){
    const picked=answersOf(card);if(!picked.length){toast('这一轮还没有回答');return;}
    setSelection(picked.map(c=>({node:cloneBody(c),raw:c._raw,card:c,el:null,whole:true})),'已选择第 '+card._turn+' 轮的全部回答');
  }
  function buildPayload(mode){
    if(!sel||!sel.items.length)throw Error('请先选择内容');
    const payload={mode};
    if(mode==='obsidian')payload.raw=sel.items.map(it=>it.raw!=null?R.obsidianSource(it.raw):R.markdown(it.node)).join('\n\n');
    else if(mode==='latex'){payload.raw=sel.items.map(it=>R.latex(it.node)).join('\n\n');}
    else if(mode==='word'||mode==='wps'){const holder=document.createElement('div');for(const it of sel.items)holder.append(it.node.cloneNode(true));Object.assign(payload,R.word(holder));}
    else{for(const it of sel.items){const f=it.node.querySelector('.formula:not(.error)');if(f){payload.raw=f.dataset.latex;payload.mathml=R.mathml(f.dataset.latex,f.dataset.display==='1').outerHTML;break;}}if(!payload.raw)throw Error('选区中没有可解析的公式');}
    return payload;
  }
  async function copyMode(mode){try{const payload=buildPayload(mode);const result=await api('clipboard',payload);if(result.platform==='darwin'){toast(mode==='obsidian'?'已复制 Markdown':mode==='latex'?'已复制纯 LaTeX 文本':mode==='formula'?'已复制公式内容':'已复制格式化内容（macOS）');}else{toast(mode==='obsidian'?'已复制 Markdown':mode==='formula'?'已复制 Word 可编辑公式':mode==='latex'?'已复制纯 LaTeX 文本':mode==='wps'?'已复制 WPS 内容与可编辑公式':'已复制 Word 内容与可编辑公式');}}catch(e){toast('复制失败：'+e.message);}}
  for(const b of [$('#copy-obsidian'),$('#copy-word'),$('#copy-wps'),$('#copy-latex'),$('#copy-formula')])b.addEventListener('click',()=>copyMode(b.dataset.copy));
  $('#select-all').onclick=selectAll;
  $('#multi-toggle').onclick=()=>{
    multiMode=!multiMode;
    document.body.classList.toggle('multi',multiMode);
    $('#multi-toggle').classList.toggle('active',multiMode);
    $('#multi-toggle').textContent=multiMode?'多选 ✓':'多选';
    host.querySelectorAll('.msg-check').forEach(c=>{c.checked=!!(sel&&sel.items.some(it=>it.card===c.closest('.message')));});
    if(!multiMode&&sel){sel.items.length?updateCopyUI():clearSelection();}
  };
  $('#dismiss').onclick=()=>{window.getSelection()?.removeAllRanges();clearSelection();};

  /* ---------- single-message reading (focus modal) ---------- */
  function focusRender(){
    const m=items[focusIndex];if(!m)return;
    focusBody.replaceChildren(createCard(m));
    $('#focus-meta').textContent=(m.role==='user'?'用户提问':'Codex 回复')+' · '+(m.timestamp?new Date(m.timestamp).toLocaleString():'');
    $('#focus-count').textContent=(focusIndex+1)+' / '+items.length;
    focusBody.scrollTop=0;
  }
  function focusOpen(){
    if(!items.length){toast('当前对话还没有消息');return;}
    let idx=-1;
    const card=sel?sel.items[sel.items.length-1].card:null;
    if(card){const i=items.findIndex(m=>m.id===card.dataset.id);if(i>=0)idx=i;}
    if(idx<0)idx=0;
    focusIndex=idx;focusRender();
    const modal=$('#focus-modal');modal.hidden=false;
    $('#focus-toggle').classList.add('active');
    toast('单条阅读 · 第 '+(idx+1)+' 条');
  }
  function focusStep(delta){
    if(!items.length)return;
    let i=focusIndex+delta;
    if(i<0)i=items.length-1;if(i>=items.length)i=0;
    focusIndex=i;focusRender();
    toast('第 '+(i+1)+' 条 / 共 '+items.length+' 条');
  }
  function focusClose(){$('#focus-modal').hidden=true;$('#focus-toggle').classList.remove('active');}
  $('#focus-toggle').onclick=focusOpen;
  $('#focus-close').onclick=focusClose;
  $('#focus-prev').onclick=()=>focusStep(-1);
  $('#focus-next').onclick=()=>focusStep(1);
  $('#focus-modal').addEventListener('mousedown',e=>{if(e.target.id==='focus-modal')focusClose();});  /* ---------- library sidebar ---------- */
  function renderLibrary(){
    const nav=$('#library'),scroll=nav.scrollTop,q=$('#project-search').value.toLowerCase(),archived=$('#archives').checked;
    nav.replaceChildren();
    const rows=library.threads.filter(t=>!!t.archived===archived&&t.title.toLowerCase().includes(q));
    function group(id,name,threads,pin=false){
      if(!threads.length&&(q||archived))return;
      const d=document.createElement('details');d.open=q?true:settings.groups?.[id]===true;
      const s=document.createElement('summary');s.textContent=(pin?'📌 ':'')+name+' · '+threads.length;d.append(s);
      for(const t of threads){const b=document.createElement('button');b.className='thread-link'+(t.id===current?' active':'');b.textContent=(t.is_pinned?'📌 ':'')+(t.title||'未命名对话');b.title=t.title;b.onclick=()=>{if(t.id!==current)openThread(t.id);};d.append(b);}
      d.ontoggle=()=>{settings.groups??={};settings.groups[id]=d.open;save();};nav.append(d);
    }
    const pins=rows.filter(t=>t.is_pinned).sort((a,b)=>(a.pin_order??99)-(b.pin_order??99));if(pins.length)group('pinned','置顶对话',pins,true);
    for(const p of library.projects)group(p.id,p.name,rows.filter(t=>t.project_id===p.id&&!t.is_pinned),p.is_pinned);
    group('other','未归属项目',rows.filter(t=>!library.projects.some(p=>p.id===t.project_id)&&!t.is_pinned));
    nav.scrollTop=scroll;
  }
  $('#project-search').oninput=renderLibrary;$('#archives').onchange=renderLibrary;

  /* ---------- cards ---------- */
  function createCard(m){
    const card=document.createElement('article');
    card.className='message '+m.role;card.dataset.id=m.id;
    const attached=(m.images||[]).map((src,i)=>'<img class="message-image attached-image" src="'+R.esc(R.imageSrc(src))+'" alt="对话附件 '+(i+1)+'" loading="lazy" decoding="async" referrerpolicy="no-referrer">').join('');
    card.innerHTML='<div class="message-header"><label class="msg-check-wrap" title="多选"><input type="checkbox" class="msg-check" aria-label="多选"></label><b class="role">'+(m.role==='user'?'你':'✦ Codex')+'</b><span class="when">'+R.esc(m.timestamp?new Date(m.timestamp).toLocaleString():'')+'</span><button class="select-reply">选择回复</button></div><div class="message-body">'+R.render(m.raw||'')+attached+'</div>';
    card._raw=m.raw;return card;
  }
  function msgSig(list){const n=list.length;return n?n+':'+list[n-1].id+':'+list[n-1].raw.length:'';}
  function assignTurns(){
    let turn=0;
    for(const m of items){if(m.role==='user')turn++;const c=cards.get(m.id);if(c)c._turn=turn;}
  }
  function cancelQueued(){if(queuedRender){cancelAnimationFrame(queuedRender.raf);queuedRender=null;}}
  function cacheRender(title){
    if(queuedRender)return;
    renderCache.delete(current);
    renderCache.set(current,{rev:revision,html:host.innerHTML,items:items.slice(),title,mtime:mtimeOf.get(current)||0});
    while(renderCache.size>4)renderCache.delete(renderCache.keys().next().value);
  }
  function setScrollTop(v){reader.style.scrollBehavior='auto';reader.scrollTop=v;reader.style.scrollBehavior='';}
  function renderCards(msgs,start,end){
    for(let i=start;i<end;i++){
      const m=msgs[i];
      if(!cards.has(m.id)){const card=createCard(m);cards.set(m.id,card);host.append(card);}
    }
  }
  function pumpQueue(){
    const q=queuedRender;if(!q)return;
    const end=Math.min(q.i+24,q.list.length);
    renderCards(q.list,q.i,end);q.i=end;assignTurns();renderTurns();
    if(q.i<q.list.length){queuedRender.raf=requestAnimationFrame(pumpQueue);}
    else{queuedRender=null;setScrollTop(settings.positions?.[current]||0);if($('#content-search').value)search(false);if(!$('#focus-modal').hidden&&focusIndex>=0&&focusIndex<items.length)focusRender();cacheRender($('#thread-title').textContent);}
  }
  function applyThread(data,initial=false){
    const atBottom=reader.scrollHeight-reader.scrollTop-reader.clientHeight<90,top=reader.scrollTop;
    if(sel&&!initial){pending=data;$('#new-content').hidden=false;return;}
    const msgs=data.messages;
    const nextIds=new Set(msgs.map(m=>m.id));
    for(const [id,card] of cards)if(!nextIds.has(id)){card.remove();cards.delete(id);}
    cancelQueued();
    const chunked=initial&&msgs.length>14;
    if(chunked)renderCards(msgs,0,14);
    else renderCards(msgs,0,msgs.length);
    items=msgs;revision=data.revision;
    mtimeOf.set(current,data.mtime||0);
    $('#thread-title').textContent=data.title;$('#welcome').hidden=true;
    assignTurns();
    $('#message-count').textContent=items.length+' 条消息';
    const sig=msgSig(msgs);
    if(sig!==navSig){navSig=sig;navMessages();renderTurns();}
    else if(items.length){$('#nav-count').textContent=items.length+' 条';}
    if(initial){
      setScrollTop(settings.positions?.[current]||0);
      if(chunked){queuedRender={list:msgs,i:14,raf:0};queuedRender.raf=requestAnimationFrame(pumpQueue);}
      else{if(!$('#content-search').value)cacheRender(data.title);}
    }else if(atBottom){reader.scrollTop=reader.scrollHeight;}
    else{reader.scrollTop=top;$('#new-content').hidden=false;}
    if(!chunked&&!$('#focus-modal').hidden&&focusIndex>=0&&focusIndex<items.length)focusRender();
  }
  async function openThread(id){
    clearSelection(false);focusClose();
    if(current){settings.positions??={};settings.positions[current]=reader.scrollTop;}
    current=id;revision=null;pending=null;items=[];cards.clear();navSig='';
    cancelQueued();
    host.replaceChildren();
    $('#message-nav').replaceChildren();$('#turn-nav').replaceChildren();
    $('#content-search').value='';search(false);$('#new-content').hidden=true;
    settings.thread=id;save();renderLibrary();
    const row=library.threads.find(t=>t.id===id);
    $('#project-label').textContent=library.projects.find(p=>p.id===row?.project_id)?.name||'本地对话';
    if(innerWidth<=850){settings.leftCollapsed=true;sidebars();}
    const hit=renderCache.get(id);
    if(hit){
      host.innerHTML=hit.html;
      host.querySelectorAll('mark').forEach(n=>n.replaceWith(document.createTextNode(n.textContent)));
      host.querySelectorAll('.search-hit,.current').forEach(n=>n.classList.remove('search-hit','current'));
      cards.clear();
      for(const el of host.querySelectorAll('.message')){el._raw=hit.items.find(m=>m.id===el.dataset.id)?.raw||'';cards.set(el.dataset.id,el);}
      items=hit.items;revision=hit.rev;
      mtimeOf.set(id,hit.mtime||0);
      $('#thread-title').textContent=hit.title;$('#welcome').hidden=true;
      assignTurns();
      $('#message-count').textContent=items.length+' 条消息';
      navSig='';navMessages();renderTurns();
      setScrollTop(settings.positions?.[id]||0);
      if(!$('#focus-modal').hidden&&focusIndex>=0&&focusIndex<items.length)focusRender();
      return;
    }
    try{const data=await api('thread?id='+encodeURIComponent(id));if(current===id)applyThread(data,true);}
    catch(e){toast('暂时无法读取该对话，将自动重试：'+e.message);}
  }

  /* ---------- right sidebar: turns + message nav ---------- */
  function renderTurns(){
    const nav=$('#turn-nav'),users=[...host.querySelectorAll('.message.user')];
    nav.replaceChildren();nav.hidden=users.length===0;
    users.forEach((card,i)=>{const row=document.createElement('div');row.className='turn-node';row.dataset.turn=card._turn;
      const dot=document.createElement('span');dot.className='turn-dot';dot.textContent=i+1;
      const txt=document.createElement('span');txt.className='turn-text';txt.textContent=preview(card.querySelector('.message-body').textContent||'未命名提问');txt.title=card._raw||card.querySelector('.message-body').textContent;
      const btn=document.createElement('button');btn.className='turn-pick';btn.textContent='选回答';btn.title='选择这一轮的全部回答';
      row.append(dot,txt,btn);
      row.addEventListener('click',ev=>{if(ev.target.closest('.turn-pick')){selectTurn(card);return;}card.scrollIntoView({block:'start',behavior:'smooth'});});
      nav.append(row);});
  }
  function updateTurns(){
    turnRAF=null;const nav=$('#turn-nav');if(nav.hidden||!nav.children.length)return;
    const users=[...host.querySelectorAll('.message.user')],rTop=reader.getBoundingClientRect().top,mid=rTop+reader.clientHeight*0.35;
    let active=0;users.forEach((c,i)=>{if(c.getBoundingClientRect().top<=mid)active=i;});
    [...nav.children].forEach((n,i)=>n.classList.toggle('active',i===active));
    const max=reader.scrollHeight-reader.clientHeight,ratio=max>0?Math.min(1,Math.max(0,reader.scrollTop/max)):0;
    nav.style.setProperty('--fill',(ratio*100).toFixed(1)+'%');
  }
  function navMessages(){
    const nav=$('#message-nav'),scroll=nav.scrollTop;nav.replaceChildren();
    for(const m of items){const b=document.createElement('button');b.className='nav-item';b.dataset.message=m.id;
      b.innerHTML='<small>'+ (m.role==='user'?'你':'Codex') +(m.channel==='commentary'?' · 进度':'')+'</small>'+R.esc(preview(m.raw));
      b.onclick=()=>{const card=cards.get(m.id);card?.scrollIntoView({block:'start',behavior:'smooth'});nav.querySelectorAll('.active').forEach(n=>n.classList.remove('active'));b.classList.add('active');if(innerWidth<=850){settings.rightCollapsed=true;sidebars();}};
      nav.append(b);}
    nav.scrollTop=scroll;
    $('#nav-count').textContent=items.length+' 条';
    $('#message-count').textContent=items.length+' 条消息';
  }

  reader.addEventListener('scroll',()=>{
    if(current){settings.positions??={};settings.positions[current]=reader.scrollTop;save();}
    if(sel)placePopover();
    if(!turnRAF)turnRAF=requestAnimationFrame(updateTurns);
    if(reader.scrollHeight-reader.scrollTop-reader.clientHeight<40&&!pending)$('#new-content').hidden=true;
  },{passive:true});  /* ---------- selection gestures ---------- */
  function handleCardClick(e){
    if(window.getSelection()?.toString().trim())return;
    if(e.target.closest('a'))return;
    const card=e.target.closest('.message');if(!card)return;
    if(e.target.closest('.msg-check')){toggleCard(card);return;}
    if(e.ctrlKey||e.metaKey||multiMode){toggleCard(card);return;}
    if(e.target.closest('.select-reply')){chooseSingle(card.querySelector('.message-body'),'已选择整条回复',card,card._raw);return;}
    const f=e.target.closest('.formula');if(f){chooseSingle(f,'已选择公式',f);return;}
    const line=e.target.closest('.source-line');if(line){chooseSingle(line,line.classList.contains('code-line')?'已选择代码行':'已选择这一行',line);return;}
    if(e.target.closest('.message-header')||e.target.closest('.message-body')||e.target===card)chooseSingle(card.querySelector('.message-body'),'已选择整条回复',card,card._raw);
  }
  host.addEventListener('click',handleCardClick);
  focusBody.addEventListener('click',handleCardClick);
  host.addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target.matches('.formula')){e.preventDefault();chooseSingle(e.target,'已选择公式',e.target);}});
  document.addEventListener('mouseup',e=>{
    if(dragging)return;
    if(e.target.closest('#copy-popover'))return;
    const native=window.getSelection();if(!native||native.isCollapsed||!native.rangeCount)return;
    const scope=e.target.closest('#focus-body')?focusBody:host;
    const range=native.getRangeAt(0).cloneRange();if(!scope.contains(range.commonAncestorContainer))return;
    scope.querySelectorAll('.formula').forEach(f=>{if(!range.intersectsNode(f))return;const a=range.startContainer.nodeType===1?range.startContainer:range.startContainer.parentElement;const b=range.endContainer.nodeType===1?range.endContainer:range.endContainer.parentElement;if(f.contains(a))range.setStartBefore(f);if(f.contains(b))range.setEndAfter(f);});
    const rect=range.getBoundingClientRect();
    const wrapper=document.createElement('div');wrapper.append(range.cloneContents());
    wrapper.querySelectorAll('.message-header,button').forEach(n=>n.remove());
    clearSelection(false);
    sel={items:[{node:wrapper,raw:null,card:null,el:null,whole:false}],rect};
    $('#selection-label-pop').textContent='手动选择 · Ctrl+点击可继续追加';pop.hidden=false;markSelected();updateCopyUI();placePopover();
  });
  document.addEventListener('mousedown',e=>{
    if(e.target.closest('#copy-popover'))return;
    if(multiMode&&e.target.closest('.message'))return;
    if(e.ctrlKey||e.metaKey)return;
    if(sel&&!e.target.closest('.message,.source-line,.select-reply,.msg-check,#toolbar'))clearSelection();
  });
  document.addEventListener('keydown',e=>{if(e.key==='Escape'){if(!$('#focus-modal').hidden){focusClose();return;}window.getSelection()?.removeAllRanges();clearSelection();}});
  pop.addEventListener('mousedown',e=>e.preventDefault());
  pop.addEventListener('click',async e=>{const mode=e.target.closest('[data-copy]')?.dataset.copy;if(!mode||!sel)return;copyMode(mode);});
  window.addEventListener('resize',()=>{if(sel)placePopover();});

  /* ---------- resizable layout (drag dividers) ---------- */
  function initDrag(){
    const ws=document.querySelector('.workspace'),split=document.querySelector('.right-split');
    function bind(id,move,reset,axis){
      const bar=$('#'+id);if(!bar)return;
      bar.addEventListener('mousedown',e=>{
        e.preventDefault();dragging=true;document.body.classList.add('drag-'+axis);
        const onMove=ev=>{ev.preventDefault();move(ev);};
        const onUp=()=>{dragging=false;document.body.classList.remove('drag-'+axis);document.removeEventListener('mousemove',onMove);document.removeEventListener('mouseup',onUp);save();};
        document.addEventListener('mousemove',onMove);document.addEventListener('mouseup',onUp);
      });
      bar.addEventListener('dblclick',()=>{reset();save();});
    }
    bind('drag-left',e=>{const w=Math.max(150,Math.min(e.clientX,innerWidth-500));settings.leftW=w;ws.style.setProperty('--left-w',w+'px');},()=>{settings.leftW=null;ws.style.setProperty('--left-w','274px');},'col');
    bind('drag-right',e=>{const w=Math.max(210,Math.min(innerWidth-e.clientX,innerWidth-430));settings.rightW=w;ws.style.setProperty('--right-w',w+'px');},()=>{settings.rightW=null;ws.style.setProperty('--right-w','306px');},'col');
    bind('drag-turn',e=>{const r=split.getBoundingClientRect();const pct=Math.min(85,Math.max(15,(e.clientY-r.top)/r.height*100));settings.turnH=pct;split.style.setProperty('--turn-h',pct+'%');},()=>{settings.turnH=null;split.style.setProperty('--turn-h','42%');},'row');
  }
  initDrag();

  /* ---------- search ---------- */
  function search(jump=true){
    if(sel){window.getSelection()?.removeAllRanges();clearSelection();}
    host.querySelectorAll('mark').forEach(n=>n.replaceWith(document.createTextNode(n.textContent)));host.normalize();host.querySelectorAll('.search-hit').forEach(n=>n.classList.remove('search-hit','current'));
    hits=[];hitIndex=-1;const q=$('#content-search').value.toLowerCase().trim();if(!q){$('#match-count').textContent='输入内容以搜索';return;}
    for(const body of host.querySelectorAll('.message-body')){
      const walker=document.createTreeWalker(body,NodeFilter.SHOW_TEXT,{acceptNode:n=>n.parentElement.closest('.formula,button')?NodeFilter.FILTER_REJECT:NodeFilter.FILTER_ACCEPT});const texts=[];while(walker.nextNode())texts.push(walker.currentNode);
      for(const n of texts){let value=n.textContent,lower=value.toLowerCase(),pos=0,end,fragment=document.createDocumentFragment(),found=false;while((end=lower.indexOf(q,pos))!==-1){found=true;fragment.append(value.slice(pos,end));const mark=document.createElement('mark');mark.textContent=value.slice(end,end+q.length);fragment.append(mark);pos=end+q.length;}if(found){fragment.append(value.slice(pos));n.replaceWith(fragment);}}
      body.querySelectorAll('.formula').forEach(f=>{if(f.dataset.latex.toLowerCase().includes(q))f.classList.add('search-hit');});
    }
    hits=[...host.querySelectorAll('mark,.search-hit')];$('#match-count').textContent=hits.length+' 处匹配';if(jump&&hits.length)moveHit(1);
  }
  function moveHit(delta){if(!hits.length)return;hits[hitIndex]?.classList.remove('current');hitIndex=(hitIndex+delta+hits.length)%hits.length;hits[hitIndex].classList.add('current');hits[hitIndex].scrollIntoView({block:'center'});$('#match-count').textContent=(hitIndex+1)+' / '+hits.length;}
  $('#content-search').oninput=()=>search();$('#next-match').onclick=()=>moveHit(1);$('#prev-match').onclick=()=>moveHit(-1);
  $('#new-content').onclick=()=>{window.getSelection()?.removeAllRanges();clearSelection();reader.scrollTop=reader.scrollHeight;$('#new-content').hidden=true;};

  function updateSyncUI(){
    const btn=$('#sync-auto');
    btn.textContent=autoSync?'⏸ 暂停同步':'▶ 开启同步';
    btn.classList.toggle('off',!autoSync);
    btn.title=autoSync?'暂停自动同步':'开启自动同步';
    $('#sync-mode').textContent=autoSync?'自动同步':'已暂停';
    if(!autoSync)$('#sync').textContent='已暂停';
  }
  function scheduleSync(delay){
    clearTimeout(syncTimer);
    if(!autoSync||document.hidden)return;
    syncTimer=setTimeout(poll,delay);
  }
  async function poll(){
    if(busy)return;
    if(document.hidden){scheduleSync(SYNC_IDLE);return;}
    busy=true;
    let changed=false;
    try{
      const next=await api('library');
      if(next.revision!==library.revision){library=next;renderLibrary();changed=true;}
      if(current){
        const id=current,mtime=mtimeOf.get(id)||'';
        const data=await api('thread?id='+encodeURIComponent(id)+'&revision='+encodeURIComponent(revision??'')+(mtime?'&mtime='+encodeURIComponent(mtime):''));
        if(current===id&&!data.unchanged){applyThread(data,revision===null);changed=true;}
      }
      $('#sync').textContent=autoSync?'● 已同步':'● 已同步（暂停中）';
    }catch(e){$('#sync').textContent='等待重连';}
    finally{
      busy=false;
      idlePolls=changed?0:idlePolls+1;
      scheduleSync(idlePolls>=4?SYNC_IDLE:SYNC_FAST);
    }
  }
  $('#sync-now').onclick=()=>{poll();};
  $('#sync-auto').onclick=()=>{
    autoSync=!autoSync;settings.autoSync=autoSync;save();updateSyncUI();
    if(autoSync){idlePolls=0;scheduleSync(0);}else{clearTimeout(syncTimer);}
  };
  document.addEventListener('visibilitychange',()=>{if(!document.hidden){poll();updateTurns();}});
  function hashThread(){return new URLSearchParams(location.hash.slice(1)).get('thread');}
  window.addEventListener('hashchange',()=>{
    if(document.hidden){const id=hashThread();if(id&&id!==current)openThread(id);return;}
    const id=hashThread();if(id&&id!==current)openThread(id);
  });
  async function start(){
    try{
      const data=await api('settings');token=data.token;settings=data.settings;theme();
      if(settings.groups&&Object.keys(settings.groups).length){settings.groups={};save();}
      if(innerWidth<=850){settings.leftCollapsed=true;settings.rightCollapsed=true;}
      sidebars();
      autoSync=settings.autoSync!==false;
      updateSyncUI();
      library=await api('library');renderLibrary();
      const id=hashThread()||settings.thread;
      if(id&&library.threads.some(t=>t.id===id))await openThread(id);
      scheduleSync(0);updateTurns();
    }catch(e){toast('启动失败：'+e.message);$('#sync').textContent='连接失败';}
  }
  start();
})();
