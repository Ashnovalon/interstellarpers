"""Forecast preparation and constrained allocation on projected company records."""
from collections import defaultdict
from datetime import date, timedelta
import math

def histories(groups):
    result = defaultdict(lambda: defaultdict(float))
    for row in groups.get('order',[]):
        result[(row['sku'],row['depot'])][row['date']] += row['requested']
    return result

def feature_rows(groups):
    rows = []
    for key, daily in histories(groups).items():
        for day, value in sorted(daily.items()):
            previous = [(date.fromisoformat(day)-timedelta(days=n)).isoformat() for n in range(1,8)]
            if all(d in daily for d in previous):
                values = [daily[d] for d in previous]
                rows.append((day,[values[0],values[6],sum(values)/7,date.fromisoformat(day).weekday()],value))
    return sorted(rows,key=lambda r:r[0])

def snapshot(groups, version, imported, model=None, today=None):
    today = today or date.today()
    channels = {r['id']:r['min_remaining_days'] for r in groups.get('channel_master',[])}
    demands = defaultdict(set)
    for row in groups.get('order',[]):
        demands[(row['sku'],row['depot'])].add(row['channel'])
    forecasts = []
    for (sku,depot),daily in histories(groups).items():
        latest = max(daily)
        end = date.fromisoformat(latest)
        days = [(end-timedelta(days=n)).isoformat() for n in range(7)]
        values = [daily[d] for d in days if d in daily]
        target=max(today,end+timedelta(days=1))
        daily_forecast = sum(values)/len(values)
        source = 'Observed mean ('+str(len(values))+' dated days)'
        if model is not None and len(values) == 7:
            import numpy as np
            daily_forecast = max(0,float(model.predict(np.array([[values[0],values[6],sum(values)/7,target.weekday()]]))[0]))
            source = 'Validated XGBoost'
        missing_channels = sorted(demands[(sku,depot)]-channels.keys())
        forecasts.append({'sku':sku,'depot':depot,'daily':round(daily_forecast,2),'source':source,
            'latest_order':latest,'forecast_for':target.isoformat(),'stale':(today-end).days>2,
            'min_remaining_days':max((channels.get(c,0) for c in demands[(sku,depot)]),default=0),
            'missing_channel_rules':missing_channels})
    stock = defaultdict(lambda:{'physical':0,'usable':0,'expired':0,'earliest_expiry':None,'oldest_observation':None})
    for row in groups.get('lot',[]):
        bucket = stock[(row['sku'],row['depot'])]
        q = row['quantity']; bucket['physical'] += q
        bucket['expired' if row['expires'] < today.isoformat() else 'usable'] += q
        bucket['earliest_expiry'] = min(bucket['earliest_expiry'] or row['expires'],row['expires'])
        bucket['oldest_observation'] = min(bucket['oldest_observation'] or row['date'],row['date'])
    inventory = [{'sku':k[0],'depot':k[1],**v} for k,v in stock.items()]
    # Capacity records are observations, not additive snapshots of the same facility.
    capacity = {}
    for row in groups.get('capacity',[]):
        if row['facility'] not in capacity or row['date'] > capacity[row['facility']]['date']:
            capacity[row['facility']] = row
    return {'data_version':version,'imported_version':imported,'caught_up':version==imported,
            'as_of':today.isoformat(),'forecasts':forecasts,'inventory':inventory,
            'capacities':list(capacity.values()),'routes':groups.get('route',[]),'depots':groups.get('depot_master',[]),
            'record_counts':{k:len(v) for k,v in groups.items()}}

