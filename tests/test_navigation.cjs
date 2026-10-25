// Isolated headless UI regression; no user browser profile or session data.
const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),assert=require('assert');
const web=process.env.MARKDONE_WEB_ROOT||path.join(__dirname,'../web');
const messages=[];
for(let i=1;i<=80;i++){
  messages.push({id:'q'+i,role:'user',raw:'Question '+i});
  messages.push({id:'a'+i,role:'assistant',raw:Array.from({length:30},(_,j)=>'Paragraph '+j+' '+('Long answer text. '.repeat(12))).join('\n\n')});
}
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  try{
    const page=await browser.newPage({viewport:{width:1440,height:1000}});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    let revision=1;
    await page.route('http://markdone.test/**',async route=>{
      const url=new URL(route.request().url());let data;
      if(url.pathname==='/api/settings')data={settings:{thread:'test',autoSync:false},token:'test'};
      else if(url.pathname==='/api/library')data={threads:[{id:'test',title:'Long navigation fixture'}],projects:[],revision:'1'};
      else if(url.pathname==='/api/thread')data=url.searchParams.get('revision')===String(revision)?{unchanged:true}:{id:'test',title:'Long navigation fixture',revision:String(revision),messages};
      else if(url.pathname.startsWith('/api/'))data={ok:true};
      if(data!==undefined)return route.fulfill({json:data});
      const file=path.join(web,url.pathname==='/'?'index.html':url.pathname);
      return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':file.endsWith('.html')?'text/html':'application/octet-stream'});
    });
    async function ready(){
      await page.goto('http://markdone.test/');
      await page.waitForFunction(()=>document.querySelectorAll('#messages .message').length===160);
      await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
    }
    async function aligned(id){
      await page.waitForFunction(id=>{
        const reader=document.querySelector('#reader'),card=document.querySelector('.message[data-id="'+id+'"]');
        return card&&Math.abs(card.getBoundingClientRect().top-reader.getBoundingClientRect().top-reader.clientTop)<3;
      },id,{timeout:2500});
    }
    await ready();
    // A real sync update during a long native smooth scroll used to abort it.
    await page.locator('.turn-node').last().click();
    await page.waitForTimeout(60);revision++;
    await page.locator('#sync-now').click();
    await aligned('q80');
    assert.equal(await page.locator('.turn-node.active').getAttribute('data-turn'),'80');
    await page.locator('.nav-item[data-message="a1"]').click();await aligned('a1');
    await page.locator('.nav-item[data-message="a80"]').click();await aligned('a80');
    assert.equal(await page.locator('.nav-item.active').getAttribute('data-message'),'a80');
    // Navigation before the chunk queue has created the requested card.
    await page.goto('http://markdone.test/');
    await page.waitForSelector('.nav-item[data-message="q80"]');
    const clickedWhileQueued=await page.evaluate(()=>{
      const queued=document.querySelectorAll('#messages .message').length<160;
      document.querySelector('.nav-item[data-message="q80"]').click();return queued;
    });
    assert(clickedWhileQueued,'Fixture must click before rendering finishes');
    await aligned('q80');
    assert.equal(await page.locator('.nav-item.active').getAttribute('data-message'),'q80');
    assert.equal(await page.evaluate(()=>window.scrollY),0,'Navigation must scroll only the reader');
    assert.deepEqual(errors,[]);
    console.log('80 turns / 160 messages: single-click latest turn, forward/backward message navigation, sync during jump and queued target passed.');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
