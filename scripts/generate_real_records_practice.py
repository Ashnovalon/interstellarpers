"""Create explicitly synthetic uploads for the isolated practice workspace."""
import argparse
import csv
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from real_records.contracts import validate_batch

def generate(day):
    folder=ROOT/'data/real_records_practice'
    folder.mkdir(parents=True,exist_ok=True)
    (folder/'checks').mkdir(exist_ok=True)
    (folder/'csv').mkdir(exist_ok=True)
    iso=day.isoformat(); expiry=(day+timedelta(days=100)).isoformat()
    base={'date':iso,'synthetic':True,'source_note':'Generated practice data. Not actual company records.'}
    def row(**fields):return {**base,**fields}
    uploads=[
      ('01_channel_master.json','channel_master',[row(id='PRACTICE-GT',min_remaining_days=7)]),
      ('02_sku_master.json','sku_master',[row(id='PRACTICE-MANGO',recipe={'PRACTICE-PULP':.1})]),
      ('03_depot_master.json','depot_master',[row(id='PRACTICE-N',city='Bengaluru',region='Practice north'),row(id='PRACTICE-S',city='Mysuru',region='Practice south')]),
      ('04_orders.json','order',[row(id=f'PRACTICE-ORDER-{i:02}',date=(day-timedelta(days=i)).isoformat(),sku='PRACTICE-MANGO',depot='PRACTICE-N',channel='PRACTICE-GT',requested=100,fulfilled=80,in_stock=True) for i in range(42)]),
      ('05_finished_batches.json','lot',[row(id='PRACTICE-LOT-'+d,sku='PRACTICE-MANGO',depot='PRACTICE-'+d,quantity=q,manufactured=(day-timedelta(days=5)).isoformat(),expires=expiry) for d,q in [('N',30),('S',70)]]),
      ('06_raw_material_batches.json','material_lot',[row(id='PRACTICE-RAW',material='PRACTICE-PULP',quantity_kg=40,expires=expiry)]),
      ('07_confirmed_inbound.json','inbound',[row(id='PRACTICE-INBOUND',material='PRACTICE-PULP',quantity_kg=10,eta=(day+timedelta(days=1)).isoformat(),status='CONFIRMED',mode='ROAD')]),
      ('08_plant_capacity.json','capacity',[row(id='PRACTICE-CAPACITY',facility='PRACTICE-PLANT',capacity_bottles=100,status='AVAILABLE')]),
      ('09_open_route.json','route',[row(id='PRACTICE-ROUTE',corridor='PRACTICE-S-N',from_depot='PRACTICE-S',to_depot='PRACTICE-N',lead_days=1,status='OPEN',confirmed=True)]),
      ('10_optional_production.json','production',[row(id='PRACTICE-PRODUCTION',sku='PRACTICE-MANGO',facility='PRACTICE-PLANT',depot='PRACTICE-N',bottles=20,production_on=(day+timedelta(days=1)).isoformat(),eta_depot=(day+timedelta(days=2)).isoformat(),status='PLANNED')]),
      ('11_optional_shipment.json','shipment',[row(id='PRACTICE-SHIPMENT',sku='PRACTICE-MANGO',from_depot='PRACTICE-S',to_depot='PRACTICE-N',bottles=10,eta=(day+timedelta(days=2)).isoformat(),expires=expiry,status='CANCELLED')]),
      ('12_optional_freight_quote.json','freight_quote',[row(id='PRACTICE-QUOTE',material='PRACTICE-PULP',max_kg=10,incremental_cost_rupees=500,lead_days=1,valid_until=(day+timedelta(days=7)).isoformat(),cold_chain_confirmed=True)]),
      ('13_optional_signal.json','signal',[row(id='PRACTICE-SIGNAL',sku='PRACTICE-MANGO',source='CAMPAIGN',value=100,baseline=100)]),
    ]
    manifest={'synthetic':True,'as_of':iso,'target':'Isolated practice workspace only (port 3020)','files':[]}
    for filename,kind,records in uploads:
        validate_batch(kind,records,allow_synthetic=True)
        (folder/filename).write_bytes((json.dumps(records,indent=2)+'\n').encode())
        columns=list(dict.fromkeys(k for r in records for k in r))
        with (folder/'csv'/filename.replace('.json','.csv')).open('w',newline='',encoding='utf-8') as f:
            writer=csv.DictWriter(f,fieldnames=columns);writer.writeheader()
            writer.writerows({k:json.dumps(v) if isinstance(v,(bool,dict,list)) else v for k,v in r.items()} for r in records)
        manifest['files'].append({'file':filename,'kind':kind,'records':len(records),'optional':filename.startswith(('10','11','12','13'))})
    route=uploads[8][2][0]
    checks={
      'route_closed.json':[{**route,'status':'CONFIRMED_CLOSED'}],
      'route_open_again.json':[route],
      'invalid_order_rejected.json':[{**uploads[3][2][0],'id':'PRACTICE-INVALID','fulfilled':101}],
      'optional_next_day_outcome.json':[row(id='PRACTICE-NEXT-DAY',date=(day+timedelta(days=1)).isoformat(),sku='PRACTICE-MANGO',depot='PRACTICE-N',channel='PRACTICE-GT',requested=120,fulfilled=90,in_stock=True)]}
    for name,records in checks.items():
        (folder/'checks'/name).write_bytes((json.dumps(records,indent=2)+'\n').encode())
    manifest['expected']={'core_records':52,'all_records':56,'daily_forecast':100,'seven_day_demand':700,'usable_stock':100,'production_bottles':500,'confirmed_procurement_kg':10,'transfer_bottles':70,'allocation_open_route':600,'allocation_closed_route':530}
    (folder/'manifest.json').write_bytes((json.dumps(manifest,indent=2)+'\n').encode())
    print(f'Generated 13 JSON files, CSV alternatives and 4 checks in {folder}; as of {iso}')
    return manifest

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--as-of',type=date.fromisoformat,default=datetime.now(timezone(timedelta(hours=5,minutes=30))).date())
    generate(parser.parse_args().as_of)
