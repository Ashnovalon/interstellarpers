// Lightweight DOM contract check for the browser scripts against a running local API.
// This exercises rendering and event wiring without adding a browser dependency.
'use strict';
const fs=require('node:fs');
const vm=require('node:vm');
const root=process.argv[2]||'http://127.0.0.1:8765';
const html=fs.readFileSync('web/operations.html','utf8');
const ids=[...html.matchAll(/\bid="([^"]+)"/g)].map(m=>m[1]);
if(new Set(ids).size!==ids.length)throw Error('Duplicate HTML IDs');
const callbacks=new Map();
function element(id){
  let markup='';
  return {id,dataset:{},hidden:false,value:'',textContent:'',files:[],disabled:false,
    classList:{toggle(){}},addEventListener(type,fn){callbacks.set(`${id}:${type}`,fn)},
    get innerHTML(){return markup},set innerHTML(value){markup=value;
      if(id.startsWith('forecast-')&&id!=='forecast-chart'&&id!=='forecast-table'){
        const first=value.match(/<option value="([^"]+)"/);if(first)this.value=first[1];
      }}
  };
}
const elements=new Map(ids.map(id=>[id,element(id)]));
elements.get('position-status').value='ALL';
elements.get('kind').value='order';
elements.get('source').value='planner-upload';
const nav=['overview','forecast','decisions','inventory','data','scenarios'].map(view=>{
  const item=element(`nav-${view}`);item.dataset.view=view;return item;
});
const go=['decisions','forecast'].map(target=>{const item=element(`go-${target}`);item.dataset.go=target;return item});
const views=nav.map(x=>elements.get(x.dataset.view));
const document={
  getElementById(id){if(!elements.has(id))throw Error(`Missing element #${id}`);return elements.get(id)},
  querySelectorAll(selector){return selector==='[data-view]'?nav:selector==='[data-go]'?go:selector==='.view'?views:[]},
  querySelector(selector){const match=selector.match(/\[data-view="([^"]+)"\]/);return match?nav.find(x=>x.dataset.view===match[1]):null},
  addEventListener(type,fn){callbacks.set(`document:${type}`,fn)},
  dispatchEvent(event){callbacks.get(`document:${event.type}`)?.(event)}
};
const context=vm.createContext({document,window:{prompt(){return null}},
  sessionStorage:{getItem(){return null},setItem(){}},
  CustomEvent:class{constructor(type,options){this.type=type;this.detail=options.detail}},
  fetch:(path,options)=>fetch(root+path,options),setInterval(){},
  console,URL,Blob,Math,JSON,Number,Intl,Array,Object,String,Error});
vm.runInContext(fs.readFileSync('web/operations.js','utf8'),context,{filename:'operations.js'});
vm.runInContext(fs.readFileSync('web/operations-v2.js','utf8'),context,{filename:'operations-v2.js'});
(async()=>{
  for(let i=0;i<60&&!elements.get('model-card').innerHTML;i++)await new Promise(resolve=>setTimeout(resolve,100));
  for(const id of ['metrics','depot-map','forecast-chart','model-card','forecast-table','positions']){
    if(!elements.get(id).innerHTML)throw Error(`#${id} did not render`);
  }
  if(!elements.get('error').hidden)throw Error(`UI error: ${elements.get('error').textContent}`);
  elements.get('position-search').value='Delhi';
  callbacks.get('position-search:input')();
  if(!elements.get('position-count').textContent.startsWith('5 of 45'))throw Error('Inventory search did not filter five Delhi flavors');
  elements.get('position-search').value='';callbacks.get('position-search:input')();
  const template=await fetch(root+'/api/template?kind=order').then(r=>r.json());
  elements.get('kind').value='order';elements.get('source').value='ui-smoke';
  elements.get('file').files=[{name:'orders.json',text:async()=>JSON.stringify(template)}];
  await callbacks.get('ingest-form:submit')({preventDefault(){}});
  if(elements.get('import-preview').hidden||!elements.get('upload-result').textContent.startsWith('Valid:'))
    throw Error(`Import preview failed: ${elements.get('upload-result').textContent}`);
  console.log('PASS: overview, forecast, model health, inventory search and read-only import preview rendered.');
})().catch(e=>{console.error(e);process.exitCode=1});
