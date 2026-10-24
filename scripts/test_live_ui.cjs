'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {JSDOM,VirtualConsole}=require('jsdom');
const fixture=JSON.parse(fs.readFileSync('output/live_fixture.json','utf8'));
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
  if(path==='/api/live/review/open'){
    mockState.review={id:body.id,version:body.version,was_running:mockState.running};mockState.running=false;mockState.revision++;
    return {ok:true,json:async()=>({state:structuredClone(mockState),review_token:'ui-review-token'})};
  }
  if(path==='/api/live/compare')return {ok:true,json:async()=>({branches:[
    {id:'wait',label:'Wait',contribution:100,contribution_vs_wait:0,service_pct:95,unfulfilled:10,writeoffs:0},
    {id:'full',label:'Approve full',contribution:200,contribution_vs_wait:100,service_pct:99,unfulfilled:2,writeoffs:0},
    {id:'half',label:'Approve half',contribution:150,contribution_vs_wait:50,service_pct:97,unfulfilled:5,writeoffs:0},
    {id:'delay',label:'Wait 2 days then act',contribution:125,contribution_vs_wait:25,service_pct:96,unfulfilled:7,writeoffs:0}]})};
  if(path==='/api/live/decide'){
    mockState.running=mockState.review?.was_running||false;mockState.review=null;mockState.revision++;
  }
  return {ok:true,status:200,json:async()=>structuredClone(mockState)};
};
Object.defineProperty(w.HTMLCanvasElement.prototype,'getBoundingClientRect',{value:()=>({width:700,height:260,left:0,top:0})});
const ctx={scale(){},clearRect(){},beginPath(){},moveTo(){},lineTo(){},stroke(){},fillText(){},setLineDash(){},arc(){},fill(){}};
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
  const trend=d.querySelector('[name="trend"]');trend.value='2.3';trend.dispatchEvent(new w.Event('input',{bubbles:true}));
  const next=structuredClone(fixture);next.revision++;next.inputs.trend=5.5;push(next);await wait();
  assert.equal(trend.value,'2.3','Stream must not overwrite an unfinished scenario edit');
  click('[data-page="decisions"]');click('#decision-cards [data-review]');await wait();
  assert.ok(d.getElementById('review-dialog').open);
  assert.equal(d.querySelectorAll('.branch-card').length,4);
  assert.ok(calls.find(x=>x.path==='/api/live/review/open'));
  assert.equal(d.getElementById('toggle-run').textContent,'Paused for review');
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
  click('[data-page="model"]');assert.ok(d.getElementById('model-details').textContent.includes('Gradient'));
  assert.deepEqual(errors,[]);
  console.log('PASS: streamed rendering, incoming records, protected edits, server-side review pause, four selectable paths and half-quantity execution request.');
  dom.window.close();
})().catch(error=>{console.error(error);dom.window.close();process.exitCode=1});
