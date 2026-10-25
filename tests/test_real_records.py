"""Local, isolated checks. Never read/write output/control_tower.sqlite."""
import copy
from datetime import date,timedelta
import json
import math
import os
from pathlib import Path
import sys
import unittest
from real_records.contracts import validate_batch,validate_record,scenario_metrics
from real_records.planning import feature_rows,snapshot,optimize

DAY=date(2026,10,25)

def company_fixture():
    # Test fixtures only: never seeded into an application or real-record DB.
    return {'order':[{'id':'o','date':DAY.isoformat(),'sku':'A','depot':'N','channel':'GT','requested':100,'fulfilled':50,'in_stock':True}],
      'lot':[{'id':'l','date':DAY.isoformat(),'sku':'A','depot':'N','quantity':50,'manufactured':DAY.isoformat(),'expires':(DAY+timedelta(days=80)).isoformat()}],
      'channel_master':[{'id':'GT','date':DAY.isoformat(),'min_remaining_days':7}],
      'sku_master':[{'id':'A','date':DAY.isoformat(),'recipe':{'fruit':.1}}],
      'material_lot':[{'id':'raw','date':DAY.isoformat(),'material':'fruit','quantity_kg':10,'expires':(DAY+timedelta(days=100)).isoformat()}],
      'capacity':[{'id':'c','date':DAY.isoformat(),'facility':'P','capacity_bottles':200,'status':'AVAILABLE'}]}

class RealRecordTests(unittest.TestCase):
    def test_validation_rejects_nan_negative_fractional_and_overfulfillment(self):
        row=company_fixture()['order'][0]
        for values in [{'requested':float('nan')},{'requested':-1},{'requested':1.5},{'fulfilled':101},{'in_stock':'true'}]:
            with self.subTest(values=values),self.assertRaises(ValueError): validate_record('order',{**row,**values})

    def test_batch_checks_every_record_and_rejects_duplicate_ids(self):
        row=company_fixture()['order'][0];original=copy.deepcopy(row)
        with self.assertRaises(ValueError): validate_batch('order',[row,{**row,'id':'bad','fulfilled':200}])
        with self.assertRaises(ValueError): validate_batch('order',[row,row])
        self.assertEqual(row,original)

    def test_explicit_synthetic_records_are_refused(self):
        with self.assertRaises(ValueError): validate_record('order',{**company_fixture()['order'][0],'synthetic':True})

    def test_practice_mode_preserves_synthetic_label_and_validation(self):
        row={**company_fixture()['order'][0],'synthetic':True}
        self.assertTrue(validate_record('order',row,allow_synthetic=True)['synthetic'])
        with self.assertRaises(ValueError): validate_record('order',{**row,'fulfilled':101},allow_synthetic=True)

    def test_empty_platform_has_no_default_inventory_or_forecast(self):
        result=snapshot({},0,0,today=DAY)
        self.assertEqual(result['inventory'],[]);self.assertEqual(result['forecasts'],[])

    def test_inventory_snapshots_do_not_generate_quantities(self):
        groups=company_fixture();groups['lot'][0]['expires']=(DAY-timedelta(days=1)).isoformat()
        result=snapshot(groups,1,1,today=DAY)
        self.assertEqual(result['inventory'][0]['usable'],0);self.assertEqual(result['inventory'][0]['expired'],50)

    def test_feature_windows_do_not_fill_missing_days_with_zero(self):
        groups=company_fixture();base=groups['order'][0]
        groups['order']=[{**base,'id':str(i),'date':(DAY-timedelta(days=i)).isoformat()} for i in range(14) if i!=3]
        rows=feature_rows(groups)
        self.assertTrue(all(day<(DAY-timedelta(days=3)).isoformat() for day,_,_ in rows))

    def test_capacities_use_latest_facility_snapshot(self):
        groups=company_fixture();groups['capacity'].append({**groups['capacity'][0],'id':'old','date':(DAY-timedelta(days=1)).isoformat(),'capacity_bottles':999})
        result=snapshot(groups,2,2,today=DAY)
        self.assertEqual(len(result['capacities']),1);self.assertEqual(result['capacities'][0]['capacity_bottles'],200)

    def test_scenario_results_depend_only_on_imported_snapshot_and_assumptions(self):
        snap=snapshot(company_fixture(),1,1,today=DAY)
        normal=scenario_metrics(snap,{'name':'normal','days':7,'demand_multiplier':1,'delay_days':0,'capacity_loss':0})
        outage=scenario_metrics(snap,{'name':'outage','days':7,'demand_multiplier':1,'delay_days':0,'capacity_loss':1})
        self.assertEqual(normal['demand'],700);self.assertEqual(outage['shortfall_lower_bound'],650)

    def test_proxy_is_scoped_to_operations_real(self):
        root=Path(__file__).resolve().parents[1]
        source=(root/'server.py').read_text(encoding='utf-8')
        self.assertIn('path.startswith("/operations/real/")',source)
        self.assertIn('path.startswith("/operations/real/api/")',source)
        self.assertNotIn('control_tower.sqlite',(root/'real_records/db.py').read_text())

class AllocationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try: import ortools
        except ImportError: raise unittest.SkipTest('Install OR-Tools to run solver checks')

    def solve(self,groups,**kwargs): return optimize(groups,snapshot(groups,1,1,today=DAY),**kwargs)

    def test_production_is_bounded_by_actual_raw_stock(self):
        result=self.solve(company_fixture())
        self.assertEqual(result['fulfilled'],150)
        self.assertEqual(sum(r['bottles'] for r in result['production']),100)

    def test_no_recipe_means_no_invented_production(self):
        groups=company_fixture();groups['sku_master']=[]
        self.assertEqual(self.solve(groups)['fulfilled'],50)

    def test_confirmed_receipt_bounds_procurement(self):
        groups=company_fixture();groups['inbound']=[{'id':'i','date':DAY.isoformat(),'material':'fruit','quantity_kg':5,'eta':DAY.isoformat(),'status':'CONFIRMED','mode':'ROAD'}]
        result=self.solve(groups)
        self.assertEqual(result['fulfilled'],200);self.assertAlmostEqual(result['procurement'][0]['kg'],5)
        groups['inbound'][0]['status']='PLANNED'
        self.assertEqual(self.solve(groups)['fulfilled'],150)

    def test_freshness_is_checked_at_horizon_end(self):
        groups=company_fixture();groups['lot'][0]['expires']=(DAY+timedelta(days=10)).isoformat();groups['capacity']=[]
        self.assertEqual(self.solve(groups)['fulfilled'],0)

    def test_closed_lane_does_not_allow_transfer(self):
        groups=company_fixture();groups['lot'][0]['depot']='S';groups['capacity']=[]
        groups['route']=[{'id':'r','date':DAY.isoformat(),'corridor':'S-N','status':'CONFIRMED_CLOSED','confirmed':True,'from_depot':'S','to_depot':'N'}]
        self.assertEqual(self.solve(groups)['transfers'],[])
        groups['route'][0]['status']='OPEN'
        result=self.solve(groups)
        self.assertEqual(result['fulfilled'],50);self.assertEqual(len(result['transfers']),1)

    def test_mixed_age_donor_cannot_reuse_fresh_batch_across_destinations(self):
        groups=company_fixture();groups['capacity']=[]
        groups['channel_master'][0]['min_remaining_days']=30
        groups['order'].append({**groups['order'][0],'id':'second','depot':'E'})
        groups['lot']=[{**groups['lot'][0],'id':'fresh','depot':'S'},
          {**groups['lot'][0],'id':'short','depot':'S','expires':(DAY+timedelta(days=10)).isoformat()}]
        groups['route']=[{'id':d,'date':DAY.isoformat(),'confirmed':True,'status':'OPEN','from_depot':'S','to_depot':d} for d in ('N','E')]
        result=self.solve(groups)
        self.assertEqual(result['fulfilled'],50)
        self.assertTrue(all(r['batch_id']=='fresh' for r in result['transfers']))

    def test_stale_orders_missing_rules_and_stream_lag_block_plan(self):
        groups=company_fixture();groups['order'][0]['date']=(DAY-timedelta(days=5)).isoformat()
        with self.assertRaisesRegex(ValueError,'Fresh orders'): self.solve(groups)
        groups=company_fixture();groups['channel_master']=[]
        with self.assertRaisesRegex(ValueError,'channel'): self.solve(groups)
        groups=company_fixture()
        with self.assertRaisesRegex(ValueError,'catching up'): optimize(groups,snapshot(groups,1,2,today=DAY))

if __name__=='__main__': unittest.main()
