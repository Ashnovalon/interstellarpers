'use strict';
let previewPayload=null;

function goTo(id){
  const button=document.querySelector(`[data-view="${id}"]`);
  if(button)button.click();
}
document.getElementById('hero-decisions').addEventListener('click',()=>goTo('decisions'));
document.querySelectorAll('[data-go]').forEach(x=>x.addEventListener('click',()=>goTo(x.dataset.go)));

function pathFor(values,width,height,lo,hi){
  if(!values.length)return '';
  const spread=Math.max(hi-lo,1);
  return values.map((v,i)=>`${i?'L':'M'}${(i*width/Math.max(values.length-1,1)).toFixed(1)},${(height-8-(v-lo)*(height-16)/spread).toFixed(1)}`).join(' ');
}
function chart(values,low=[],high=[]){
  const all=values.concat(low,high).filter(Number.isFinite),lo=Math.max(0,Math.min(...all)*.84),hi=Math.max(...all)*1.14;
  const w=640,h=205,main=pathFor(values,w,h,lo,hi);
  let band='';
  if(low.length===values.length&&high.length===values.length){
    const upper=high.map((v,i)=>[i*w/(high.length-1),h-8-(v-lo)*(h-16)/Math.max(hi-lo,1)]);
    const lower=low.map((v,i)=>[i*w/(low.length-1),h-8-(v-lo)*(h-16)/Math.max(hi-lo,1)]).reverse();
    band=`<polygon points="${upper.concat(lower).map(p=>p.map(n=>n.toFixed(1)).join(',')).join(' ')}" fill="#7668d622"/>`;
  }
  return `<svg class="spark" viewBox="0 0 640 205" role="img" aria-label="Daily demand forecast from ${fmt(values[0])} to ${fmt(values.at(-1))} bottles"><path class="gridline" d="M0 190 H640 M0 103 H640 M0 17 H640"/>${band}<path class="line-path" d="${main}"/></svg>`;
}
function modelHealth(plan){
  const card=plan.forecast.card,metrics=card.metrics;
  if(!metrics)return `<p class="note">${esc(card.limitations?.[0]||'No trained model is available.')}</p>`;
  return `<div class="model-fact"><b>${esc(card.name)}</b>${badge(card.status,card.status==='VALIDATED'?'green':'gold')}</div>
    <div class="model-score"><div><small>HELD-OUT MODEL ERROR</small><strong>${esc(metrics.test.model_wape_pct)}%</strong></div><div><small>REPEAT LAST WEEK</small><strong>${esc(metrics.test.seasonal_wape_pct)}%</strong></div></div>
    <div class="model-fact"><b>Training data</b><span>${card.synthetic?'Synthetic case history':'Company order history'}</span></div>
    <div class="model-fact"><b>History window</b><span>${esc(card.data_start)} to ${esc(card.data_end)}</span></div>
    <div class="model-fact"><b>Series / rows</b><span>${fmt(card.series_count)} / ${fmt(card.training_rows)}</span></div>
    <div class="model-fact"><b>Model used today</b><span>${fmt(plan.forecast.model_positions)} of ${fmt(plan.forecast.series.length)} positions</span></div>
    <p class="model-disclaimer">${esc(card.limitations[0])} Error is weighted absolute percentage error on later dates. Forecast ranges reflect validation residuals and can fail during new shocks.</p>`;
}
function populateSelect(select,values){
  const previous=select.value;
  select.innerHTML=values.map(value=>`<option value="${esc(value)}">${esc(value)}</option>`).join('');
  if(values.includes(previous))select.value=previous;
}
function renderForecast(plan){
  const data=plan.forecast;
  if(!data)return;
  const series=data.series;
  populateSelect(document.getElementById('forecast-sku'),[...new Set(series.map(x=>x.sku))]);
  populateSelect(document.getElementById('forecast-depot'),[...new Set(series.map(x=>x.depot))]);
  populateSelect(document.getElementById('forecast-channel'),[...new Set(series.map(x=>x.channel))]);
  const sku=document.getElementById('forecast-sku').value,depot=document.getElementById('forecast-depot').value,channel=document.getElementById('forecast-channel').value;
  const selected=series.find(x=>x.sku===sku&&x.depot===depot&&x.channel===channel);
  if(selected){
    document.getElementById('forecast-source').textContent=selected.source.replaceAll('_',' ');
    const points=selected.points;
    document.getElementById('forecast-chart').innerHTML=chart(points.map(x=>x.prediction),
      points[0].low==null?[]:points.map(x=>x.low),points[0].high==null?[]:points.map(x=>x.high))+
      `<div class="chart-caption"><span>${esc(points[0].date)}</span><span>${esc(points[6].date)}</span><span>${esc(points.at(-1).date)}</span></div>`;
    document.getElementById('forecast-summary').textContent=`${fmt(Math.round(selected.daily))} bottles/day for the next 7 days. ${selected.explanation}. ${data.interval_note}`;
  }
  document.getElementById('model-card').innerHTML=modelHealth(plan);
  document.getElementById('forecast-count').textContent=`${fmt(series.length)} series`;
  const lookup=new Map(plan.demand.map(x=>[[x.sku,x.depot,x.channel].join('|'),x]));
  document.getElementById('forecast-table').innerHTML=series.map(x=>{
    const row=lookup.get([x.sku,x.depot,x.channel].join('|'));
    return `<tr><td>${esc(x.sku)}</td><td>${esc(x.depot)}</td><td>${esc(x.channel)}</td><td>${fmt(row?.baseline)}</td><td>${fmt(Math.round(x.daily))}</td><td>${badge(x.source.replaceAll('_',' '),x.source==='BASELINE'?'gold':'green')}</td></tr>`;
  }).join('');
  const days=Array.from({length:14},(_,i)=>i).map(i=>series.reduce((n,row)=>n+row.points[i].prediction,0));
  document.getElementById('mini-forecast').innerHTML=chart(days)+`<div class="chart-caption"><span>Tomorrow</span><span>Day 7</span><span>Day 14</span></div><p class="model-disclaimer">${fmt(data.model_positions)} of ${fmt(series.length)} series use the trained model. ${esc(data.card.synthetic?'Synthetic model':'Company-trained model')} · ${esc(data.card.status)}</p>`;
}
function renderDepotRisk(plan){
  const catalog=plan.positions.reduce((acc,p)=>{
    const item=acc[p.depot]||(acc[p.depot]={depot:p.depot,city:p.city,critical:0,watch:0,healthy:0});
    if(p.service_flag==='CRITICAL')item.critical++;
    else if(p.service_flag==='OK')item.healthy++;
    else item.watch++;
    return acc;
  },{});
  document.getElementById('depot-map').innerHTML=Object.values(catalog).map(x=>{
    const state=x.critical?'critical':x.watch?'watch':'healthy';
    return `<div class="depot-tile ${state}" title="${esc(x.city)}: ${x.critical} critical, ${x.watch} watch, ${x.healthy} healthy"><span class="count">${x.critical?x.critical+' risk':x.watch?x.watch+' watch':'OK'}</span><strong>${esc(x.city)}</strong><small>${esc(x.depot)} · ${x.critical+x.watch+x.healthy} flavors</small></div>`;
  }).join('')||'<div class="empty">Import stock and orders to see depot health.</div>';
}
function renderPositions(plan){
  const search=document.getElementById('position-search').value.trim().toLowerCase(),status=document.getElementById('position-status').value;
  const rows=plan.positions.filter(x=>(status==='ALL'||x.service_flag===status)&&
    (!search||`${x.sku} ${x.city} ${x.depot}`.toLowerCase().includes(search)));
  document.getElementById('position-count').textContent=`${rows.length} of ${plan.positions.length} positions`;
  document.getElementById('positions').innerHTML=rows.slice().sort((a,b)=>(a.cover_days??999)-(b.cover_days??999)).map(x=>
    `<tr><td>${esc(x.city)}</td><td>${esc(x.sku)}</td><td>${known(x.quantity)}</td><td>${fmt(x.daily_demand)}</td><td>${esc(x.cover_days??'?')} d</td><td>${known(x.mt_qc_eligible_on_transfer_arrival)}</td><td>${badge(x.service_flag,x.service_flag==='CRITICAL'?'red':x.service_flag==='OK'?'green':'gold')}</td></tr>`).join('')||'<tr><td colspan="7">No positions match these filters.</td></tr>';
}
document.addEventListener('plan-rendered',event=>{
  renderForecast(event.detail);renderDepotRisk(event.detail);renderPositions(event.detail);
});
['forecast-sku','forecast-depot','forecast-channel'].forEach(id=>document.getElementById(id).addEventListener('change',()=>current&&renderForecast(current)));
['position-search','position-status'].forEach(id=>document.getElementById(id).addEventListener('input',()=>current&&renderPositions(current)));

