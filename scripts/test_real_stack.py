"""End-to-end test against ONLY the dedicated Compose test project on port 8020.

Start with compose.yaml + compose.test.yaml and -p pulp-real-records-test.
This script never seeds the actual real-records workspace or the synthetic app.
"""
import json
import time
from datetime import date,timedelta
from urllib.request import Request,urlopen
from urllib.error import HTTPError

BASE='http://127.0.0.1:8020'

def api(path,body=None):
    req=Request(BASE+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'})
    try:
        with urlopen(req,timeout=180) as response: return json.load(response)
    except HTTPError as exc: raise RuntimeError(f'{path}: {exc.code}: {exc.read().decode()}') from exc

def wait(predicate,seconds=180):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        value=predicate()
        if value:return value
        time.sleep(2)
    raise AssertionError('Timed out waiting for pipeline state')

def verify_reconciliation(request_id):
    assert api('/health').get('test_mode') is True
    api(f'/requests/{request_id}/reconcile',{'actor':'Integration checker','reason':'Test request cancelled without physical execution'})
    for kind in ('lot','material_lot','capacity','inbound','production','shipment'):
        existing=api('/records?kind='+kind)
        assert all(r['source']=='dedicated-integration-test' for r in existing)
        if existing:
            result=api('/imports',{'kind':kind,'source':'dedicated-integration-test','confirmed_real':True,'records':[r['data'] for r in existing]})
            assert result['changed']==0,'Fresh confirmation must preserve content idempotence'
    proposal=api('/optimize',{'days':7})
    api(f"/proposals/{proposal['id']}/decide",{'actor':'Integration checker','reason':'Freshly verified snapshot after cancelled test request','approved':True})
    def reserved_again():
        s=api('/state')
        return s if any(p['id']==proposal['id'] and p['status']=='REQUESTED' for p in s['proposals']) else None
    state=wait(reserved_again)
    assert len([r for r in state['requests'] if r['status']=='AWAITING_ERP_ADAPTER'])==1
    print('PASS: reconciliation and unchanged fresh snapshots permit the next plan safely',flush=True)

def main():
    health=api('/health')
    assert health.get('test_mode') is True,'Refusing to write outside the dedicated test workspace'
    initial=api('/state')
    assert not initial['requests'],'Use a fresh dedicated test project after a completed execution test'
    for kind in initial['record_counts']:
        assert all(r['source']=='dedicated-integration-test' for r in api('/records?kind='+kind)), 'Refusing to mix fixtures with another source'
    day=date.today(); iso=day.isoformat(); expiry=(day+timedelta(days=100)).isoformat()
    rows={
      'channel_master':[{'id':'GT','date':iso,'min_remaining_days':7}],
      'sku_master':[{'id':'TEST-A','date':iso,'recipe':{'TEST-FRUIT':.1}}],
      'depot_master':[{'id':d,'date':iso,'city':d,'region':'test-only'} for d in ('TEST-N','TEST-S')],
      'order':[{'id':f'test-order-{i}','date':(day-timedelta(days=i)).isoformat(),'sku':'TEST-A','depot':'TEST-N','channel':'GT','requested':100,'fulfilled':80,'in_stock':True} for i in range(42)],
      'lot':[{'id':'test-batch-'+d,'date':iso,'sku':'TEST-A','depot':d,'quantity':q,'manufactured':iso,'expires':expiry} for d,q in [('TEST-N',30),('TEST-S',70)]],
      'material_lot':[{'id':'test-raw','date':iso,'material':'TEST-FRUIT','quantity_kg':40,'expires':expiry}],
      'inbound':[{'id':'test-receipt','date':iso,'material':'TEST-FRUIT','quantity_kg':10,'eta':iso,'status':'CONFIRMED','mode':'ROAD'}],
      'capacity':[{'id':'test-capacity','date':iso,'facility':'TEST-P','capacity_bottles':100,'status':'AVAILABLE'}],
      'route':[{'id':'test-route','date':iso,'corridor':'TEST-S-N','status':'OPEN','confirmed':True,'from_depot':'TEST-S','to_depot':'TEST-N','lead_days':1}],
    }
    for kind,records in rows.items():
        payload={'kind':kind,'source':'dedicated-integration-test','records':records,'confirmed_real':True}
        preview=api('/validate',payload);assert 0<=preview['would_change']<=len(records)
        assert api('/imports',payload)['changed']==preview['would_change']
        assert api('/imports',payload)['changed']==0
    state=wait(lambda:(s if (s:=api('/state'))['caught_up'] else None),300)
    assert state['inventory'] and state['forecasts'] and state['quarantined']==0
    print('PASS: validation, atomic imports, idempotence, Debezium / Kafka / Flink projection',flush=True)
    history=api('/history');assert history['iceberg_snapshot'] and history['clickhouse_counts']['order']==42
    print('PASS: S3 / Iceberg / ClickHouse history',flush=True)
    training=api('/train',{});assert training['test_rows']>0
    print('PASS: XGBoost training / held-out evaluation / MLflow registry',flush=True)
    scenarios=api('/scenarios',{'scenarios':[{'name':'current'},{'name':'outage','capacity_loss':1}]})
    assert len(scenarios['results'])==2 and scenarios['engine']=='Ray'
    print('PASS: Ray parallel disruption comparisons',flush=True)
    proposal=api('/optimize',{'days':7}); plan=proposal['plan']
    assert plan['fulfilled']<=600 and plan['production'] and plan['procurement'] and plan['transfers']
    api(f"/proposals/{proposal['id']}/decide",{'actor':'Integration checker','reason':'Dedicated test only','approved':True})
    def requested():
        s=api('/state')
        return s if any(p['id']==proposal['id'] and p['status']=='REQUESTED' for p in s['proposals']) else None
    state=wait(requested)
    assert len(state['requests'])==1
    assert state['requests'][0]['payload']['physical_dispatch'] is False
    print('PASS: OR-Tools feasibility / Temporal approval / reservation / dispatch request',flush=True)
    duplicate=api('/optimize',{'days':7})
    api(f"/proposals/{duplicate['id']}/decide",{'actor':'Integration checker','reason':'Verify duplicate reservation prevention','approved':True})
    def blocked_duplicate():
        s=api('/state')
        return s if any(p['id']==duplicate['id'] and p['status']=='STALE' for p in s['proposals']) else None
    state=wait(blocked_duplicate)
    assert len(state['requests'])==1
    print('PASS: a second approval cannot reserve or dispatch the same inventory again',flush=True)
    verify_reconciliation(proposal['id'])
    checks=api('/services');down=[c for c in checks if c['status']!='UP']
    assert not down,down
    print(f'PASS: {len(checks)} service and worker health checks',flush=True)
    print('Integration test complete. Dedicated test records remain only in test-project volumes.',flush=True)

if __name__=='__main__': main()
