const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),assert=require('assert');
const web=path.join(__dirname,'../web');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe'});
 try {
  const page=await browser.newPage();
  await page.setContent('<div id="sample"></div>');
  for(const file of ['vendor/markdown-it.min.js','vendor/turndown.js','vendor/turndown-plugin-gfm.js','vendor/katex/katex.min.js','render.js'])
   await page.addScriptTag({path:path.join(web,file)});
  const result=await page.evaluate(()=>{
   const R=ReaderRender,box=document.querySelector('#sample');
   box.innerHTML=R.render('## 标题\n\n- 中文 **加粗** $Q_R$。\n\n$$\n\\frac{x}{y}\n$$');
   const single=document.createElement('div');single.append(box.querySelectorAll('.formula')[1].cloneNode(true));
   return {latex:R.latex(box),single:R.latex(single),word:R.word(box)};
  });
  assert.equal(result.single,'\\frac{x}{y}');
  assert(result.latex.includes('\\subsection*{标题}'));
  assert(result.latex.includes('\\textbf{加粗}'));
  assert(result.latex.includes('$Q_R$'));
  assert(!result.latex.includes('```'));
  assert(!result.word.html.includes('katex-html'));
  assert(result.word.html.includes('<math'));
  let copies=[];
  await page.route('http://markdone.test/**',async route=>{
   const url=new URL(route.request().url()),api=url.pathname;
   if(api.startsWith('/api/')){
    let data={};
    if(api==='/api/settings')data={settings:{thread:'test',autoSync:false},token:'test'};
    if(api==='/api/library')data={threads:[{id:'test',title:'Test'}],projects:[],revision:'1'};
    if(api==='/api/thread')data={id:'test',title:'Test',revision:'1',messages:[{id:'0',role:'assistant',raw:'中文 $Q_R$'}]};
    if(api==='/api/clipboard'){copies.push(route.request().postDataJSON());data={ok:true};}
    return route.fulfill({json:data});
   }
   const file=path.join(web,api==='/'?'index.html':api);
   return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':file.endsWith('.html')?'text/html':'application/octet-stream'});
  });
  await page.goto('http://markdone.test/');
  await page.locator('.select-reply').click();
  for(const mode of ['latex','wps','word']){
   const response=page.waitForResponse('**/api/clipboard');
   await page.locator('#copy-'+mode).click();await response;
  }
  assert.deepEqual(copies.map(x=>x.mode),['latex','wps','word']);
  assert.equal(copies[0].raw,'中文 $Q_R$');
  assert(copies[1].html.includes('<math'));
  console.log('LaTeX source, MathML payload, and all three copy buttons passed.');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
