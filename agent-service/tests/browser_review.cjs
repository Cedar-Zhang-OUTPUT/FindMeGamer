// Run with NODE_PATH pointing to an existing Playwright installation. Local fixtures only.
const {chromium}=require('playwright');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {spawn}=require('node:child_process'),assert=require('node:assert/strict');
(async()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'fmg-review-qa-'));
 fs.mkdirSync(path.join(root,'runs/test'),{recursive:true});
 fs.writeFileSync(path.join(root,'game-profile.md'),'# Test game\nCo-op puzzle game.\nAI inference: coordination-focused creators.');
 fs.writeFileSync(path.join(root,'runs/test/search-intent.json'),JSON.stringify({angles:['Co-op puzzle gameplay'],budget:{pages_per_platform:5}}));
 const script=path.resolve(__dirname,'../../skills/fmg-research/scripts/game_review.py');
 const proc=spawn(process.env.PYTHON||'python3',[script,'serve','--root',root,'--run-id','test']);
 const url=await new Promise((resolve,reject)=>{proc.stdout.once('data',s=>{try{resolve(JSON.parse(s).url)}catch(e){reject(e)}});proc.once('error',reject);proc.stderr.on('data',s=>process.stderr.write(s));});
 let browser, viewer;
 try{
 browser=await chromium.launch({headless:true,channel:process.env.FMG_BROWSER_CHANNEL||'chrome'});
 const page=await browser.newPage({viewport:{width:1280,height:900}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.goto(url);await page.locator('#edit').waitFor();
 await page.locator('#edit').click();
 assert.equal(await page.locator('#platforms input:checked').count(),3);
 await page.locator('#platforms input[value=x]').uncheck();
 await page.keyboard.press('Escape');
 await page.locator('#edit').click();
 assert.equal(await page.locator('#platforms input:checked').count(),3);
 await page.locator('#count-mode').selectOption('presets');
 assert.equal(await page.locator('#count-unknown').isChecked(),false);
 await page.locator('#presets input[value=under1k]').check();
 await page.locator('#count-unknown').check();
 await page.locator('#count-mode').selectOption('custom');
 assert.equal(await page.locator('#count-unknown').isChecked(),true);
 await page.locator('#count-min').fill('100');
 await page.locator('#count-mode').selectOption('any');
 await page.locator('#count-mode').selectOption('custom');
 assert.equal(await page.locator('#count-unknown').isChecked(),false);
 await page.locator('#languages input[value=ja]').check();
 await page.locator('#north-america').click();
 await page.locator('#contact').selectOption('has_email');
 await page.locator('#apply').click();
 await page.locator('#corrections').fill('Prioritize cooperative mechanics');
 await page.locator('#approve').click();
 await page.getByText('已保存。Codex 将读取你的确认和纠偏，再继续查找。').waitFor();
 const saved=JSON.parse(fs.readFileSync(path.join(root,'runs/test/game-confirmation.json')));
 assert.deepEqual(saved.filters.regions.codes,['US','CA']);
 assert.deepEqual(saved.filters.languages,['ja']);
 assert.equal(saved.filters.contact,'has_email');
 assert.equal(saved.filters.target_total,null);
 assert.equal(saved.filters.followers.min,100);
 await page.reload();await page.locator('#edit').click();
 assert.equal(await page.locator('#contact').inputValue(),'has_email');
 await page.locator('#region-search').fill('US');
 assert.equal(await page.locator('#regions label:visible').count(),1);
 await page.locator('#cancel').click();
 assert.equal(await page.locator('#corrections').inputValue(),'Prioritize cooperative mechanics');
 const foreign=await page.request.post(url+'save',{headers:{Origin:'https://foreign.example'},data:{}});
 assert.equal(foreign.status(),403);
 await page.screenshot({path:path.join(root,'desktop.png'),fullPage:true});
 await page.setViewportSize({width:390,height:844});
 await page.locator('#edit').click();
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
 await page.locator('#cancel').click();
 await page.screenshot({path:path.join(root,'mobile.png'),fullPage:true});
 fs.mkdirSync(path.join(root,'runs/test/matches'));
 fs.writeFileSync(path.join(root,'runs/test/matches/creator.json'),JSON.stringify({
   creator:{platform:'twitch',account_id:'123',display_name:'RisXch',profile_url:'https://www.twitch.tv/risxch'},
   match:{decision:'suitable'},presentation:{public_name:'Unknown — 仅确认公开账号名',followers:'Unknown — 未查询'},
   contacts:{status:'found',primary_email:'chosen@example.com',emails:[{address:'other@example.com',purpose:'公开商务联系'},{address:'chosen@example.com',purpose:'公开商务联系'}]},
   metrics:{followers:{status:'found',value:4321,metric:'followers',checked_at:'2026-09-22T01:00:00Z'}}
 }));
 viewer=spawn(process.env.PYTHON||'python3',[path.join(path.dirname(script),'research_dashboard.py'),'--root',root,'--run-id','test']);
 const viewerUrl=await new Promise((resolve,reject)=>{viewer.stdout.once('data',s=>{try{resolve(JSON.parse(s).url)}catch(e){reject(e)}});viewer.once('error',reject)});
 await page.goto(viewerUrl);await page.locator('#rows tr').waitFor();
 const row=await page.locator('#rows tr').innerText();
 assert.ok(row.includes('RisXch')&&row.includes('4,321 followers')&&row.includes('chosen@example.com'));
 assert.ok(!row.includes('other@example.com')&&!row.includes('公开商务联系')&&!row.includes('仅确认公开账号名'));
 assert.deepEqual(errors,[]);
 console.log(JSON.stringify({passed:true,artifacts:root,checks:'default platforms, Escape rollback, count modes, language/region independence, persisted approval, Origin protection, desktop/mobile, public-name fallback, primary email, follower rendering'}));
 }finally{if(browser)await browser.close();proc.kill();if(viewer)viewer.kill();}
})().catch(e=>{console.error(e);process.exitCode=1});
