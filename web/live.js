'use strict';
const el=id=>document.getElementById(id);
const escapeHtml=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const number=v=>Math.round(Number(v||0)).toLocaleString('en-IN');
const money=v=>`${v<0?'−':''}₹${Math.abs(v)>=1e7?(Math.abs(v)/1e7).toFixed(2)+' cr':Math.abs(v)>=1e5?(Math.abs(v)/1e5).toFixed(2)+' L':number(Math.abs(v))}`;
const rate=v=>v==null?'—':number(v);
const badge=(text,type='')=>`<span class="tag ${type}">${escapeHtml(text)}</span>`;
let state=null,page='board',inputDirty=false,selectedAction=null,selectedBranch=null,branchComparison=null,lastMessage=0,hoverIndex=null,commandBusy=false;
let accessToken=sessionStorage.getItem('control-tower-token')||'';
let lastMarket={};

async function api(path,body,retry=true){
  const headers={};if(accessToken)headers.Authorization=`Bearer ${accessToken}`;
  if(body!==undefined)headers['Content-Type']='application/json';
  const response=await fetch(path,{method:body===undefined?'GET':'POST',headers,body:body===undefined?undefined:JSON.stringify(body)});
  if(response.status===401&&retry){
    const token=window.prompt('Enter this local server’s configured API token.');
    if(token){accessToken=token;sessionStorage.setItem('control-tower-token',token);return api(path,body,false)}
  }
  const result=await response.json();
  if(!response.ok)throw new Error(result.error||`HTTP ${response.status}`);
  return result;
}
function showError(message){el('app-error').textContent=message||'';el('app-error').hidden=!message;}
async function command(path,body){
  if(commandBusy){const message='Another update is being applied. Wait for its confirmation, then retry.';showError(message);throw new Error(message)}
  commandBusy=true;showError('');
  try{const next=await api(path,body);render(next);return next}
  catch(error){showError(error.message);throw error}
  finally{commandBusy=false}
}
function metric(label,value,note,tone=''){
  return `<div class="metric"><span class="metric-label">${escapeHtml(label)}</span><strong class="metric-value ${tone}">${escapeHtml(value)}</strong><span class="metric-note">${escapeHtml(note)}</span></div>`;
}
function openPage(name){
  page=name;
  document.querySelectorAll('[data-page]').forEach(x=>x.classList.toggle('active',x.dataset.page===name));
  document.querySelectorAll('.page').forEach(x=>x.classList.toggle('active',x.id===`page-${name}`));
  if(state)renderPage();
  requestAnimationFrame(drawCharts);
}
document.querySelectorAll('[data-page]').forEach(x=>x.addEventListener('click',()=>openPage(x.dataset.page)));
document.querySelectorAll('[data-open]').forEach(x=>x.addEventListener('click',()=>openPage(x.dataset.open)));
if(localStorage.getItem('pulp-live-welcome')==='dismissed')el('welcome').hidden=true;
el('dismiss-welcome').addEventListener('click',()=>{el('welcome').hidden=true;localStorage.setItem('pulp-live-welcome','dismissed')});