function resetPreview(){previewPayload=null;document.getElementById('import-preview').hidden=true;}
['kind','source','file'].forEach(id=>document.getElementById(id).addEventListener('change',resetPreview));
document.getElementById('ingest-form').addEventListener('submit',async event=>{
  event.preventDefault();resetPreview();const file=document.getElementById('file').files[0];if(!file)return;
  const output=document.getElementById('upload-result');
  try{
    const raw=await file.text();const parsed=file.name.toLowerCase().endsWith('.csv')?parseCsv(raw):JSON.parse(raw);
    const records=Array.isArray(parsed)?parsed:parsed.records;
    if(!Array.isArray(records))throw Error('File must contain a JSON array or CSV rows');
    if(!records.length)throw Error('File has no records');
    const payload={kind:document.getElementById('kind').value,source:document.getElementById('source').value,records};
    const checked=await api('/api/validate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    previewPayload=payload;
    output.textContent=`Valid: ${checked.received} records; ${checked.would_change} would be added or changed. Review the first rows below, then import.`;
    const cols=Object.keys(checked.preview[0]||{}).slice(0,8);
    document.getElementById('preview-table').innerHTML=`<table><thead><tr>${cols.map(c=>`<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${checked.preview.map(row=>`<tr>${cols.map(c=>`<td title="${esc(typeof row[c]==='object'?JSON.stringify(row[c]):row[c])}">${esc(typeof row[c]==='object'?JSON.stringify(row[c]):row[c])}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
    document.getElementById('import-preview').hidden=false;
  }catch(e){output.textContent=`Rejected: ${e.message}`;}
});
document.getElementById('confirm-import').addEventListener('click',async()=>{
  if(!previewPayload)return;
  const button=document.getElementById('confirm-import');button.disabled=true;
  try{
    const result=await api('/api/ingest',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(previewPayload)});
    document.getElementById('upload-result').textContent=`Imported ${result.received} records; ${result.changed} changed. The plan has been refreshed.`;
    resetPreview();await refresh();
  }catch(e){document.getElementById('upload-result').textContent=`Import failed: ${e.message}`;}
  finally{button.disabled=false;}
});
document.getElementById('download-template').addEventListener('click',async()=>{
  try{
    const kind=document.getElementById('kind').value,rows=await api(`/api/template?kind=${encodeURIComponent(kind)}`);
    const blob=new Blob([JSON.stringify(rows,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob);
    const link=document.createElement('a');link.href=url;link.download=`${kind}-example.json`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }catch(e){error(e.message);}
});
