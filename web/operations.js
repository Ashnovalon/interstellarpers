'use strict';
const $=id=>document.getElementById(id);
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=value=>Number(value??0).toLocaleString('en-IN');
const known=value=>value==null?'Unknown':fmt(value);
const pct=value=>`${Number(value??0).toFixed(1)}%`;
let current=null, pendingDecision=null, view='overview';
let token=sessionStorage.getItem('control-tower-token')||'';
async function api(path,options={},retried=false){
  const headers={...(options.headers||{})};if(token)headers.Authorization=`Bearer ${token}`;
  const response=await fetch(path,{...options,headers});const data=await response.json();
  if(response.status===401&&!retried){const supplied=window.prompt('This local server requires its configured API token.');if(supplied){token=supplied;sessionStorage.setItem('control-tower-token',token);return api(path,options,true)}}
  if(!response.ok)throw new Error(data.error||`HTTP ${response.status}`);return data;
}
function error(message){$('error').hidden=!message;$('error').textContent=message||'';}
function badge(text,kind=''){return `<span class="badge ${kind}">${esc(text)}</span>`}
function metric(title,value,note,danger=false){return `<div class="metric ${danger?'danger':''}"><label>${esc(title)}</label><strong>${esc(value)}</strong><small>${esc(note)}</small></div>`}
function actionCard(a){
 const nums=Object.entries(a.numbers).map(([k,v])=>`${esc(k.replaceAll('_',' '))}: <b>${esc(typeof v==='number'?fmt(v):v)}</b>`).join(' · ');
 const actions=a.status==='PENDING'?`<div class="action-actions"><button data-decision="${esc(a.id)}" data-status="APPROVED">Approve</button><button data-decision="${esc(a.id)}" data-status="REJECTED">Reject</button></div>`:'';
 return `<div class="action p${a.priority}"><div class="action-top"><div><h3>${esc(a.title)}</h3><small>${esc(a.kind)} · ${esc(a.owner_role)}</small></div>${badge(a.status,a.status==='APPROVED'?'green':a.status==='REJECTED'?'red':'gold')}</div><p>${esc(a.why)}</p><div class="numbers">${nums}</div><ul>${a.checks.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>${a.decision?`<small>Decision by ${esc(a.decision.actor)} · ${esc(a.decision.reason)}</small>`:''}${actions}</div>`;
}
function render(plan){
 current=plan;$('mode').textContent=plan.mode;$('clock').textContent=plan.as_of;
 $('overview-sub').textContent=`${plan.quality.latest_order_date?'Last order '+plan.quality.latest_order_date:'No order feed'} · ${plan.actions.length} recommendations · all decisions need review`;
 const m=plan.metrics;
 $('metrics').innerHTML=metric('Demand per day',fmt(m.daily_demand_bottles),'Validated order forecast')+metric('Capacity gap per day',fmt(m.capacity_gap_bottles_per_day),'Against fixed in-house capacity',m.capacity_gap_bottles_per_day>0)+metric('Critical depot positions',m.critical_positions,'Below 14 days cover',m.critical_positions>0)+metric('Pending decisions',m.pending_actions,'No automatic dispatch');
 $('action-count').textContent=`${plan.actions.length} total`;
 $('top-actions').innerHTML=plan.actions.length?plan.actions.slice(0,5).map(a=>`<div class="line"><div><strong>${esc(a.title)}</strong><small>${esc(a.why)}</small></div>${badge(a.kind,a.priority===1?'red':'gold')}</div>`).join(''):'<div class="empty">No current action.</div>';
 const road=plan.route.status;const material=plan.materials.find(x=>x.material==='passionfruit');
 const five=[['Demand',`${plan.demand.filter(x=>x.reason.startsWith('two observed')).length} validated shifts`],['Supply',material?`${material.cover_days} days passionfruit cover`:'No pulp data'],['Inventory',`${m.critical_positions} service-critical positions`],['Distribution',`${plan.actions.filter(a=>a.kind==='TRANSFER').length} eligible proposed moves`],['Transportation',`${road} · no approved alternate road`]];
 $('radar').innerHTML=five.map(([name,description])=>`<div class="risk-row"><strong>${esc(name)}</strong><span>${esc(description)}</span>${badge(name==='Demand'||name==='Inventory'?'DEEP':'LINKED')}</div>`).join('');
 const e=plan.external||{};
 $('signals').innerHTML=`<div class="line"><div><strong>Observed campaign/search signals</strong><small>${plan.signals.length} recent verified records</small></div>${badge(plan.signals.length?'WATCH':'NONE')}</div><div class="line"><div><strong>Road provider</strong><small>${esc(e.road?.reason||'Not polled')}</small></div>${badge(e.road?.state||'UNKNOWN')}</div><div class="line"><div><strong>Video attention</strong><small>${esc(e.attention?.reason||'Not polled')}</small></div>${badge(e.attention?.state||'UNKNOWN')}</div><p class="note">External attention may start a watch. Bottle forecasts change only when operational demand observations support them.</p>`;
 const q=plan.quality;
 $('health').innerHTML=`<div class="line"><div><strong>Order feed</strong><small>${esc(q.latest_order_date||'No records')}</small></div>${badge(q.order_feed_stale?'STALE':'CURRENT',q.order_feed_stale?'red':'green')}</div><div class="line"><div><strong>Route observation</strong><small>${esc(q.route_observation_date||'No report')}</small></div>${badge(road,road.includes('CLOSED')?'red':'gold')}</div>${Object.entries(q.record_counts).sort().map(([k,v])=>`<div class="line"><span>${esc(k.replaceAll('_',' '))}</span><b>${fmt(v)} records</b></div>`).join('')}`;
 $('decision-list').innerHTML=plan.actions.length?plan.actions.map(actionCard).join(''):'<div class="empty">No recommendations from the current inputs.</div>';
 $('materials').innerHTML=plan.materials.map(x=>`<div class="line"><div><strong>${esc(x.material)}</strong><small>${known(x.stock_kg)} kg in batches · ${fmt(x.forecast_kg_per_day)} kg/day forecast</small></div>${badge(`${x.cover_days??'?'} days`,x.cover_days!=null&&x.cover_days<24&&x.material==='passionfruit'?'red':'')}</div>`).join('')||'<div class="empty">No raw-material observations.</div>';
 $('road').innerHTML=`<p>${badge(road,road.includes('CLOSED')?'red':'gold')}</p><p>${esc(plan.route.source_note||'No transporter/authority report available.')}</p><p class="note">Map incidents within a configured bounding box require route and transporter confirmation. The case allows no alternative cooperative road.</p>`;
 $('position-count').textContent=`${plan.positions.length} positions`;
 $('positions').innerHTML=plan.positions.slice().sort((a,b)=>(a.cover_days??999)-(b.cover_days??999)).map(x=>`<tr><td>${esc(x.city)}</td><td>${esc(x.sku)}</td><td>${known(x.quantity)}</td><td>${fmt(x.daily_demand)}</td><td>${esc(x.cover_days??'?')} d</td><td>${known(x.mt_qc_eligible_on_transfer_arrival)}</td><td>${badge(x.service_flag,x.service_flag==='CRITICAL'?'red':x.service_flag==='OK'?'green':'gold')}</td></tr>`).join('');
 $('external').innerHTML=Object.entries(e).map(([name,x])=>`<div class="line"><div><strong>${esc(name)}</strong><small>${esc(x.reason||'')}</small></div>${badge(x.state||'UNKNOWN')}</div>`).join('')||'<div class="empty">No external source has been polled. Configure authorized keys and a verified corridor to connect them.</div>';
 document.dispatchEvent(new CustomEvent('plan-rendered',{detail:plan}));
}
function renderProcessMining(summary){
  const target=$('process-mining');
  if(!summary || summary.status === 'unavailable'){
    target.innerHTML=`<div class="empty">PM4Py is not available in this environment: ${esc(summary?.error || 'unknown error')}</div>`;
    return;
  }
  if(summary.status === 'empty'){
    target.innerHTML='<div class="empty">No operational audit events yet. Import or approve records to build a process log.</div>';
    return;
  }
  const activities = summary.activities.length ? summary.activities.map(x => `<span class="badge">${esc(x)}</span>`).join(' ') : '<span class="empty">No activities</span>';
  const start = summary.start_activities.length ? summary.start_activities.map(([name, count]) => `<div class="line"><span>${esc(name)}</span><b>${fmt(count)}</b></div>`).join('') : '<div class="empty">No start activities</div>';
  const end = summary.end_activities.length ? summary.end_activities.map(([name, count]) => `<div class="line"><span>${esc(name)}</span><b>${fmt(count)}</b></div>`).join('') : '<div class="empty">No end activities</div>';
  const edges = summary.dfg.length ? summary.dfg.slice(0, 8).map(edge => `<div class="line"><span>${esc(edge.from)} → ${esc(edge.to)}</span><b>${fmt(edge.count)}</b></div>`).join('') : '<div class="empty">No flow edges identified</div>';
  target.innerHTML = `
    <div class="line"><div><strong>Events</strong><small>PM4Py event log</small></div>${badge(`${fmt(summary.event_count)}`)}</div>
    <div class="line"><div><strong>Cases</strong><small>distinct process instances</small></div>${badge(`${fmt(summary.case_count)}`)}</div>
    <div class="line"><div><strong>Activities</strong><small>distinct event labels</small></div>${badge(`${fmt(summary.activity_count)}`)}</div>
    <div class="note">${activities}</div>
    <div class="grid two"><div class="card"><h3>Start</h3>${start}</div><div class="card"><h3>End</h3>${end}</div></div>
    <div class="card"><h3>Directly-follows graph</h3>${edges}</div>
  `;
}
async function loadProcessMining(){
  try {
    const summary = await api('/api/process-mining');
    renderProcessMining(summary);
    $('process-overview').textContent = summary.status === 'ok'
      ? `Observed ${fmt(summary.event_count)} events across ${fmt(summary.case_count)} cases.`
      : 'No process-mining data available yet.';
  } catch (e) {
    renderProcessMining({status: 'unavailable', error: e.message});
    $('process-overview').textContent = 'Process-mining analysis could not run.';
  }
}
async function refresh(){error('');try{render(await api('/api/plan'));if(view==='decisions')loadAudit();await loadProcessMining()}catch(e){error(e.message)}}
async function loadAudit(){try{const rows=await api('/api/audit');$('audit').innerHTML=rows.filter(r=>r.event==='DECISION').slice(0,15).map(r=>{let detail={};try{detail=JSON.parse(r.detail)}catch{}return `<div class="line"><div><strong>${esc(detail.status||r.event)} · ${esc(detail.action_id||'')}</strong><small>${esc(detail.actor||'')} · ${esc(detail.reason||'')}</small></div><small>${esc(r.at)}</small></div>`}).join('')||'<div class="empty">No decisions recorded.</div>'}catch(e){error(e.message)}}
document.querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>{view=button.dataset.view;document.querySelectorAll('[data-view]').forEach(x=>x.classList.toggle('active',x===button));document.querySelectorAll('.view').forEach(x=>x.classList.toggle('active',x.id===view));if(view==='decisions')loadAudit()}));
$('refresh').addEventListener('click',refresh);
document.addEventListener('click',event=>{const button=event.target.closest('[data-decision]');if(!button||!current)return;const a=current.actions.find(x=>x.id===button.dataset.decision);if(!a)return;pendingDecision={action:a,status:button.dataset.status};$('decision-title').textContent=`${button.dataset.status==='APPROVED'?'Approve':'Reject'} ${a.title}`;$('decision-explain').textContent=`Owner role: ${a.owner_role}. This is a recorded decision, not a stock or freight dispatch.`;$('reason').value='';$('decision-dialog').showModal()});
$('cancel-decision').addEventListener('click',()=>$('decision-dialog').close());
$('decision-form').addEventListener('submit',async event=>{event.preventDefault();if(!pendingDecision)return;const {action,status}=pendingDecision;try{await api('/api/decide',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:action.id,version:action.version,status,actor:$('actor').value,role:action.owner_role,reason:$('reason').value})});$('decision-dialog').close();await refresh()}catch(e){error(e.message);$('decision-dialog').close()}});
function parseCsv(source){const rows=[];let row=[],cell='',quoted=false;source=source.replace(/^\uFEFF/,'');for(let i=0;i<source.length;i++){const c=source[i];if(c==='"'){if(quoted&&source[i+1]==='"'){cell+='"';i++}else quoted=!quoted}else if(c===','&&!quoted){row.push(cell);cell=''}else if((c==='\n'||c==='\r')&&!quoted){if(c==='\r'&&source[i+1]==='\n')i++;row.push(cell);if(row.some(x=>x.trim()))rows.push(row);row=[];cell=''}else cell+=c}if(quoted)throw Error('Unclosed CSV quote');row.push(cell);if(row.some(x=>x.trim()))rows.push(row);if(rows.length<2)throw Error('CSV needs a header and data row');const headers=rows.shift().map(x=>x.trim());return rows.map((cells,i)=>{if(cells.length!==headers.length)throw Error(`CSV row ${i+2} has ${cells.length} fields, expected ${headers.length}`);return Object.fromEntries(headers.map((h,j)=>[h,h==='recipe'?JSON.parse(cells[j].trim()):cells[j].trim()]))})}
$('poll-external').addEventListener('click',async()=>{try{$('poll-external').disabled=true;const results=await api('/api/external/refresh',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});$('upload-result').textContent=`Road: ${results.road.state}. Attention: ${results.attention.state}.`;await refresh()}catch(e){error(e.message)}finally{$('poll-external').disabled=false}});
$('run-replay').addEventListener('click',async()=>{try{$('replay').textContent='Running both daily policies…';const result=await api('/api/replay');const old=result.last_summer_planning,next=result.approved_proposals,d=result.difference;
 $('replay').innerHTML=`<div class="scenario-metrics">${metric('Additional fulfilled',fmt(d.additional_fulfilled_bottles),'Bottles in synthetic comparison')}${metric('Write-off difference',fmt(d.avoided_writeoff_bottles),'Bottles; can be negative')}${metric('Added transfer spend',`₹${fmt(d.added_transfer_cost_rupees)}`,'No procurement buffer cost included')}</div><div class="grid two"><article class="card"><h2>Static planning policy</h2><p>Service ${pct(old.service_pct)} · Unfulfilled ${fmt(old.unfulfilled_bottles)} · Written off ${fmt(old.writeoff_bottles)}</p><div class="timeline">${old.milestones.map(x=>`<div class="event"><b>${esc(x.date)} · ${esc(x.trigger)}</b><small>Pulp ${esc(x.passion_cover_days)}d · ${esc(x.critical_positions)} critical positions</small><p>${x.recommendations.map(esc).join('; ')}</p></div>`).join('')}</div></article><article class="card"><h2>Approved proposal policy</h2><p>Service ${pct(next.service_pct)} · Unfulfilled ${fmt(next.unfulfilled_bottles)} · Written off ${fmt(next.writeoff_bottles)} · Transferred ${fmt(next.transfer_bottles)}</p><div class="timeline">${next.milestones.map(x=>`<div class="event"><b>${esc(x.date)} · ${esc(x.trigger)}</b><small>Pulp ${esc(x.passion_cover_days)}d · ${esc(x.critical_positions)} critical positions</small><p>${x.recommendations.map(esc).join('; ')}</p></div>`).join('')}</div></article></div><article class="card"><h2>How to read this result</h2>${result.assumptions.map(x=>`<p>${esc(x)}</p>`).join('')}<p><b>These are scenario outcomes, not measured savings or a forecast.</b> The program budget and added buffer working capital must be validated separately.</p></article>`;
 }catch(e){$('replay').textContent=`Replay failed: ${e.message}`}});
refresh();setInterval(refresh,60_000);
