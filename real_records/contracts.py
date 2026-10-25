"""Technology-independent import and event checks; no sample masters or defaults."""
import hashlib
import json
import math
from datetime import date

CONTRACTS = {
 'order': ('id date sku depot channel requested fulfilled in_stock', 'requested fulfilled'),
 'lot': ('id date sku depot quantity manufactured expires', 'quantity'),
 'material_lot': ('id date material quantity_kg expires', 'quantity_kg'),
 'inbound': ('id date material quantity_kg eta status mode', 'quantity_kg'),
 'route': ('id date corridor status confirmed', ''),
 'signal': ('id date sku source value baseline', 'value baseline'),
 'freight_quote': ('id date material max_kg incremental_cost_rupees lead_days valid_until cold_chain_confirmed', 'max_kg incremental_cost_rupees lead_days'),
 'capacity': ('id date facility capacity_bottles status', 'capacity_bottles'),
 'production': ('id date sku facility depot bottles production_on eta_depot status', 'bottles'),
 'shipment': ('id date sku from_depot to_depot bottles eta expires status', 'bottles'),
 'sku_master': ('id date recipe', ''),
 'depot_master': ('id date city region', ''),
 'channel_master': ('id date min_remaining_days', 'min_remaining_days'),
}
ENUMS = {
 'inbound': {'status': {'PLANNED','CONFIRMED','RECEIVED','CANCELLED'}, 'mode': {'ROAD','AIR','SEA'}},
 'capacity': {'status': {'AVAILABLE','REDUCED','DOWN'}},
 'production': {'status': {'PLANNED','COMMITTED','COMPLETED','CANCELLED'}},
 'shipment': {'status': {'PLANNED','IN_TRANSIT','RECEIVED','CANCELLED'}},
 'route': {'status': {'OPEN','WATCH','CONFIRMED_CLOSED','UNKNOWN'}},
}
INTEGER_FIELDS = {'requested','fulfilled','quantity','bottles','capacity_bottles','lead_days','min_remaining_days'}

def nonnegative(value):
    return not isinstance(value, bool) and isinstance(value, (int,float)) and math.isfinite(value) and value >= 0

def validate_record(kind, row, *, allow_synthetic=False):
    if kind not in CONTRACTS:
        raise ValueError('Unknown record type')
    if not isinstance(row, dict):
        raise ValueError('Each record must be an object')
    result = dict(row)
    required, numeric = CONTRACTS[kind]
    for field in required.split():
        if field not in row or row[field] is None:
            raise ValueError(f'{kind}: missing {field}')
        if field not in numeric.split() and field not in {'recipe','confirmed','in_stock','cold_chain_confirmed'}:
            if not isinstance(row[field],str) or not row[field].strip() or len(row[field]) > 200:
                raise ValueError(f'{field} must be nonempty text (up to 200 characters)')
    for field in numeric.split():
        value = row[field]
        if not nonnegative(value) or value > 1e12 or (field in INTEGER_FIELDS and int(value) != value):
            raise ValueError(f'{field} must be finite, nonnegative' + (' and whole' if field in INTEGER_FIELDS else ''))
    for field in ('date','manufactured','expires','eta','valid_until','production_on','eta_depot'):
        if field in row:
            date.fromisoformat(row[field])
    for field in ('confirmed','in_stock','cold_chain_confirmed','synthetic','sample'):
        if field in row and not isinstance(row[field],bool):
            raise ValueError(f'{field} must be true or false')
    for field, choices in ENUMS.get(kind,{}).items():
        if row[field] not in choices:
            raise ValueError(f'{field} must be one of {sorted(choices)}')
    if kind == 'order' and row['fulfilled'] > row['requested']:
        raise ValueError('Fulfilled cannot exceed requested')
    if kind == 'lot' and not row['manufactured'] <= row['date'] <= row['expires']:
        raise ValueError('Batch dates must satisfy manufactured <= date <= expires')
    if kind == 'route' and row['status'] == 'CONFIRMED_CLOSED' and not row['confirmed']:
        raise ValueError('A closure needs confirmation')
    if kind == 'route' and 'lead_days' in row and (not nonnegative(row['lead_days']) or int(row['lead_days'])!=row['lead_days']):
        raise ValueError('Route lead_days must be a nonnegative whole number')
    if kind == 'sku_master':
        recipe = row['recipe']
        if not isinstance(recipe,dict) or not recipe or any(not str(k).strip() or not nonnegative(v) or v == 0 for k,v in recipe.items()):
            raise ValueError('Recipe must map materials to positive kg per bottle')
    if kind == 'production' and not row['date'] <= row['production_on'] <= row['eta_depot']:
        raise ValueError('Production and arrival dates are inconsistent')
    if kind == 'shipment' and not row['date'] <= row['eta'] <= row['expires']:
        raise ValueError('Shipment must arrive before expiry')
    # Keep customer provenance explicit. A generator flag is never reclassified as real.
    if not allow_synthetic and (row.get('synthetic') is True or row.get('sample') is True):
        raise ValueError('Synthetic/sample records belong in the existing synthetic workspace')
    return result

def validate_batch(kind, records, *, allow_synthetic=False):
    if not isinstance(records,list) or not 1 <= len(records) <= 10000:
        raise ValueError('Import 1 to 10,000 records per file')
    checked = [validate_record(kind,r,allow_synthetic=allow_synthetic) for r in records]
    if len({r['id'] for r in checked}) != len(checked):
        raise ValueError('Duplicate IDs in the same upload')
    return checked

def record_hash(row):
    return hashlib.sha256(json.dumps(row,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def scenario_metrics(snapshot, scenario):
    """Explicit what-if assumptions over observed inputs; no generated orders."""
    demand = sum(r['daily'] for r in snapshot['forecasts']) * scenario['days'] * scenario['demand_multiplier']
    stock = sum(r['usable'] for r in snapshot['inventory'])
    capacity = sum(r['capacity_bottles'] for r in snapshot['capacities'] if r['status'] != 'DOWN')
    supply = stock + capacity * max(0,scenario['days']-scenario['delay_days']) * (1-scenario['capacity_loss'])
    return {**scenario, 'demand':round(demand), 'supply_upper_bound':round(supply),
            'shortfall_lower_bound':round(max(0,demand-supply)),
            'assumption':'Aggregate capacity bound; recipe, freshness and route feasibility checked by optimizer'}
