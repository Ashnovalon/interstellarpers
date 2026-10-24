'use strict';
// Real HTTP server + actual DOM handlers. Only browser platform facilities
// unavailable in jsdom (canvas, dialogs, downloads) are adapted, never API data.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {spawn}=require('node:child_process');
const {JSDOM,VirtualConsole}=require('jsdom');
const server=spawn(process.env.PYTHON||'python',['-B','scripts/serve_audit_app.py'],{stdio:['ignore','pipe','pipe'],windowsHide:true});
let serverError='';server.stderr.on('data',b=>serverError+=b);
const contexts=[],checks=[];
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function until(test,label,timeout=45000){const started=Date.now();while(!test()){if(Date.now()-started>timeout)throw Error(`Timeout: ${label}`);await sleep(25)}}
function check(label){checks.push(label);console.log('PASS '+label)}

async function browser(root,page,scripts){
  const errors=[],calls=[],downloads=[],aborts=new AbortController();
  const html=await fetch(root+page).then(r=>r.text());
  const vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
  const dom=new JSDOM(html,{url:root+page,runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc});
  const w=dom.window,d=w.document;
  w.structuredClone=structuredClone;w.TextDecoder=TextDecoder;
  w.fetch=async(path,options={})=>{
    const call={path,body:options.body?JSON.parse(options.body):null};calls.push(call);
    const response=await fetch(root+path,{...options,signal:aborts.signal});
    if(path!='/api/live/stream'){
      const original=response.json.bind(response);
      response.json=async()=>{const result=await original();call.result=result;call.status=response.status;return result};
    }
    return response;
  };
  const context={scale(){},clearRect(){},beginPath(){},moveTo(...v){assert.ok(v.every(Number.isFinite),'Chart coordinate must be finite')},lineTo(...v){assert.ok(v.every(Number.isFinite),'Chart coordinate must be finite')},stroke(){},fillText(){},setLineDash(){},arc(){},fill(){}};
  w.HTMLCanvasElement.prototype.getContext=()=>context;
  w.HTMLCanvasElement.prototype.getBoundingClientRect=()=>({width:700,height:260,left:0,top:0});
  w.HTMLDialogElement.prototype.showModal=function(){this.open=true};
  w.HTMLDialogElement.prototype.close=function(){this.open=false};
  const blobs=new Map();w.URL.createObjectURL=b=>{const id='blob:audit-'+blobs.size;blobs.set(id,b);return id};w.URL.revokeObjectURL=()=>{};
  w.HTMLAnchorElement.prototype.click=function(){downloads.push({filename:this.download,blob:blobs.get(this.href)})};
  const api=async(path,body)=>{const response=await fetch(root+path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const result=await response.json();assert.ok(response.ok,JSON.stringify(result));return result};
  const click=selector=>{const node=d.querySelector(selector);assert.ok(node,`Missing ${selector}`);assert.ok(!node.disabled,`Disabled ${selector}`);node.click();return node};
  const input=(selector,value,type='input')=>{const node=d.querySelector(selector);assert.ok(node,selector);if(node.type==='checkbox')node.checked=value;else node.value=String(value);node.dispatchEvent(new w.Event(type,{bubbles:true}));return node};
  const post=async(selector,path)=>{const old=calls.length;click(selector);await until(()=>calls.slice(old).some(c=>c.path===path&&c.result),selector);return calls.slice(old).find(c=>c.path===path&&c.result)};
  const app={w,d,api,click,input,post,calls,errors,downloads,dom,aborts};contexts.push(app);
  w.eval(scripts.map(script=>fs.readFileSync(script,'utf8')).join('\n'));
  return app;
}

async function liveAudit(root){
  const a=await browser(root,'/',['web/live.js']);const {w,d,click,input,post,api}=a;
  await until(()=>d.querySelectorAll('#market-body tr').length===5,'live initial render');
  const reset=async()=>{const state=await api('/api/live/control',{action:'reset',scenario:'sandbox',seed:77});await until(()=>d.getElementById('footer-state').textContent.includes(state.run_id),'reset stream');return state};
  const step=async(n=1)=>{for(let i=0;i<n;i++)await post('#step-run','/api/live/control')};
  for(const page of ['board','decisions','network','datafeed','inputs','ledger','model']){click(`[data-page="${page}"]`);assert.ok(d.getElementById('page-'+page).classList.contains('active'))}
  check('Live: all seven tabs');
  click('[data-page="board"]');click('#dismiss-welcome');assert.ok(d.getElementById('welcome').hidden);
  click('#reset-run');assert.ok(d.getElementById('reset-dialog').open);click('#close-reset');assert.ok(!d.getElementById('reset-dialog').open);
  click('#reset-run');input('#reset-seed',77);input('#reset-scenario','sandbox','change');await post('#reset-form button[type="submit"]','/api/live/control');assert.ok(!d.getElementById('reset-dialog').open);
  let result=await post('#toggle-run','/api/live/control');assert.equal(result.result.running,true);assert.ok(d.getElementById('step-run').disabled);
  result=await post('#toggle-run','/api/live/control');assert.equal(result.result.running,false);
  for(const speed of [.125,.25,.5,1]){const before=a.calls.length;input('#sim-speed',speed,'change');await until(()=>a.calls.slice(before).some(c=>c.result?.days_per_tick===speed),'speed');await step()}
  check('Live: start/pause, step, all speeds, new-run submit/cancel and welcome dismissal');
  for(const [preset,field,value] of [['viral','trend',5],['rumor','conversion',0],['closure','road_closed',true],['outage','plant_availability',.65],['traffic','traffic_delay_days',2],['imports','import_delay_days',14],['heatwave','heatwave',1.25],['feed','feed_outage',true],['competitor','competitor_pressure',.25],['quality',null,null]]){
    await reset();click('[data-page="inputs"]');input('#shock-duration',0);input('#shock-recovery',0);
    const r=await post(`#preset-grid [data-preset="${preset}"]`,'/api/live/inject');assert.equal(r.status,200);
    if(field)assert.equal(r.result.inputs[field],value);else assert.ok(r.result.metrics.held_pulp_kg>0);
    assert.equal(r.result.tick,1);
  }
  for(const preset of ['viral','closure','outage','feed']){await reset();click('[data-page="board"]');await post(`.quick-presets [data-preset="${preset}"]`,'/api/live/inject')}
  check('Live: all ten disruption presets and four board shortcuts reach the real engine');
  await reset();click('[data-page="inputs"]');input('#shock-duration',1);input('#shock-recovery',1);
  await post('#preset-grid [data-preset="heatwave"]','/api/live/inject');
  input('[name="competitor_pressure"]',.2);input('#shock-duration',0);input('#shock-recovery',0);
  result=await post('#inputs-form button[type="submit"]','/api/live/inputs');
  assert.deepEqual(Object.keys(result.body.changes),['competitor_pressure']);
  assert.ok(result.result.lifecycles.some(x=>x.label.includes('Heatwave')&&x.status==='ACTIVE'));
  await step(6);let s=await api('/api/live/state');assert.equal(s.inputs.heatwave,1);
  for(const [name,value] of [['target_sku','Guava Chilli'],['region','East'],['trend',2],['conversion',.5],['heatwave',1.1],['competitor_pressure',.1],['road_closed',true],['closure_days',3],['traffic_delay_days',1],['plant_availability',.8],['import_delay_days',5],['feed_outage',true],['quality_result','FAIL']])input(`[name="${name}"]`,value);
  result=await post('#inputs-form button[type="submit"]','/api/live/inputs');assert.equal(Object.keys(result.body.changes).length,13);assert.equal(result.result.inputs.region,'East');
  await post('#restore-inputs','/api/live/inputs');s=await api('/api/live/state');assert.equal(s.inputs.feed_outage,false);assert.equal(s.inputs.heatwave,1);
  input('#shock-duration',0);input('#shock-recovery',2);result=await post('#preset-grid [data-preset="heatwave"]','/api/live/inject');assert.equal(result.status,400);assert.ok(!d.getElementById('app-error').hidden);input('#shock-recovery',0);
  check('Live: every scenario field, timed recovery, independent schedules, reset and invalid-duration feedback');
  click('[data-page="datafeed"]');input('#incoming-channel','QC','change');input('#incoming-sku','Dragon Passion','change');input('#incoming-search','Delhi');assert.equal(d.querySelectorAll('#incoming-rows tr').length,1);
  click('#incoming-rows summary');assert.ok(d.querySelector('#incoming-rows details').open);
  click('#incoming-freeze');const frozen=d.getElementById('input-batch-label').textContent;await step();assert.equal(d.getElementById('input-batch-label').textContent,frozen);click('#incoming-freeze');assert.notEqual(d.getElementById('input-batch-label').textContent,frozen);
  click('[data-page="network"]');input('#network-flavor','Guava Chilli','change');assert.equal(d.querySelectorAll('.depot-box').length,9);input('#network-search','Delhi');assert.equal(d.querySelectorAll('#network-rows tr').length,5);
  click('[data-page="board"]');for(const option of d.getElementById('chart-mode').options){input('#chart-mode',option.value,'change');assert.ok(d.getElementById('chart-title').textContent)}
  input('#chart-mode','demand','change');input('#chart-flavor','Dragon Passion','change');d.getElementById('live-chart').dispatchEvent(new w.MouseEvent('mousemove',{clientX:300}));d.getElementById('live-chart').dispatchEvent(new w.MouseEvent('mouseleave'));w.dispatchEvent(new w.Event('resize'));
  click('[data-page="model"]');input('#forecast-flavor','Guava Chilli','change');assert.match(d.getElementById('horizon-summary').textContent,/Guava Chilli/);await until(()=>d.querySelectorAll('#forecast-benchmarks tbody tr').length===4,'benchmark render');
  check('Live: incoming filters/expand/freeze, depot filters, all chart modes/hover/resize, model selector and benchmark');
  for(const choice of ['wait','full','half','delay','reject','close','escape']){
    await reset();click('[data-page="decisions"]');
    for(const filter of ['TRANSFER','SUPPLY','CAPACITY','QUALITY','ALL'])input('#action-filter',filter,'change');
    s=await api('/api/live/state');const offer=s.actions.find(x=>x.kind==='BUFFER'&&x.available);assert.ok(offer);
    await api('/api/live/control',{action:'start'});await until(()=>d.getElementById('toggle-run').textContent.includes('Pause'),'running');
    await post(`[data-review="${offer.id}"]`,'/api/live/review/open');
    await until(()=>d.querySelector('[data-branch="full"]'),'comparison');
    const comparison=a.calls.filter(c=>c.path==='/api/live/compare'&&c.result).at(-1).result;
    assert.ok(comparison.horizon_days>=14);assert.equal(new Set(comparison.branches.map(b=>b.requested)).size,1);
    assert.ok(d.getElementById('review-evidence').textContent.includes('Quantity'));
    assert.equal(d.querySelectorAll('#branch-results [style]').length,0,'CSP must allow branch legend styling');
    s=await api('/api/live/state');assert.equal(s.running,false);const tick=s.tick;await sleep(1100);assert.equal((await api('/api/live/state')).tick,tick);
    if(choice==='close'){await post('#close-review','/api/live/review/close')}
    else if(choice==='escape'){d.getElementById('review-dialog').dispatchEvent(new w.Event('cancel',{cancelable:true}));await until(()=>!d.getElementById('review-dialog').open,'escape closes review')}
    else{
      if(choice!=='reject')click(`[data-branch="${choice}"]`);
      input('#decision-actor','UI audit');input('#decision-reason','Verified against isolated server');input('#decision-checks',choice!=='wait');
      result=await post(choice==='reject'?'#reject-action':'#approve-action','/api/live/decide');assert.equal(result.status,200,JSON.stringify(result.result));
      assert.equal(result.result.decisions.at(-1).choice,choice);
      if(['full','half','delay'].includes(choice))assert.ok(result.result.outcomes.length);
    }
    assert.equal((await api('/api/live/state')).running,true);await api('/api/live/control',{action:'pause'});await until(()=>d.getElementById('toggle-run').textContent.includes('Start'),'pause after decision');
  }
  check('Live: wait/full/half/delay/reject, comparison arithmetic, clock lock, close and Escape with real execution');
  click('[data-page="ledger"]');assert.equal(d.querySelectorAll('#outcome-cards .metric').length,5);
  await post('#export-events','/api/live/events');await until(()=>a.downloads.length,'event export');assert.match(a.downloads.at(-1).filename,/pulp-riot-.*-events.json/);assert.ok(a.downloads.at(-1).blob.size>0);
  assert.ok(d.querySelector('a[href="/operations"]'));
  await sleep(50);assert.deepEqual(a.errors,[]);check('Live: ledger, export download and workbench link; no DOM/runtime errors');
}

async function operationsAudit(root){
  const a=await browser(root,'/operations',['web/operations.js','web/operations-v2.js']);const {w,d,click,input,post,api}=a;
  await until(()=>d.querySelectorAll('#positions tr').length===45,'workbench initial plan');
  for(const page of ['overview','forecast','decisions','inventory','data','scenarios']){click(`[data-view="${page}"]`);assert.ok(d.getElementById(page).classList.contains('active'))}
  await post('#refresh','/api/plan');click('#hero-decisions');assert.ok(d.getElementById('decisions').classList.contains('active'));
  for(const node of d.querySelectorAll('[data-go]')){node.click();assert.ok(d.getElementById(node.dataset.go).classList.contains('active'))}
  for(const id of ['forecast-sku','forecast-depot','forecast-channel'])input('#'+id,d.getElementById(id).options[1].value,'change');assert.ok(d.querySelector('#forecast-chart svg'));
  input('#position-search','Delhi');assert.match(d.getElementById('position-count').textContent,/5 of 45/);input('#position-status','CRITICAL');input('#position-search','');input('#position-status','ALL');
  check('Workbench: six tabs, refresh/shortcuts, three forecast selectors and inventory filters');
  click('[data-view="data"]');input('#kind','route','change');await post('#download-template','/api/template?kind=route');assert.ok(a.downloads.at(-1).blob.size>0);
  const rows=await api('/api/template?kind=route');rows[0].id='audit-route';
  const files=d.getElementById('file');files.required=false;Object.defineProperty(files,'files',{configurable:true,value:[{name:'routes.json',text:async()=>JSON.stringify(rows)}]});files.dispatchEvent(new w.Event('change'));
  const liveBefore=await api('/api/live/state');
  await post('#ingest-form button[type="submit"]','/api/validate');assert.ok(!d.getElementById('import-preview').hidden);
  await post('#confirm-import','/api/ingest');assert.match(d.getElementById('upload-result').textContent,/Imported/);assert.ok(d.getElementById('import-preview').hidden);
  assert.equal((await api('/api/live/state')).revision,liveBefore.revision);
  Object.defineProperty(files,'files',{configurable:true,value:[{name:'broken.json',text:async()=>'{bad'}]});files.dispatchEvent(new w.Event('change'));click('#ingest-form button[type="submit"]');await until(()=>d.getElementById('upload-result').textContent.startsWith('Rejected'),'invalid import');
  const headers=Object.keys(rows[0]);const csv=[headers.join(','),...rows.map(r=>headers.map(h=>'"'+String(r[h]??'').replaceAll('"','""')+'"').join(','))].join('\n');
  Object.defineProperty(files,'files',{configurable:true,value:[{name:'routes.csv',text:async()=>csv}]});files.dispatchEvent(new w.Event('change'));await post('#ingest-form button[type="submit"]','/api/validate');assert.ok(!d.getElementById('import-preview').hidden);
  input('#source','changed-source','change');assert.ok(d.getElementById('import-preview').hidden);
  await post('#poll-external','/api/external/refresh');assert.match(d.getElementById('upload-result').textContent,/Road:/);
  check('Workbench: template download, JSON/CSV preview, import, invalid input, preview invalidation, feed-check button and live-data isolation');
  for(const status of ['APPROVED','REJECTED']){
    await post('#refresh','/api/plan');click('[data-view="decisions"]');const selector=`#decision-list [data-status="${status}"]`;
    click(selector);assert.ok(d.getElementById('decision-dialog').open);click('#cancel-decision');assert.ok(!d.getElementById('decision-dialog').open);
    click(selector);input('#actor','Workbench audit');input('#reason','Isolated UI test');await post('#decision-form button[type="submit"]','/api/decide');await until(()=>!d.getElementById('decision-dialog').open,'workbench decision');
  }
  click('[data-view="scenarios"]');await post('#run-replay','/api/replay');assert.ok(d.querySelector('#replay .scenario-metrics'));
  await sleep(100);assert.deepEqual(a.errors,[]);check('Workbench: approve/reject/cancel, scenario replay, and no DOM/runtime errors');
}

(async()=>{
  let output='';server.stdout.on('data',b=>output+=b);
  await until(()=>output.includes('\n')||server.exitCode!==null,'test server startup');
  if(server.exitCode!==null)throw Error(serverError);
  const root='http://127.0.0.1:'+JSON.parse(output.split('\n')[0]).port;
  await liveAudit(root);await operationsAudit(root);
  fs.mkdirSync('output',{recursive:true});fs.writeFileSync('output/ui_audit.json',JSON.stringify({passed:checks,real_http:true,visual_layout_verified:false},null,2));
  console.log(`PASS ${checks.length} workflow groups against real HTTP; visual layout not verified by jsdom.`);
})().catch(e=>{console.error(e);if(serverError)console.error(serverError);process.exitCode=1}).finally(async()=>{
  for(const c of contexts)c.aborts.abort();
  await sleep(100);
  for(const c of contexts)c.dom.window.close();
  server.kill();
});
