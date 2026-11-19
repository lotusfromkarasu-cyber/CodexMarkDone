// Isolated rendering fixtures; never accesses the user's browser or chats.
const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const web=process.env.MARKDONE_WEB_ROOT||path.join(__dirname,'../web');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe'});
 try{
  const page=await browser.newPage({viewport:{width:1600,height:1000}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  let settings={thread:'test',autoSync:false};
  const raw='1. **Chen + Cheng：仅波段手性准 BIC 驱动的量子阱吸收。**把两个模式独立控制。\n\n**因此，可以建立上下两个环境域，分别用 `n_top`、`n_bottom` 控制。**模拟整体浸没时。\n\n| 项目 | 数值 |\n| --- | --- |\n| A | 42 |';
  await page.route('http://markdone.test/**',route=>{
   const url=new URL(route.request().url());let data;
   if(url.pathname==='/api/settings'){
    if(route.request().method()==='POST')settings=route.request().postDataJSON();
    data={settings,token:'test'};
   }else if(url.pathname==='/api/library')data={threads:[{id:'test',title:'Reading fixture'}],projects:[],revision:'1'};
   else if(url.pathname==='/api/thread')data={id:'test',title:'Reading fixture',revision:'1',messages:[{id:'a1',role:'assistant',raw},{id:'a2',role:'assistant',raw:'第二条 **正常加粗**。'}]};
   else if(url.pathname.startsWith('/api/'))data={ok:true};
   if(data!==undefined)return route.fulfill({json:data});
   const file=path.join(web,url.pathname==='/'?'index.html':url.pathname);
   return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':file.endsWith('.html')?'text/html':'application/octet-stream'});
  });
  await page.goto('http://markdone.test/');
  await page.waitForFunction(()=>document.querySelectorAll('#messages .message').length===2);
  const rendered=await page.evaluate(()=>{
   const R=ReaderRender;
   return [
    '**关于虚部：你的理解对，真实材料吸收需要损耗。**我上文将虚部设零。',
    '中文**（括号内强调）**后文',
    '**说明：*内层斜体*。**接下文',
    '`**代码原样。**后文`',
    '\\*\\*转义原样。\\*\\*后文',
    '```txt\n**围栏原样。**后文\n```',
    '**不闭合',
    '** 有空格 **',
    '**公式 $x^2$。**后文',
   ].map(s=>R.render(s));
  });
  for(const i of [0,1,2,8])assert.match(rendered[i],/<strong>/);
  assert.match(rendered[2],/<em>内层斜体<\/em>/);
  for(const i of [3,4,5,6,7])assert.doesNotMatch(rendered[i],/<strong>/);
  assert.match(rendered[8],/class="formula/);
  assert.equal(await page.locator('#messages strong').count(),3); // two bold sections plus second reply
  assert.deepEqual(await page.locator('#messages strong code').allTextContents(),['n_top','n_bottom']);
  const mathTable=await page.evaluate(()=>{
   const source=String.raw`正文。

| 波长 | 有源区内 \(\max |E_z/E_0|\) | 含义 |
|---|---:|---|
| 7.7 µm | $|x|$ | A \| B |
| 8.0 µm | $\|x\|$ | ${'`\\|`'} |

后续正文。`;
   const doc=document.createElement('div');
   doc.innerHTML=ReaderRender.render(source);
   const table=doc.querySelector('table');
   if(!table)return null;
   return {columns:table.tHead.rows[0].cells.length,rows:[...table.tBodies[0].rows].map(row=>row.cells.length),
    formulas:[...table.querySelectorAll('.formula:not(.error)')].map(node=>node.dataset.latex),
    values:[...table.querySelectorAll('td:last-child')].map(node=>node.textContent),
    alignment:table.tHead.rows[0].cells[1].style.textAlign,following:table.nextElementSibling.textContent};
  });
  assert.deepEqual(mathTable,{columns:3,rows:[3,3],formulas:[String.raw`\max |E_z/E_0|`,'|x|',String.raw`\|x\|`],
   values:['A | B','|'],alignment:'right',following:'后续正文。'});
  const prices=await page.evaluate(()=>{
   const doc=document.createElement('div');
   doc.innerHTML=ReaderRender.render('| A | B |\n|---|---|\n| $5 | $3 |');
   return [...doc.querySelectorAll('td')].map(cell=>cell.textContent);
  });
  assert.deepEqual(prices,['$5','$3']);
  const table=await page.locator('#messages table').evaluate(el=>{
   const r=el.getBoundingClientRect(),p=el.closest('.message-body').getBoundingClientRect();
   return {offset:Math.abs((r.left+r.right)-(p.left+p.right)),align:getComputedStyle(el.querySelector('td')).textAlign};
  });
  assert(table.offset<2);assert.equal(table.align,'center');
  await page.locator('#focus-toggle').click();
  assert.equal(Math.round((await page.locator('#focus-window').boundingBox()).width),880);
  await page.locator('#focus-width').fill('1200');
  await page.waitForFunction(()=>document.querySelector('#focus-window').getBoundingClientRect().width===1200);
  await page.waitForFunction(()=>document.querySelector('#focus-width-value').value==='1200 px');
  await page.waitForResponse(response=>response.url().endsWith('/api/settings')&&response.request().method()==='POST');
  await page.locator('#focus-next').click();
  assert.equal(Math.round((await page.locator('#focus-window').boundingBox()).width),1200);
  await page.reload();await page.locator('#focus-toggle').click();
  assert.equal(Math.round((await page.locator('#focus-window').boundingBox()).width),1200);
  await page.setViewportSize({width:600,height:850});
  assert((await page.locator('#focus-window').boundingBox()).width<=548);
  assert.deepEqual(errors,[]);
  console.log('CJK bold, math and dollar amounts in tables, centered table, adjustable/persisted focus width and narrow viewport passed.');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
