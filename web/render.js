/* Shared Markdown / math model. Dependencies are vendored for offline use. */
(() => {
  const esc = s => String(s).replace(/[&<>"']/g, x => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x]));
  const md = window.markdownit({html:false, linkify:true, breaks:true});
  // CommonMark treats punctuation beside CJK text as a delimiter boundary.
  // Relax only that boundary for double asterisks, using the native emphasis
  // pairing algorithm so escapes, code spans, nesting and math remain intact.
  const cjk = c => /[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}]/u.test(c || '');
  const punctuation = c => /[\p{P}\p{S}]/u.test(c || '');
  md.inline.ruler.before('emphasis','reader_cjk_strong',state=>{
    if(!state.readerCjkStrong){
      state.readerCjkStrong=true;
      const scan=state.scanDelims;
      state.scanDelims=function(pos,split){
        const result=scan.call(this,pos,split);
        if(this.src[pos]==='*'&&result.length===2){
          const before=this.src[pos-1],after=this.src[pos+2];
          if(cjk(before)&&punctuation(after))result.can_open=true;
          if(punctuation(before)&&cjk(after))result.can_close=true;
        }
        return result;
      };
    }
    return false;
  });
  function imageSrc(src) {
    const value=String(src||'').trim();
    if (/^(?:data:image\/|blob:|https?:\/\/)/i.test(value)) return value;
    if (/^(?:file:\/\/|[a-zA-Z]:[\\/]|\\\\)/.test(value)) {
      return '/api/image?path='+encodeURIComponent(value);
    }
    return value;
  }
  md.renderer.rules.image=(tokens,i)=>{
    const token=tokens[i];
    const src=imageSrc(token.attrGet('src')||'');
    if(!src)return '';
    const alt=token.content||'';
    const title=token.attrGet('title');
    const titleAttr=title?' title="'+esc(title)+'"':'';
    return '<img class="message-image" src="'+esc(src)+'" alt="'+esc(alt)+'"'+titleAttr+' loading="lazy" decoding="async" referrerpolicy="no-referrer">';
  };
  const delimiters = [['\\\\[','\\\\]',true],['\\[','\\]',true],['\\\\(','\\\\)',false],['\\(','\\)',false],['$$','$$',true],['$','$',false]];
  function matchMath(src, pos) {
    for (const [open, close, display] of delimiters) {
      if (!src.startsWith(open, pos)) continue;
      if (open === '$' && (/\s/.test(src[pos+1] || '') || src[pos+1] === '$')) continue;
      let end = pos + open.length;
      while ((end = src.indexOf(close, end)) >= 0) {
        if (src[end-1] === '\\' && close[0] === '$') {end++; continue;}
        const body = src.slice(pos+open.length,end);
        if (!display && body.includes('\n')) break;
        if (!body.trim()) break;
        return {body,display,end:end+close.length};
      }
    }
    return null;
  }
  const formulaCache = new Map();
  function formula(body, display) {
    const key = (display ? 'd|' : 'i|') + body;
    const hit = formulaCache.get(key);
    if (hit) return hit;
    let html;
    try {
      const rendered = katex.renderToString(body,{displayMode:display,output:'htmlAndMathml',throwOnError:true,trust:false,strict:'ignore',maxExpand:1000});
      html = `<span class="formula ${display?'display':''}" data-latex="${esc(body)}" data-display="${display?'1':'0'}" tabindex="0" role="button" aria-label="选择公式">${rendered}</span>`;
    } catch (e) {
      html = `<span class="formula error ${display?'display':''}" data-latex="${esc(body)}" data-display="${display?'1':'0'}" data-error="1"><small>公式解析失败 · ${esc(e.message)}</small>${esc(body)}</span>`;
    }
    if (formulaCache.size > 3000) formulaCache.clear();
    formulaCache.set(key, html);
    return html;
  }
  md.inline.ruler.before('escape','reader_math',(state,silent)=>{
    const m=matchMath(state.src,state.pos); if(!m)return false;
    if(!silent){
      const t=state.push('reader_math','',0);
      t.content=m.body;t.meta={display:m.display,start:state.pos,end:m.end};
    }
    state.pos=m.end;return true;
  });
  // markdown-it splits table cells before it parses inline math. Temporarily
  // mask formula pipes without changing source offsets or the native GFM rule.
  const {fn:parseTable,alt:tableAlternates}=md.block.ruler.__rules__.find(rule=>rule.name==='table');
  md.block.ruler.at('table',(state,start,end,silent)=>{
    const src=state.src;
    const lineStart=row=>state.bMarks[row]+state.tShift[row];
    const separator=start+1;
    const delimiter=separator<end ? src.slice(lineStart(separator),state.eMarks[separator]) : '';
    if(!delimiter.includes('-') || /[^|:\t -]/.test(delimiter)){
      return parseTable(state,start,end,silent);
    }
    const columns=delimiter.split('|').filter(cell=>cell.trim()).length;
    const columnCount=line=>{
      const cells=line.trim().split(/(?<!\\)\|/);
      return cells.length-(cells[0]===''?1:0)-(cells.at(-1)===''?1:0);
    };
    // A private-use character of the same width keeps the block parser's offsets valid.
    let marker,from=0;
    const pieces=[];
    const protect=row=>{
      const offset=lineStart(row);
      const line=src.slice(offset,state.eMarks[row]);
      if(!line.includes('|') || !/[$\\]/.test(line))return;
      const tokens=[];
      let masked='',last=0;
      md.inline.parse(line,md,state.env,tokens);
      for(const token of tokens){
        if(token.type!=='reader_math')continue;
        const {start:begin,end:finish}=token.meta;
        const raw=line.slice(begin,finish);
        if(!raw.includes('|'))continue;
        if(!marker)marker=['\ue000','\ue001','\ue002'].find(char=>!src.includes(char));
        if(!marker)return;
        masked+=line.slice(last,begin)+raw.replaceAll('|',marker);
        last=finish;
      }
      if(!last)return;
      masked+=line.slice(last);
      // Preserve valid cells such as "| $5 | $3 |" where a dollar amount
      // in one column can resemble a math delimiter spanning both columns.
      if(columnCount(line)===columns && columnCount(masked)<columns)return;
      pieces.push(src.slice(from,offset),masked);
      from=state.eMarks[row];
    };
    protect(start);
    if(!silent){
      for(let row=start+2;row<end;row++){
        const indent=state.sCount[row]-state.blkIndent;
        if(indent<0 || indent>=4 || state.isEmpty(row))break;
        protect(row);
      }
    }
    if(!pieces.length)return parseTable(state,start,end,silent);
    const firstToken=state.tokens.length;
    state.src=pieces.join('')+src.slice(from);
    try{
      const parsed=parseTable(state,start,end,silent);
      for(let i=firstToken;i<state.tokens.length;i++){
        const token=state.tokens[i];
        if(token.type==='inline')token.content=token.content.replaceAll(marker,'|');
      }
      return parsed;
    }finally{
      state.src=src;
    }
  },{alt:tableAlternates});
  md.block.ruler.before('fence','reader_math_block',(state,start,end,silent)=>{
    const pos=state.bMarks[start]+state.tShift[start];
    const m=matchMath(state.src,pos);if(!m || !m.display)return false;
    // A display expression begins a block only if the remainder of its closing line is empty.
    const nextNewline=state.src.indexOf('\n',m.end);
    if(state.src.slice(m.end,nextNewline<0?state.src.length:nextNewline).trim())return false;
    if(silent)return true;
    let next=start;while(next<end&&state.bMarks[next]<m.end)next++;
    const t=state.push('reader_math_block','div',0);t.content=m.body;t.meta={display:true};t.map=[start,next];
    state.line=next;return true;
  },{alt:['paragraph','reference','blockquote','list']});
  md.renderer.rules.reader_math=(ts,i)=>formula(ts[i].content,ts[i].meta.display);
  md.renderer.rules.reader_math_block=(ts,i)=>`<div class="source-line math-line">${formula(ts[i].content,true)}</div>`;
  // Wrap logical source lines without running a second Markdown parser over the result.
  const inlineRender=md.renderer.renderInline.bind(md.renderer);
  md.renderer.renderInline=(tokens,options,env)=>{
    let result='',part=[];
    const flush=()=>{if(part.length){result+='<span class="source-line">'+inlineRender(part,options,env)+'</span>';part=[];}};
    // Preserve formatting spans across softbreaks: split only outside paired emphasis/link tokens.
    let depth=0;
    for(const t of tokens){
      if((t.type==='softbreak'||t.type==='hardbreak')&&depth===0){flush();result+='<br>';}
      else {part.push(t);depth+=t.nesting;}
    }
    flush();return result;
  };
  md.renderer.rules.fence=(ts,i)=>`<pre><code>${ts[i].content.replace(/\n$/,'').split('\n').map(s=>'<span class="source-line code-line">'+esc(s)+'</span>').join('\n')}</code></pre>`;
  const td=new TurndownService({headingStyle:'atx',codeBlockStyle:'fenced',bulletListMarker:'-'});
  td.use(turndownPluginGfm.gfm);
  td.addRule('readerFormula',{filter:n=>n.classList?.contains('formula'),replacement:(_,n)=>n.dataset.display==='1'?'\n\n$$\n'+n.dataset.latex+'\n$$\n\n':'$'+n.dataset.latex+'$'});
  td.addRule('codeLine',{filter:n=>n.classList?.contains('code-line'),replacement:(content)=>content});
  function markdown(node){return td.turndown(node.cloneNode(true));}
  function obsidianSource(source){
    let out='',i=0;
    while(i<source.length){
      const code=/^(`+|~{3,})/.exec(source.slice(i));
      if(code){const end=source.indexOf(code[0],i+code[0].length);if(end>=0){out+=source.slice(i,end+code[0].length);i=end+code[0].length;continue;}}
      const m=matchMath(source,i);
      if(m){out+=m.display?'$$\n'+m.body.trim()+'\n$$':'$'+m.body+'$';i=m.end;}
      else out+=source[i++];
    }
    return out;
  }
  function mathml(body,display){
    const temp=document.createElement('div');temp.innerHTML=katex.renderToString(body,{displayMode:display,output:'mathml',throwOnError:true,trust:false,strict:'ignore'});
    const math=temp.querySelector('math');math.querySelectorAll('annotation,annotation-xml').forEach(x=>x.remove());
    return math;
  }
  function latex(node){
    const fs=[...node.querySelectorAll('.formula')];
    if(fs.length===1&&node.textContent.trim()===fs[0].textContent.trim())return fs[0].dataset.latex.trim();
    const escapeText=s=>s.replace(/[\\{}%&#_$~^]/g,c=>({'\\':'\\textbackslash{}','~':'\\textasciitilde{}','^':'\\textasciicircum{}'}[c]||'\\'+c));
    function walk(n){
      if(n.nodeType===3)return escapeText(n.textContent);
      if(n.nodeType!==1)return '';
      if(n.classList.contains('formula'))return n.dataset.display==='1'?'\n\n$$\n'+n.dataset.latex+'\n$$\n\n':'$'+n.dataset.latex+'$';
      const tag=n.tagName.toLowerCase(),body=[...n.childNodes].map(walk).join('');
      if(/^h[1-6]$/.test(tag))return '\n\\'+(tag==='h1'?'section':tag==='h2'?'subsection':'subsubsection')+'*{'+body+'}\n\n';
      if(tag==='strong'||tag==='b')return '\\textbf{'+body+'}';
      if(tag==='em'||tag==='i')return '\\emph{'+body+'}';
      if(tag==='br')return '\n';
      if(tag==='p'||tag==='div'||tag==='li')return body+'\n\n';
      if(tag==='button'||tag==='script'||tag==='style')return '';
      return body;
    }
    return walk(node).replace(/\n{3,}/g,'\n\n').trim();
  }
  function word(node){
    const clone=node.cloneNode(true);
    clone.querySelectorAll('button,script,style').forEach(x=>x.remove());
    clone.querySelectorAll('.formula').forEach(f=>{if(f.dataset.error)throw Error('选区中有未解析公式，请先检查原文');f.replaceWith(mathml(f.dataset.latex,f.dataset.display==='1'));});
    clone.querySelectorAll('*').forEach(n=>{if(n.namespaceURI==='http://www.w3.org/1998/Math/MathML')return;for(const a of [...n.attributes])if(!['href','colspan','rowspan'].includes(a.name))n.removeAttribute(a.name);});
    return {html:clone.innerHTML,plain:clone.textContent};
  }
  window.ReaderRender={render:s=>md.render(s),markdown,obsidianSource,latex,word,mathml,esc,imageSrc,matchMath};
})();