function setSelect(id,values){
  const select=el(id),old=select.value;
  select.innerHTML=values.map(value=>`<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join('');
  if(values.includes(old))select.value=old;
}
function render(next){
  if(!next?.run_id)return;
  if(state&&state.run_id===next.run_id&&state.revision>next.revision)return;
  const freshRun=!state||state.run_id!==next.run_id;
  state=next;
  if(freshRun){
    lastMarket={};hoverIndex=null;
    const flavors=state.market.map(x=>x.sku);
    setSelect('chart-flavor',['ALL',...flavors]);setSelect('network-flavor',flavors);
    setSelect('forecast-flavor',flavors);setSelect('input-sku',flavors);setSelect('incoming-sku',['ALL',...flavors]);
    renderPresets();inputDirty=false;
  }
  el('business-clock').textContent=state.business_time;
  el('run-details').textContent=`Day ${state.day.toFixed(2)} / 112 · Tick ${state.tick} · ${state.scenario==='guided'?'Guided season':'Sandbox'} · Seed ${state.seed}`;
  el('toggle-run').textContent=state.review?'Paused for review':state.day>=112?'Season complete':state.running?'Ⅱ Pause':'▶ Start live';
  el('toggle-run').disabled=Boolean(state.review)||state.day>=112;
  el('step-run').disabled=state.running||state.day>=112||Boolean(state.review);
  el('sim-speed').value=String(state.days_per_tick);
  el('nav-pending').textContent=state.actions.length;
  el('metric-strip').innerHTML=
    metric('Operating contribution',money(state.metrics.contribution),'Scenario estimate after modeled costs',state.metrics.contribution>=0?'positive':'negative')+
    metric('Lift vs no intervention',money(state.metrics.contribution_lift),'Same opening stock and demand',state.metrics.contribution_lift>=0?'positive':'negative')+
    metric('Orders served',`${state.metrics.service_pct.toFixed(2)}%`,`${number(state.metrics.unfulfilled)} bottles unfulfilled`,state.metrics.service_pct<98?'negative':'positive')+
    metric('Critical stock positions',state.metrics.critical_positions,'Below 14 forecast days of cover',state.metrics.critical_positions?'negative':'')+
    metric('Uncommitted cash',money(state.metrics.budget_remaining),'After rollout reserve & approved commitments','neutral');
  renderMarket();renderUrgent();renderSources();renderTape();
  renderInputConfirmation();
  if(!inputDirty)syncInputs();
  renderPage();updateReview();
  el('footer-state').textContent=`Run ${state.run_id} · Revision ${state.revision} · Bottle balance ${state.metrics.bottle_conservation_error===0?'verified':'ERROR'}`;
  requestAnimationFrame(drawCharts);
  if(!selectedAction&&state.review){
    try{const saved=JSON.parse(sessionStorage.getItem('pulp-active-review')||'null');if(saved?.run_id===state.run_id&&saved.id===state.review.id)openReview(saved.id,saved.token)}catch{}
  }
}
function miniSpark(values){
  if(values.length<2)return '<span class="subtle">Waiting for ticks</span>';
  const min=Math.min(...values),max=Math.max(...values),spread=Math.max(max-min,1);
  const points=values.map((v,i)=>`${(i*94/(values.length-1)).toFixed(1)},${(25-(v-min)*22/spread).toFixed(1)}`).join(' ');
  return `<svg class="mini-spark" viewBox="0 0 96 28" aria-hidden="true"><polyline points="${points}" fill="none" stroke="#a293ff" stroke-width="1.8"/></svg>`;
}
function renderMarket(){
  const flavorClasses=['mango','guava','passion','dragon','blend'];
  el('market-body').innerHTML=state.market.map((row,index)=>{
    const last=lastMarket[row.sku],flash=last===undefined||last===row.forecast?'':row.forecast>last?'flash-up':'flash-down';
    lastMarket[row.sku]=row.forecast;
    const history=state.tape.slice(-35).map(x=>x.sku[row.sku].forecast);
    return `<tr class="${flash}" data-flavor="${escapeHtml(row.sku)}"><td><div class="flavor ${flavorClasses[index]}"><i></i>${escapeHtml(row.sku)}</div></td><td>${number(row.forecast)}</td><td class="${row.change_pct>=0?'neutral':'negative'}">${row.change_pct>=0?'↗ +':'↘ '}${row.change_pct.toFixed(1)}%</td><td>${rate(row.actual)}</td><td>${row.cover.toFixed(1)} d</td><td>${badge(state.inputs.feed_outage?'STALE':row.critical?`${row.critical} CRITICAL`:'HEALTHY',state.inputs.feed_outage?'amber':row.critical?'red':'green')}</td><td>${miniSpark(history)}</td></tr>`;
  }).join('');
}
function actionCard(action,compact=false){
  const urgent=action.remaining_days<=1;
  const progress=Math.max(0,Math.min(100,100*action.remaining_days/Math.max(action.deadline-action.created,.25)));
  const cash=action.params.cash;
  return `<article class="action-card"><div class="action-top"><h3>${escapeHtml(action.title)}</h3><span class="deadline ${urgent?'urgent':''}">${action.wall_seconds.toFixed(0)}s ${state.running?'left':'on clock'}</span></div>${compact?'':`<p>${escapeHtml(action.why)}</p>`}<progress class="deadline-progress" value="${progress.toFixed(1)}" max="100" aria-label="Decision time remaining"></progress><div class="action-bottom"><span>${cash?money(cash)+' commitment':'Allocation / evidence decision'}${compact?'':`<br>${escapeHtml(action.role)} · lead ${action.lead}d`}</span><button class="button ${urgent?'primary':''}" data-review="${escapeHtml(action.id)}">Compare & decide</button></div></article>`;
}
function renderUrgent(){
  el('urgent-actions').innerHTML=state.actions.length?state.actions.slice(0,3).map(x=>actionCard(x,true)).join(''):
    '<div class="empty-state">No pending intervention.<br>Start the clock or introduce a disruption.</div>';
}
function renderSources(){
  el('source-health').innerHTML=`<span>Orders / stock: <b class="${state.inputs.feed_outage?'negative':'positive'}">${state.inputs.feed_outage?'STOPPED':'OBSERVED'}</b></span><span>Road: <b class="${state.inputs.road_closed?'negative':'positive'}">${state.inputs.road_closed?'CLOSED':'OPEN'}</b></span><span>Managed plant capacity: <b>${Math.round((state.effective_availability??state.inputs.plant_availability)*100)}%</b></span><span>Evidence age: <b>${state.feed_age_days.toFixed(2)}d</b></span>`;
}
function renderTape(){
  el('event-tape').innerHTML=state.events.slice(-12).reverse().map(x=>`<div class="tape-row"><span class="tape-time">D${x.day.toFixed(2)}</span><span class="event-kind">${escapeHtml(x.kind)}</span><span class="tape-message">${escapeHtml(x.message)}</span></div>`).join('')||'<div class="empty-state">Waiting for events</div>';
}
function renderPage(){
  if(page==='decisions')renderDecisions();
  else if(page==='network')renderNetwork();
  else if(page==='ledger')renderLedger();
  else if(page==='model')renderModel();
  else if(page==='datafeed')renderIncoming();
}

function renderInputConfirmation(){
  const change=state.last_input_change,box=el('change-confirmation');
  if(!change){box.hidden=true;return}
  const applied=change.changes.map(x=>`${x.field}: ${x.before} → ${x.after}`).join(' · ');
  const observed=state.latest_inputs&&state.latest_inputs.tick>change.tick;
  box.hidden=false;box.innerHTML=`<b>${escapeHtml(change.message)}</b> · ${escapeHtml(applied||`held pulp ${number(change.held_pulp_kg)} kg`)}<br><span>${observed?`Batch #${state.latest_inputs.tick} is available for inspection.`:'Parameters are applied. Start or Step the clock to generate the next affected batch.'}</span> <button class="text-button" data-show-inputs>See incoming data →</button>`;
}
function renderIncoming(){
  const batch=state.latest_inputs;
  el('input-batch-stats').innerHTML=metric('Latest input batch',batch?'#'+batch.tick:'Waiting','135 potential order series per tick')+
    metric('Business interval',batch?`${(batch.dt*24).toFixed(1)} hours`:'—','Wall clock delivers one batch/second')+
    metric('Requested this interval',batch?number(batch.requested):'—','Orders before stock constraints')+
    metric('Fulfilled this interval',batch?number(batch.fulfilled):'—','Actual eligible stock consumed')+
    metric('Feed visibility',batch?(batch.observed?'OBSERVED':'HIDDEN / STOPPED'):'—','Hidden records are audit truth only',batch&&!batch.observed?'negative':'positive');
  const change=state.last_input_change;
  el('input-change-detail').innerHTML=change?`<p class="subtle"><b>${escapeHtml(change.message)}</b> at D${change.day.toFixed(2)}. ${change.changes.map(x=>`${escapeHtml(x.field)}: ${escapeHtml(x.before)} → ${escapeHtml(x.after)}`).join(' · ')||`Pulp held: ${number(change.held_pulp_kg)} kg`}</p>`:'<p class="subtle">No manual disruption yet. Apply one in Disruption studio and its before/after values will appear here.</p>';
  el('input-parameters').innerHTML=Object.entries(batch?.parameters||state.inputs).map(([k,v])=>`<div><small>${escapeHtml(k.replaceAll('_',' '))}</small><strong>${escapeHtml(v)}</strong></div>`).join('');
  el('input-batch-label').textContent=batch?`D${batch.day_start.toFixed(2)} → D${batch.day_end.toFixed(2)} · ${batch.generator_version}`:'Start or Step to create an incoming batch';
  const sku=el('incoming-sku').value,channel=el('incoming-channel').value,query=el('incoming-search').value.trim().toLowerCase();
  const rows=(batch?.rows||[]).filter(x=>(sku==='ALL'||x.sku===sku)&&(channel==='ALL'||x.channel===channel)&&`${x.city} ${x.depot}`.toLowerCase().includes(query));
  el('incoming-rows').innerHTML=rows.map(x=>`<tr><td><details><summary>${escapeHtml(x.sku)} · ${escapeHtml(x.city)}</summary><div class="factor-detail">${Object.entries(x.factors).map(([k,v])=>`${escapeHtml(k)} × ${v.toFixed(5)}`).join('<br>')}<br><b>${x.baseline_daily.toFixed(3)} × ${Object.values(x.factors).reduce((a,b)=>a*b,1).toFixed(6)} × ${batch.dt} days = ${x.requested} requested (rounded)</b><br>${escapeHtml(x.id)}</div></details></td><td>${escapeHtml(x.channel)}</td><td>${number(x.baseline_daily)}</td><td>${number(x.daily_rate)}</td><td>${number(x.requested)}</td><td>${number(x.fulfilled)}</td><td>${x.factors.attention.toFixed(2)}</td><td>${x.factors.weather.toFixed(2)}</td><td>${(x.factors.network_regime*x.factors.regional_regime*x.factors.product_regime).toFixed(3)}</td><td>${badge(x.observed?'OBSERVED':'NOT OBSERVED',x.observed?'green':'amber')}</td></tr>`).join('')||'<tr><td colspan="10">No matching incoming records. Start or Step the simulation to generate a batch.</td></tr>';
  el('incoming-supply').innerHTML=`<p class="subtle">Road ${state.inputs.road_closed?'closed':'open'} · managed plant capacity ${Math.round(state.effective_availability*100)}% · traffic +${state.inputs.traffic_delay_days}d · imported pulp +${state.inputs.import_delay_days}d · held pulp ${number(state.metrics.held_pulp_kg)} kg.</p><div class="table-scroll"><table><thead><tr><th>Ingredient</th><th>Usable kg</th><th>Forecast kg/day</th><th>Cover</th><th>Unblocked inbound kg</th></tr></thead><tbody>${state.materials.map(x=>`<tr><td>${escapeHtml(x.material)}</td><td>${number(x.kg)}</td><td>${number(x.daily)}</td><td>${x.cover.toFixed(2)}d</td><td>${number(x.inbound)}</td></tr>`).join('')}</tbody></table></div>`;
}
function renderDecisions(){
  const selected=el('action-filter').value;
  const groups={TRANSFER:['TRANSFER','GT_TRANSFER'],SUPPLY:['AIR','AIR_DRAGON','BUFFER'],CAPACITY:['REPLAN','COPACKER','REPAIR_PLANT'],QUALITY:['LAB_TEST','RELEASE_QA','RESTORE_FEED']};
  const actions=state.actions.filter(x=>selected==='ALL'||groups[selected]?.includes(x.kind));
  el('decision-count').textContent=`${actions.length} of ${state.actions.length} pending`;
  el('decision-cards').innerHTML=actions.map(x=>actionCard(x)).join('')||'<div class="empty-state">No current recommendations in this group.</div>';
}
function renderNetwork(){
  const closed=state.inputs.road_closed;
  el('route-status').innerHTML=`<div class="section-head"><div><h2>Passionfruit cooperative → plants</h2><span class="subtle">Sole approved road · 3-day normal inbound lead · no approved detour</span></div>${badge(closed?'CONFIRMED SIMULATED CLOSURE':'SIMULATED OPEN',closed?'red':'green')}</div><div class="route-path"><div class="route-node">Hill cooperative<small>Passionfruit pulp</small></div><div class="route-line ${closed?'closed':''}"><span>${closed?'⊘ road blocked':'→ contracted receipts'}</span></div><div class="route-node">Two plants<small>${Math.round((state.effective_availability??state.inputs.plant_availability)*100)}% available capacity</small></div><div class="route-line"><span>+${state.inputs.traffic_delay_days}d traffic</span></div><div class="route-node">Nine depots<small>Batch freshness checked</small></div></div><p class="footnote">${closed?`Expected reopening in ${Math.max(0,state.road_reopens-state.day).toFixed(1)} business days. Road receipts remain blocked; air requires an explicit decision.`:'Normal booked road receipts can arrive. Public map data is not connected to this synthetic route.'}</p>`;
  const sku=el('network-flavor').value;
  el('depot-grid').innerHTML=state.positions.filter(x=>x.sku===sku).map(x=>`<div class="depot-box ${x.status==='CRITICAL'?'critical':x.status==='STALE'?'stale':''}"><strong>${escapeHtml(x.city)}</strong><small>${escapeHtml(x.region)} · ${escapeHtml(x.depot)}</small><span class="cover">${x.cover.toFixed(1)}d</span><small>${number(x.quantity)} bottles · ${x.status}</small></div>`).join('');
  el('material-list').innerHTML=state.materials.map(x=>`<div class="material-row"><div class="material-top"><b>${escapeHtml(x.material)}</b><span class="${x.cover<14?'negative':''}">${x.cover.toFixed(1)} days</span></div><progress class="material-progress ${x.cover<14?'low':''}" max="42" value="${Math.min(42,x.cover)}" aria-label="${escapeHtml(x.material)} cover"></progress><small>${number(x.kg)} kg available · ${number(x.daily)} kg/day · ${number(x.inbound)} kg unblocked inbound</small></div>`).join('');
  const query=el('network-search').value.trim().toLowerCase();
  el('network-rows').innerHTML=state.positions.filter(x=>`${x.sku} ${x.city}`.toLowerCase().includes(query)).sort((a,b)=>a.cover-b.cover).map(x=>`<tr><td>${escapeHtml(x.city)}<br><span class="subtle">${escapeHtml(x.sku)}</span></td><td>${number(x.quantity)}</td><td>${number(x.daily)}</td><td>${x.cover.toFixed(1)} d</td><td>${number(x.eligible)}</td><td>${number(x.inbound)}</td><td>${badge(x.status,x.status==='CRITICAL'?'red':x.status==='STALE'?'amber':'green')}</td></tr>`).join('')||'<tr><td colspan="7">No matching positions</td></tr>';
}
function renderPresets(){
  el('preset-grid').innerHTML=Object.entries(state.presets).map(([id,label],i)=>`<button type="button" class="preset-button" data-preset="${escapeHtml(id)}"><small>EVENT ${String(i+1).padStart(2,'0')}</small>${escapeHtml(label)}</button>`).join('');
}
function syncInputs(){
  const form=el('inputs-form');
  for(const [name,value] of Object.entries(state.inputs)){
    const field=form.elements.namedItem(name);if(!field)continue;
    if(field.type==='checkbox')field.checked=value;else field.value=String(value);
  }
  updateInputLabels();
}
function updateInputLabels(){
  document.querySelectorAll('[data-output]').forEach(output=>{
    const name=output.dataset.output,value=Number(el('inputs-form').elements.namedItem(name).value);
    output.textContent=['conversion','plant_availability','competitor_pressure'].includes(name)?`${Math.round(value*100)}%`:`${value.toFixed(2)}×`;
  });
}
function renderLedger(){
  const m=state.metrics;
  el('outcome-cards').innerHTML=metric('Managed contribution',money(m.contribution),'Same contribution and cost rules','positive')+
    metric('No-intervention policy',money(m.baseline_contribution),'Same exogenous demand and disruptions')+
    metric('Your contribution lift',money(m.contribution_lift),'Can be negative after a poor choice',m.contribution_lift>=0?'positive':'negative')+
    metric('Expired bottles',number(m.writeoffs),'Actual simulated batch expiry',m.writeoffs?'negative':'')+
    metric('Incremental operating costs',money(m.incremental_cost),'Freight, tests, co-packer & holding','neutral');
  el('budget-detail').innerHTML=`<div class="budget-grid"><div><span>First-year ceiling</span><strong>${money(m.budget)}</strong></div><div><span>Illustrative build/run reserve</span><strong>${money(m.rollout_reserved)}</strong></div><div><span>Buffer working capital committed</span><strong>${money(m.cash_buffer)}</strong></div><div><span>Uncommitted headroom</span><strong class="neutral">${money(m.budget_remaining)}</strong></div></div><p class="footnote">Maximum co-packer premium is reserved on approval. Costs are charged only when production occurs. Buffer purchases remain inventory working capital; contribution already includes ordinary variable costs. All prices beyond case facts are declared simulation assumptions.</p>`;
  el('decision-ledger').innerHTML=state.decisions.slice().reverse().map(x=>`<tr><td>D${x.day.toFixed(2)}</td><td>${escapeHtml(x.title)}<br><span class="subtle">${escapeHtml(x.reason)}</span></td><td>${escapeHtml(x.actor)}</td><td>${badge(x.status,['EXPIRED','REJECTED','FAILED'].includes(x.status)?'red':['RECEIVED','COMPLETED'].includes(x.status)?'green':'purple')}</td><td>${money(x.cash||0)}</td><td>${x.eta==null?'—':`D${x.eta.toFixed(2)}`}</td></tr>`).join('')||'<tr><td colspan="6">No decisions yet. Open the decision desk to choose an intervention.</td></tr>';
  el('shipment-ledger').innerHTML=state.shipments.slice(-15).reverse().map(x=>`<div class="ledger-entry">${number(x.quantity)} ${escapeHtml(x.sku)}<small>${escapeHtml(x.from)} → ${escapeHtml(x.to)} · expected D${x.eta.toFixed(2)} · ${escapeHtml(x.type)}</small></div>`).join('')||'<div class="empty-state">No goods in transit</div>';
  el('receipt-ledger').innerHTML=state.receipts.slice(-15).reverse().map(x=>`<div class="ledger-entry">${number(x.kg)} kg ${escapeHtml(x.material)} ${state.inputs.road_closed&&x.material==='passionfruit'&&x.mode==='ROAD'?badge('BLOCKED','red'):''}<small>${escapeHtml(x.mode)} · expected D${x.eta.toFixed(2)} · ${escapeHtml(x.type||'PRE-BOOKED CONTRACT')}</small></div>`).join('')||'<div class="empty-state">No ingredient receipts booked</div>';
}
function renderModel(){
  const model=state.model;
  const scored=state.market.filter(x=>x.online_wape!=null);
  el('model-details').innerHTML=[['Model',model.name],['Artifact',model.version||'Not trained'],['Synthetic held-out WAPE',model.test_wape==null?'Not available':model.test_wape+'%'],['Active daily models',`${model.positions} / ${model.total_positions}`],['Generated training rows',number(model.training_rows)],['Online evaluation',scored.length?'Completed-day scores available':'Waiting for a complete observed day'],['Feed state',state.inputs.feed_outage?'Stopped; estimates are stale':'Observed synthetic order batches']].map(([label,value])=>`<div class="model-row"><b>${escapeHtml(label)}</b><span>${escapeHtml(value)}</span></div>`).join('')+`<p class="footnote">${escapeHtml(model.runtime)}</p>`;
  el('model-details').innerHTML+=`<div class="table-scroll"><table><thead><tr><th>Completed-day WAPE</th><th>Trained only</th><th>Adaptive at day start</th></tr></thead><tbody>${state.market.map(x=>`<tr><td>${escapeHtml(x.sku)}</td><td>${x.online_wape==null?'pending':x.online_wape.toFixed(2)+'%'}</td><td>${x.adaptive_wape==null?'pending':x.adaptive_wape.toFixed(2)+'%'}</td></tr>`).join('')}</tbody></table></div>`;
  el('model-details').innerHTML+=`<p class="footnote"><b>Inputs:</b> completed 14-day requested-order history, lag/rolling statistics, target weekday and forecast horizon. Intraday requests divided by the exact interval feed the adaptive nowcast.<br><b>Outputs:</b> demand per day for each flavor/depot/channel and the next 14 daily estimates. The decision engine then checks inventory, shelf life, ingredients, transport, capacity and cash.<br><b>Quality:</b> ${model.test_wape}% is held-out synthetic error, not real-company accuracy. Current live scenarios have independent demand variation; use the online scores above to judge this run.</p>`;
  el('assumption-list').innerHTML=state.assumptions.map((text,i)=>`<div class="assumption-row"><b>${String(i+1).padStart(2,'0')}</b><span>${escapeHtml(text)}</span></div>`).join('');
  const row=state.market.find(x=>x.sku===el('forecast-flavor').value);
  el('horizon-summary').textContent=row?`${row.sku}: ${number(state.forecast_curves[row.sku][0])} bottles/day now; ${number(state.forecast_curves[row.sku][13])} at D+13. Live trained-only daily WAPE: ${row.online_wape==null?'pending':row.online_wape+'%'}. No calibrated live uncertainty band is claimed.`:'';
}

function canvasPlot(canvas,series,xValues,{currency=false,hover=null}={}){
  const rect=canvas.getBoundingClientRect();if(!rect.width||!rect.height)return;
  const ratio=Math.min(window.devicePixelRatio||1,2),w=rect.width,h=rect.height;
  canvas.width=Math.round(w*ratio);canvas.height=Math.round(h*ratio);
  const ctx=canvas.getContext('2d');ctx.scale(ratio,ratio);ctx.clearRect(0,0,w,h);
  const padding={left:55,right:15,top:15,bottom:27};const pw=w-padding.left-padding.right,ph=h-padding.top-padding.bottom;
  const values=series.flatMap(s=>s.values).filter(v=>v!=null&&Number.isFinite(v));
  if(!values.length)return;
  let lo=Math.min(...values),hi=Math.max(...values);const span=Math.max(hi-lo,Math.abs(hi)*.04,1);lo=Math.max(currency?-Infinity:0,lo-span*.15);hi+=span*.15;
  const x=i=>padding.left+i*pw/Math.max(xValues.length-1,1),y=v=>padding.top+ph-(v-lo)*ph/Math.max(hi-lo,1);
  ctx.font='9px Segoe UI';ctx.textAlign='right';ctx.lineWidth=1;
  for(let i=0;i<4;i++){
    const v=lo+(hi-lo)*i/3,yy=y(v);ctx.strokeStyle='#223047';ctx.beginPath();ctx.moveTo(padding.left,yy);ctx.lineTo(w-padding.right,yy);ctx.stroke();
    ctx.fillStyle='#7185a4';ctx.fillText(currency?money(v):v>=1e5?(v/1e5).toFixed(1)+'L':number(v),padding.left-8,yy+3);
  }
  ctx.textAlign='center';[0,Math.floor((xValues.length-1)/2),xValues.length-1].forEach(i=>{ctx.fillText(`D${Number(xValues[i]||0).toFixed(1)}`,x(i),h-7)});
  for(const item of series){
    ctx.strokeStyle=item.color;ctx.lineWidth=1.9;ctx.setLineDash(item.dashed?[4,4]:[]);ctx.beginPath();let open=false;
    item.values.forEach((v,i)=>{if(v==null){open=false;return}if(!open){ctx.moveTo(x(i),y(v));open=true}else ctx.lineTo(x(i),y(v))});ctx.stroke();ctx.setLineDash([]);
  }
  if(hover!=null&&hover<xValues.length){
    ctx.strokeStyle='#8290aa66';ctx.beginPath();ctx.moveTo(x(hover),padding.top);ctx.lineTo(x(hover),h-padding.bottom);ctx.stroke();
    for(const item of series){const value=item.values[hover];if(value==null)continue;ctx.fillStyle=item.color;ctx.beginPath();ctx.arc(x(hover),y(value),3,0,Math.PI*2);ctx.fill()}
  }
}
function drawCharts(){
  if(!state)return;
  if(page==='board'){
    const mode=el('chart-mode').value,sku=el('chart-flavor').value,tape=state.tape;
    el('chart-empty').hidden=tape.length>0;
    const titles={demand:'Live demand vs prediction',contribution:'Cumulative contribution: managed vs no intervention',tick_revenue:'Gross sales in each business interval',tick_contribution:'Operating contribution in each interval',unfulfilled_rate:'Unfulfilled demand: daily rate'};
    el('chart-title').textContent=titles[mode];
    const chosen=tape.map(x=>sku==='ALL'?x:x.sku[sku]);
    const series=mode==='contribution'?[{values:tape.map(x=>x.contribution),color:'#48d5a1'},{values:tape.map(x=>x.baseline),color:'#7d90ad',dashed:true}]:mode==='demand'?[{values:chosen.map(x=>x.forecast),color:'#a293ff'},{values:chosen.map(x=>x.actual),color:'#48d5a1'}]:[{values:tape.map(x=>x[mode]??null),color:mode==='unfulfilled_rate'?'#ff7a8e':'#48d5a1'}];
    el('chart-legend').innerHTML=mode==='contribution'?'<span class="actual">Managed contribution</span><span class="base">No intervention</span>':mode==='demand'?'<span class="model">Trained model + adaptive nowcast</span><span class="actual">Observed requested daily rate</span>':`<span class="actual">${escapeHtml(titles[mode])}</span>`;
    const currency=['contribution','tick_revenue','tick_contribution'].includes(mode);
    el('chart-caption').textContent=mode==='contribution'?'Cumulative totals usually rise as fulfilled sales accumulate. Use interval views to see deteriorating performance.':mode.startsWith('tick_')?'Each point covers the selected business interval. Values can fall; contribution can be negative after costs.':'Observed data and prediction update from each incoming batch.';
    canvasPlot(el('live-chart'),series,tape.map(x=>x.day),{currency,hover:hoverIndex});
    const index=hoverIndex??tape.length-1;
    if(index>=0&&tape[index])el('chart-latest').textContent=mode==='contribution'?`D${tape[index].day.toFixed(2)} · Managed ${money(tape[index].contribution)} · No intervention ${money(tape[index].baseline)}`:mode==='demand'?`D${tape[index].day.toFixed(2)} · Forecast ${number(chosen[index].forecast)} · Observed ${rate(chosen[index].actual)} bottles/day`:`D${tape[index].day.toFixed(2)} · ${currency?money(tape[index][mode]||0):number(tape[index][mode]||0)} · ${(24*(tape[index].dt||state.days_per_tick)).toFixed(1)} business hours`;
  }else if(page==='model'){
    const curve=state.forecast_curves[el('forecast-flavor').value]||[];
    canvasPlot(el('horizon-chart'),[{values:curve,color:'#a293ff'}],curve.map((_,i)=>Math.floor(state.day)+i));
  }
}
el('live-chart').addEventListener('mousemove',event=>{
  if(!state?.tape.length)return;const rect=el('live-chart').getBoundingClientRect();
  hoverIndex=Math.max(0,Math.min(state.tape.length-1,Math.round((event.clientX-rect.left-55)/(rect.width-70)*(state.tape.length-1))));drawCharts();
});
el('live-chart').addEventListener('mouseleave',()=>{hoverIndex=null;drawCharts()});
window.addEventListener('resize',drawCharts);
['chart-flavor','chart-mode'].forEach(id=>el(id).addEventListener('change',drawCharts));
el('forecast-flavor').addEventListener('change',()=>{renderModel();drawCharts()});
el('network-flavor').addEventListener('change',renderNetwork);el('network-search').addEventListener('input',renderNetwork);
el('action-filter').addEventListener('change',renderDecisions);
['incoming-sku','incoming-channel'].forEach(id=>el(id).addEventListener('change',renderIncoming));
el('incoming-search').addEventListener('input',renderIncoming);

el('toggle-run').addEventListener('click',()=>state&&command('/api/live/control',{action:state.running?'pause':'start'}).catch(()=>{}));
el('step-run').addEventListener('click',()=>command('/api/live/control',{action:'step'}).catch(()=>{}));
el('sim-speed').addEventListener('change',()=>command('/api/live/control',{action:'speed',days_per_tick:Number(el('sim-speed').value)}).catch(()=>{}));
el('reset-run').addEventListener('click',()=>el('reset-dialog').showModal());el('close-reset').addEventListener('click',()=>el('reset-dialog').close());
el('reset-form').addEventListener('submit',async event=>{event.preventDefault();try{await command('/api/live/control',{action:'reset',seed:Number(el('reset-seed').value),scenario:el('reset-scenario').value});el('reset-dialog').close()}catch{}});
document.addEventListener('click',event=>{
  if(event.target.closest('[data-show-inputs]')){openPage('datafeed');return}
  const branch=event.target.closest('[data-branch]');if(branch){chooseBranch(branch.dataset.branch);return}
  const preset=event.target.closest('[data-preset]');if(preset){inputDirty=false;command('/api/live/inject',{preset:preset.dataset.preset,step_if_paused:true}).catch(()=>{});return}
  const review=event.target.closest('[data-review]');if(review){openReview(review.dataset.review);return}
  const flavor=event.target.closest('[data-flavor]');if(flavor){el('chart-flavor').value=flavor.dataset.flavor;el('chart-mode').value='demand';drawCharts()}
});
el('inputs-form').addEventListener('input',()=>{inputDirty=true;updateInputLabels();el('inputs-status').textContent='Unsaved scenario changes. Press Apply to introduce them.'});
el('inputs-form').addEventListener('submit',async event=>{
  event.preventDefault();const changes={};
  for(const field of el('inputs-form').elements){if(!field.name)continue;changes[field.name]=field.type==='checkbox'?field.checked:['range','number'].includes(field.type)?Number(field.value):field.value}
  try{await command('/api/live/inputs',{changes,step_if_paused:true});inputDirty=false;syncInputs();el('inputs-status').textContent='Applied. The incoming-data tab shows the parameters and affected records.'}catch{}
});

el('decision-fraction').closest('label').hidden=true;
const choiceSummary=document.createElement('div');choiceSummary.id='review-choice-summary';choiceSummary.className='notice';el('branch-results').after(choiceSummary);
async function openReview(id,recoveredToken=null){
  const action=state.actions.find(x=>x.id===id);if(!action)return;
  selectedAction=structuredClone(action);
  selectedBranch=null;branchComparison=null;
  try{
    if(recoveredToken)selectedAction.review_token=recoveredToken;
    else{
      const opened=await api('/api/live/review/open',{id:action.id,version:action.version});
      selectedAction.review_token=opened.review_token;render(opened.state);
    }
    sessionStorage.setItem('pulp-active-review',JSON.stringify({run_id:state.run_id,id:action.id,token:selectedAction.review_token}));
  }catch(error){selectedAction=null;showError(error.message);return}
  el('review-title').textContent=action.title;el('review-why').textContent=action.why;
  el('review-checks').innerHTML=`<ul>${action.checks.map(x=>`<li>${escapeHtml(x)}</li>`).join('')}</ul>`;
  el('review-role').textContent=`Accountable role: ${action.role}`;
  el('decision-actor').value=localStorage.getItem('pulp-live-operator')||'';el('decision-reason').value='';el('decision-checks').checked=false;
  el('decision-fraction').value='1';el('decision-fraction').disabled=!['TRANSFER','GT_TRANSFER','AIR','AIR_DRAGON','BUFFER'].includes(action.kind);
  el('review-error').hidden=true;el('branch-results').textContent='Comparing identical forecast assumptions…';
  el('review-choice-summary').textContent='Select one of the available paths above. The server clock is paused until you decide or close this review.';
  el('approve-action').textContent='Choose a path above';el('approve-action').disabled=true;
  el('pause-review').textContent='Clock paused automatically';el('pause-review').disabled=true;
  el('review-dialog').showModal();updateReview();
  try{
    const result=await api('/api/live/compare',{id:action.id,version:action.version});
    if(selectedAction?.version!==action.version)return;
    branchComparison=result;
    const best=Math.max(...result.branches.filter(x=>!x.issue).map(x=>x.contribution));
    el('branch-results').innerHTML=result.branches.map(x=>`<button type="button" data-branch="${escapeHtml(x.id)}" class="branch-card ${x.contribution===best&&!x.issue?'best':''}" aria-pressed="false" ${x.issue?'disabled':''}><b>${escapeHtml(x.label)}</b><strong class="${x.contribution_vs_wait>=0?'positive':'negative'}" title="${number(x.contribution_vs_wait)} rupees">${money(x.contribution_vs_wait)}</strong><span>contribution gain vs waiting</span><small>Action cash ${money(x.cash_commitment||0)}</small><small>14-day contribution ${money(x.contribution)}</small><small>Service ${x.service_pct.toFixed(2)}% · ${number(x.unfulfilled)} unfilled</small><small>${number(x.writeoffs)} expired bottles</small><small>${x.issue?escapeHtml(x.issue):'Click to select this path'}</small></button>`).join('');
  }catch(error){el('branch-results').textContent=error.message}
}
function chooseBranch(id){
  const branch=branchComparison?.branches.find(x=>x.id===id);
  if(!branch||branch.issue)return;
  selectedBranch=id;
  document.querySelectorAll('[data-branch]').forEach(x=>{x.classList.toggle('selected',x.dataset.branch===id);x.setAttribute('aria-pressed',String(x.dataset.branch===id))});
  el('decision-fraction').value=id==='half'?'0.5':'1';
  el('decision-checks').required=id!=='wait';
  el('review-choice-summary').innerHTML=`<b>Selected: ${escapeHtml(branch.label)}</b><br>${number(branch.additional_fulfilled||0)} additional fulfilled bottles × ₹19.20 = ${money(branch.service_value_vs_wait||0)} service contribution, minus ${money(branch.extra_cost_vs_wait||0)} extra modeled costs = <b>${money(branch.contribution_vs_wait)} gain vs waiting</b>.<br>${id==='delay'?'Cash is reserved now; execution is revalidated after two business days.':id==='wait'?'No stock moves or cash commitments will be created.':'The selected intervention will execute in the simulation.'}`;
  el('approve-action').textContent=id==='wait'?'Record wait / no new action':id==='delay'?'Schedule action in 2 days':id==='half'?'Approve half quantity':'Approve full action';
  updateReview();
}
function updateReview(){
  if(!selectedAction||!el('review-dialog').open)return;
  const current=state.actions.find(x=>x.id===selectedAction.id&&x.version===selectedAction.version);
  const valid=Boolean(current);
  el('approve-action').disabled=!valid||!selectedBranch;el('reject-action').disabled=!valid;
  el('review-deadline').textContent=valid?`Clock paused for this review · ${current.wall_seconds.toFixed(0)} seconds remain when resumed · proposed commitment ${money(current.params.cash)}. ${current.operational_remaining<0?'Some immediate losses may already be unavoidable; this action can protect later demand.':''}`:'This offer changed or its decision window expired. Close this review and select a current recommendation.';
}
async function closeReview(){
  if(!selectedAction){el('review-dialog').close();return}
  try{const next=await api('/api/live/review/close',{review_token:selectedAction.review_token});selectedAction=null;selectedBranch=null;sessionStorage.removeItem('pulp-active-review');el('review-dialog').close();render(next)}
  catch(error){el('review-error').textContent=error.message;el('review-error').hidden=false}
}
el('close-review').addEventListener('click',closeReview);
el('review-dialog').addEventListener('cancel',event=>{event.preventDefault();closeReview()});
async function recordDecision(status){
  if(!selectedAction)return;
  if(status==='APPROVED'&&!selectedBranch){el('review-error').textContent='Select a decision path above first.';el('review-error').hidden=false;return}
  const actor=el('decision-actor').value.trim(),reason=el('decision-reason').value.trim();
  if(!actor||!reason){el('review-error').textContent='Enter your name and a reason for this decision.';el('review-error').hidden=false;return}
  if(status==='APPROVED'&&selectedBranch!=='wait'&&!el('decision-checks').checked){el('review-error').textContent='Confirm the operational checks before approving.';el('review-error').hidden=false;return}
  el('approve-action').disabled=true;el('reject-action').disabled=true;
  try{
    const next=await api('/api/live/decide',{id:selectedAction.id,version:selectedAction.version,status,actor,reason,
      choice:status==='REJECTED'?'reject':selectedBranch,review_token:selectedAction.review_token,
      fraction:Number(el('decision-fraction').value),checks_confirmed:el('decision-checks').checked});
    localStorage.setItem('pulp-live-operator',actor);el('review-dialog').close();selectedAction=null;selectedBranch=null;sessionStorage.removeItem('pulp-active-review');render(next);
  }catch(error){el('review-error').textContent=error.message;el('review-error').hidden=false;updateReview()}
}
el('decision-form').addEventListener('submit',event=>{event.preventDefault();recordDecision('APPROVED')});
el('reject-action').addEventListener('click',()=>recordDecision('REJECTED'));
el('export-events').addEventListener('click',async()=>{
  try{const data=await api('/api/live/events');const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download=`pulp-riot-${data.run_id}-events.json`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}catch(error){showError(error.message)}
});

async function connect(){
  let delay=1000;
  while(true){
    try{
      if(!state)render(await api('/api/live/state'));
      const headers={Accept:'text/event-stream'};if(accessToken)headers.Authorization=`Bearer ${accessToken}`;
      const response=await fetch('/api/live/stream',{headers,cache:'no-store'});
      if(!response.ok)throw Error(`Live stream HTTP ${response.status}`);
      el('connection-text').textContent='Connected · 1s ticks';el('connection-dot').classList.add('connected');
      const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='';delay=1000;
      while(true){
        const {value,done}=await reader.read();if(done)throw Error('Stream ended');lastMessage=Date.now();
        el('connection-dot').classList.add('connected');el('connection-text').textContent='Connected · 1s ticks';
        buffer+=decoder.decode(value,{stream:true});let split;
        while((split=buffer.indexOf('\n\n'))!==-1){
          const event=buffer.slice(0,split);buffer=buffer.slice(split+2);
          const line=event.split('\n').find(x=>x.startsWith('data: '));if(line)render(JSON.parse(line.slice(6)));
        }
      }
    }catch(error){
      el('connection-dot').classList.remove('connected');el('connection-text').textContent='Reconnecting…';
      if(!state)showError(`Cannot reach the local app: ${error.message}`);
      await new Promise(resolve=>setTimeout(resolve,delay));delay=Math.min(10000,delay*2);
    }
  }
}
setInterval(()=>{if(state?.running&&lastMessage&&Date.now()-lastMessage>5000){el('connection-text').textContent='Stream delayed — checking connection';el('connection-dot').classList.remove('connected')}},2000);
connect();