def optimize(groups, snap, days=7):
    from ortools.linear_solver import pywraplp
    if not snap['caught_up']:
        raise ValueError('Stream processing is catching up; wait for the imported version')
    if not snap['forecasts']:
        raise ValueError('Import actual orders before optimizing')
    if any(r['stale'] or r['missing_channel_rules'] for r in snap['forecasts']):
        raise ValueError('Fresh orders and imported channel freshness rules are required for every demand position')
    today = date.fromisoformat(snap['as_of']); arrival = today+timedelta(days=days)
    if not snap['inventory'] or any(r['oldest_observation'] < (today-timedelta(days=2)).isoformat() for r in snap['inventory']):
        raise ValueError('Import current batch inventory before optimizing (maximum age: two days)')
    solver = pywraplp.Solver.CreateSolver('SCIP')
    if not solver:
        raise RuntimeError('OR-Tools SCIP backend unavailable')
    solver.SetTimeLimit(15000)
    forecasts = snap['forecasts']; positions = [(r['sku'],r['depot']) for r in forecasts]
    demand = {k:math.ceil(r['daily']*days) for k,r in zip(positions,forecasts)}
    freshness = {k:r['min_remaining_days'] for k,r in zip(positions,forecasts)}
    stocks = {k:sum(r['quantity'] for r in groups.get('lot',[]) if (r['sku'],r['depot'])==k and date.fromisoformat(r['expires']) >= arrival+timedelta(days=freshness[k])) for k in positions}
    # Donor-only positions are included so actual surplus can rescue demand elsewhere.
    for row in snap['inventory']:
        k = row['sku'],row['depot']
        if k not in stocks:
            positions.append(k); demand[k]=0; freshness[k]=0
            stocks[k]=sum(r['quantity'] for r in groups.get('lot',[]) if (r['sku'],r['depot'])==k and r['expires']>=arrival.isoformat())
    fulfill={k:solver.IntVar(0,demand[k],f'allocate_{i}') for i,k in enumerate(positions)}
    recipes={r['id']:r['recipe'] for r in groups.get('sku_master',[])}
    facilities=[r for r in snap['capacities'] if r['status']!='DOWN' and r['date'] >= (today-timedelta(days=2)).isoformat()]
    prod={(k,f['facility']):solver.IntVar(0,demand[k],f'produce_{i}_{j}') for i,k in enumerate(positions) if k[0] in recipes for j,f in enumerate(facilities)}
    for f in facilities:
        solver.Add(sum(v for (k,facility),v in prod.items() if facility==f['facility']) <= f['capacity_bottles']*days)
    # Existing committed runs consume capacity. Do not count them as newly available stock.
    for f in facilities:
        committed=sum(r['bottles'] for r in groups.get('production',[]) if r['facility']==f['facility'] and r['status']=='COMMITTED' and today.isoformat()<=r['production_on']<=arrival.isoformat())
        solver.Add(sum(v for (k,facility),v in prod.items() if facility==f['facility']) <= max(0,f['capacity_bottles']*days-committed))
    raw=defaultdict(float)
    for r in groups.get('material_lot',[]):
        if r['expires']>=arrival.isoformat() and r['date'] >= (today-timedelta(days=2)).isoformat(): raw[r['material']]+=r['quantity_kg']
    procure={}
    for i,r in enumerate(groups.get('inbound',[])):
        if r['status']=='CONFIRMED' and today.isoformat()<=r['eta']<=arrival.isoformat():
            procure[r['id']]=(r,solver.NumVar(0,r['quantity_kg'],f'procure_{i}'))
    for material in {m for recipe in recipes.values() for m in recipe}:
        solver.Add(sum(v*recipes[k[0]].get(material,0) for (k,f),v in prod.items()) <= raw[material]+sum(v for r,v in procure.values() if r['material']==material))
    # Only explicitly open, confirmed lanes enable transfers; route masters name from/to.
    lanes=[r for r in groups.get('route',[]) if r['confirmed'] and r['status']=='OPEN' and r.get('from_depot') and r.get('to_depot') and r['date'] >= (today-timedelta(days=2)).isoformat()]
    # Assign actual batches, so two destination channels cannot both claim the
    # same long-life part of a donor's mixed-age inventory.
    batch_use={}
    for lot in groups.get('lot',[]):
        origin=lot['sku'],lot['depot']
        variables=[]
        for dest in positions:
            if dest[0]!=lot['sku'] or not demand[dest]: continue
            if date.fromisoformat(lot['expires'])<arrival+timedelta(days=freshness[dest]): continue
            if origin!=dest and not any((r['from_depot'],r['to_depot'])==(origin[1],dest[1]) and r.get('lead_days',1)<=days for r in lanes): continue
            v=solver.IntVar(0,lot['quantity'],f'batch_{len(batch_use)}')
            batch_use[(lot['id'],origin,dest)]=v;variables.append(v)
        if variables: solver.Add(sum(variables)<=lot['quantity'])
    for k in positions:
        solver.Add(fulfill[k]<=sum(v for (batch,a,b),v in batch_use.items() if b==k)+sum(v for (p,f),v in prod.items() if p==k))
    # Prioritize delivery; smaller terms choose less production, procurement and movement.
    objective=solver.Objective()
    for v in fulfill.values(): objective.SetCoefficient(v,1000)
    for v in prod.values(): objective.SetCoefficient(v,-1)
    for r,v in procure.values(): objective.SetCoefficient(v,-0.01)
    for (batch,a,b),v in batch_use.items(): objective.SetCoefficient(v,-0.1 if a!=b else -0.001)
    objective.SetMaximization()
    status=solver.Solve()
    if status not in (solver.OPTIMAL,solver.FEASIBLE): raise ValueError('No feasible allocation')
    val=lambda v:round(v.solution_value(),3)
    return {'engine':'Google OR-Tools / SCIP','solver_status':'OPTIMAL' if status==solver.OPTIMAL else 'FEASIBLE',
      'data_version':snap['data_version'],'days':days,'demand':sum(demand.values()),
      'fulfilled':sum(round(val(v)) for v in fulfill.values()),
      'allocations':[{'sku':k[0],'depot':k[1],'bottles':round(val(v)),'requested':demand[k]} for k,v in fulfill.items() if demand[k]],
      'production':[{'sku':k[0],'depot':k[1],'facility':f,'bottles':round(val(v))} for (k,f),v in prod.items() if val(v)>0],
      'procurement':[{'inbound_id':r['id'],'material':r['material'],'kg':val(v)} for r,v in procure.values() if val(v)>0],
      'batch_allocations':[{'batch_id':batch,'sku':a[0],'from_depot':a[1],'to_depot':b[1],'bottles':round(val(v))} for (batch,a,b),v in batch_use.items() if val(v)>0],
      'transfers':[{'batch_id':batch,'sku':a[0],'from_depot':a[1],'to_depot':b[1],'bottles':round(val(v))} for (batch,a,b),v in batch_use.items() if a!=b and val(v)>0],
      'limits':['Demand is a constant daily forecast over the horizon.','Freshness must hold through the horizon and destination channel minimum.','Only confirmed inbound quantities and explicitly open lanes are eligible.','Production is an aggregate horizon allocation; facility/SKU qualification and detailed scheduling need company masters.','Approval creates an ERP dispatch request; no external adapter is configured.']}
