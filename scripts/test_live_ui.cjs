'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {JSDOM,VirtualConsole}=require('jsdom');
const fixture=JSON.parse(fs.readFileSync('output/live_fixture.json','utf8'));
const benchmark=JSON.parse(fs.readFileSync('data/forecast_benchmark.json','utf8'));
let mockState=structuredClone(fixture);mockState.running=true;
const errors=[],calls=[];
const virtualConsole=new VirtualConsole();virtualConsole.on('jsdomError',e=>errors.push(e.message));
const dom=new JSDOM(fs.readFileSync('web/live.html','utf8'),{url:'http://127.0.0.1:8765',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole});
const w=dom.window,d=w.document;
w.structuredClone=structuredClone;
const encoder=new TextEncoder();w.TextDecoder=TextDecoder;
let streamController;
const stream=new ReadableStream({start(controller){streamController=controller}});
w.fetch=async(path,options={})=>{
  const body=options.body?JSON.parse(options.body):null;calls.push({path,body});
  if(path==='/api/live/stream')return {ok:true,body:stream};
  if(path==='/api/live/benchmarks')return {ok:true,json:async()=>({...benchmark,current_source:true})};
  if(path==='/api/live/review/open'){
    mockState.review={id:body.id,version:body.version,was_running:mockState.running};mockState.running=false;mockState.revision++;
    return {ok:true,json:async()=>({state:structuredClone(mockState),review_token:'ui-review-token'})};
  }
  if(path==='/api/live/compare')return {ok:true,json:async()=>({horizon_days:30,as_of_day:mockState.day,
    evidence:{as_of_day:mockState.day,as_of_tick:mockState.tick,observation_age_days:0,forecast_mode:'blend',forecast_revision:mockState.revision,calculations:['Receiver below 14-day cover; preserve donor floor']},branches:[
    {id:'wait',label:'Wait',contribution:100,contribution_vs_wait:0,service_pct:95,unfulfilled:10,writeoffs:0},
    {id:'full',label:'Approve full',contribution:200,contribution_vs_wait:100,service_pct:99,unfulfilled:2,writeoffs:0},
    {id:'half',label:'Approve half',contribution:150,contribution_vs_wait:50,service_pct:97,unfulfilled:5,writeoffs:0},
    {id:'delay',label:'Wait 2 days then act',contribution:125,contribution_vs_wait:25,service_pct:96,unfulfilled:7,writeoffs:0,issue:'The decision window expires before this delayed approval'}]})};
  if(path==='/api/live/decide'){
    mockState.running=mockState.review?.was_running||false;mockState.review=null;mockState.revision++;
  }
  return {ok:true,status:200,json:async()=>structuredClone(mockState)};
};
Object.defineProperty(w.HTMLCanvasElement.prototype,'getBoundingClientRect',{value:()=>({width:700,height:260,left:0,top:0})});
const ctx={scale(){},clearRect(){},beginPath(){},moveTo(...v){assert.ok(v.every(Number.isFinite))},lineTo(...v){assert.ok(v.every(Number.isFinite))},stroke(){},fillText(){},setLineDash(){},arc(){},fill(){}};
w.HTMLCanvasElement.prototype.getContext=()=>ctx;
w.HTMLDialogElement.prototype.showModal=function(){this.setAttribute('open','')};
w.HTMLDialogElement.prototype.close=function(){this.removeAttribute('open')};
const wait=()=>new Promise(resolve=>setTimeout(resolve,35));
function click(selector){const node=d.querySelector(selector);assert.ok(node,`Missing ${selector}`);node.click();return node}
function push(state){mockState=structuredClone(state);streamController.enqueue(encoder.encode(`event: snapshot\ndata: ${JSON.stringify(state)}\n\n`))}
(async()=>{
  w.eval(fs.readFileSync('web/live.js','utf8'));await wait();
  assert.equal(d.querySelectorAll('#market-body tr').length,5);
  assert.match(d.getElementById('business-clock').textContent,/20\d\d/);
  assert.ok(d.querySelectorAll('#urgent-actions .action-card').length);
  click('[data-page="network"]');assert.equal(d.querySelectorAll('.depot-box').length,9);
  d.getElementById('network-search').value='Delhi';d.getElementById('network-search').dispatchEvent(new w.Event('input'));
  assert.equal(d.querySelectorAll('#network-rows tr').length,5);
  click('[data-page="datafeed"]');assert.equal(d.querySelectorAll('#incoming-rows tr').length,135);
  d.getElementById('incoming-channel').value='QC';d.getElementById('incoming-channel').dispatchEvent(new w.Event('change'));
  assert.equal(d.querySelectorAll('#incoming-rows tr').length,45);
  click('[data-page="inputs"]');assert.equal(d.querySelectorAll('.preset-button').length,10);
  d.getElementById('shock-duration').value='3';d.getElementById('shock-recovery').value='2';
  click('[data-preset="heatwave"]');await wait();
  const injection=calls.find(x=>x.path==='/api/live/inject');
  assert.deepEqual(injection.body.lifecycle,{duration_days:3,recovery_days:2});
  const trend=d.querySelector('[name="trend"]');trend.value='2.3';trend.dispatchEvent(new w.Event('input',{bubbles:true}));
  const next=structuredClone(fixture);next.revision++;next.inputs.trend=5.5;push(next);await wait();
  assert.equal(trend.value,'2.3','Stream must not overwrite an unfinished scenario edit');
  next.last_input_change={message:'Heatwave lifts demand',day:next.day-.25,tick:next.tick-1,changes:[{field:'heatwave',before:1,after:1.25}],applied_inputs:{...next.inputs,heatwave:1.25},operating_before:{generated_demand_per_day:100,forecast_per_day:105,unfulfilled_rate:0,expired_bottles:0},operating_after:{generated_demand_per_day:125,forecast_per_day:105,unfulfilled_rate:0,expired_bottles:0}};
  next.revision++;push(next);await wait();
  const options=[...d.getElementById('impact-metric').options];
  assert.equal(options.length,3,'Demand disruption should show three useful outcome measures');
  assert.equal(new Set(options.map(x=>x.textContent)).size,options.length,'No duplicate measures');
  assert.match(d.getElementById('impact-legend').textContent,/Observed demand/);
  const option=options[0];next.revision++;push(next);await wait();
  assert.equal(d.getElementById('impact-metric').options[0],option,'Stream must preserve the open dropdown');
  d.getElementById('impact-chart').dispatchEvent(new w.MouseEvent('mousemove',{clientX:300}));
  d.getElementById('impact-chart').dispatchEvent(new w.MouseEvent('mouseleave'));
  click('[data-page="decisions"]');
  const bottomButton=[...d.querySelectorAll('#decision-cards [data-review]')].at(-1);
  bottomButton.focus();bottomButton.dispatchEvent(new w.MouseEvent('pointerdown',{bubbles:true}));
  next.revision++;push(next);await wait();
  assert.equal(d.querySelector(`#decision-cards [data-review="${bottomButton.dataset.review}"]`),bottomButton,'Bottom decision button must survive a snapshot between pointerdown and click');
  assert.equal(d.activeElement,bottomButton,'Keyboard focus must survive snapshots');
  bottomButton.click();await wait();
  assert.ok(d.getElementById('review-dialog').open);
  assert.equal(d.querySelectorAll('.branch-card').length,4);
  assert.match(d.getElementById('comparison-title').textContent,/30-day/);
  assert.match(d.getElementById('review-evidence').textContent,/preserve donor floor/);
  assert.match(d.querySelector('.branch-card').textContent,/30-day contribution/);
  assert.ok(calls.find(x=>x.path==='/api/live/review/open'));
  assert.equal(d.getElementById('toggle-run').textContent,'Paused for review');
  click('[data-branch="delay"]');assert.match(d.getElementById('review-choice-summary').textContent,/unavailable.*expires/);
  assert.ok(d.getElementById('approve-action').disabled,'Unavailable delayed branch cannot execute');
  d.getElementById('decision-form').dispatchEvent(new w.Event('submit',{cancelable:true,bubbles:true}));await wait();
  assert.equal(d.getElementById('review-error').hidden,false);
  click('[data-branch="half"]');assert.equal(d.querySelector('[data-branch="half"]').getAttribute('aria-pressed'),'true');
  d.getElementById('decision-actor').value='UI operator';d.getElementById('decision-reason').value='Reviewed forecast and batch age';d.getElementById('decision-checks').checked=true;
  d.getElementById('decision-form').dispatchEvent(new w.Event('submit',{cancelable:true,bubbles:true}));await wait();
  const decision=calls.find(x=>x.path==='/api/live/decide');assert.ok(decision);
  assert.equal(decision.body.actor,'UI operator');assert.equal(decision.body.checks_confirmed,true);
  assert.equal(decision.body.choice,'half');assert.equal(decision.body.review_token,'ui-review-token');
  assert.equal(d.getElementById('review-dialog').open,false);
  click('[data-page="ledger"]');assert.equal(d.querySelectorAll('#outcome-cards .metric').length,5);
  click('[data-page="model"]');await wait();assert.ok(d.getElementById('model-details').textContent.includes('Gradient'));
  assert.equal(d.querySelectorAll('#forecast-benchmarks tbody tr').length,4);
  assert.match(d.getElementById('forecast-benchmarks').textContent,/Blend versus nowcast/);
  click('[data-page="board"]');
  d.getElementById('chart-mode').value='stock_cover';d.getElementById('chart-mode').dispatchEvent(new w.Event('change'));
  assert.match(d.getElementById('chart-title').textContent,/stock cover/);
  assert.deepEqual(errors,[]);
  console.log('PASS: streamed rendering, incoming records, protected edits, server-side review pause, four selectable paths and half-quantity execution request.');
  dom.window.close();
})().catch(error=>{console.error(error);dom.window.close();process.exitCode=1});
