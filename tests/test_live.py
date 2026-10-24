import copy
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from engine.live import LiveEngine, MATERIALS, stock_total, generate_inputs, OTHER_SPATIAL_FACTOR
from server import AppServer


class LiveTests(unittest.TestCase):
    def setUp(self):
        self.engine=LiveEngine()
        self.engine.control({"action":"reset","scenario":"sandbox","seed":77})

    def tearDown(self):
        self.engine.close()

    def step(self,n=1):
        for _ in range(n):
            self.engine.control({"action":"step"})
        return self.engine.snapshot()

    def offer(self,kind):
        return next(x for x in self.engine.snapshot()["actions"] if x["kind"]==kind and x.get("available",True))

    def decide(self,offer,status="APPROVED",**extra):
        return self.engine.decide({"id":offer["id"],"version":offer["version"],"status":status,
            "actor":"Test planner","reason":"Verified synthetic evidence","checks_confirmed":True,**extra})

    def assert_conserved(self):
        self.assertEqual(self.engine.snapshot()["metrics"]["bottle_conservation_error"],0)
        for world in (self.engine.state["world"],self.engine.state["baseline"]):
            m=world["metrics"]
            for material in MATERIALS:
                remaining=world["raw"][material]+(world["held_raw"] if material=="passionfruit" else 0)
                expected=m["raw_initial"][material]+m["raw_received"][material]-m["raw_consumed"][material]-m["raw_disposed"][material]
                self.assertAlmostEqual(remaining,expected,places=5)
                self.assertGreaterEqual(remaining,-1e-6)

    def test_tick_conserves_physical_stock_and_raw_materials(self):
        self.engine.inject("viral");self.step(12)
        self.engine.inject("closure");self.step(12)
        self.engine.inject("outage");self.step(4)
        self.assert_conserved()
        self.assertEqual(self.engine.state["world"]["metrics"]["requested"],self.engine.state["baseline"]["metrics"]["requested"])

    def test_input_records_match_generator_equation_and_interval_totals(self):
        state=self.step()
        batch=state["latest_inputs"]
        self.assertEqual(len(batch["rows"]),135)
        self.assertEqual(sum(x["requested"] for x in batch["rows"]),batch["requested"])
        import math
        for row in batch["rows"]:
            self.assertAlmostEqual(row["daily_rate"],row["baseline_daily"]*math.prod(row["factors"].values()),places=7)
            self.assertEqual(row["requested"],round(row["daily_rate"]*batch["dt"]))
            self.assertLessEqual(row["fulfilled"],row["requested"])
        from engine.operations import DEPOTS
        total=sum(v[2]*(1.3 if d in {"D1","D3","D6"} else .65 if d in {"D8","D9"} else OTHER_SPATIAL_FACTOR) for d,v in DEPOTS.items())
        self.assertAlmostEqual(total,1,places=12)

    def test_review_holds_clock_until_decision_and_resumes_prior_state(self):
        action=self.offer("BUFFER")
        self.engine.control({"action":"start"})
        opened=self.engine.begin_review({"id":action["id"],"version":action["version"]})
        self.assertFalse(self.engine.state["running"])
        before=self.engine.state["day"]
        with self.assertRaises(ValueError):self.engine.control({"action":"step"})
        self.assertEqual(before,self.engine.state["day"])
        result=self.decide(action,choice="wait",review_token=opened["review_token"],checks_confirmed=False)
        self.assertTrue(result["running"])
        self.assertIsNone(result["review"])
        self.assertEqual(result["decisions"][-1]["status"],"WAITED")
        self.assertEqual(self.engine.state["cash_buffer"],0)
        self.engine.control({"action":"pause"})

    def test_offer_has_at_least_ten_ticks_at_every_speed(self):
        self.engine.control({"action":"speed","days_per_tick":1})
        self.engine.inject("quality")
        action=self.offer("LAB_TEST")
        self.assertGreaterEqual(action["wall_seconds"],10)
        self.step(9)
        current=self.engine.state["offers"][action["id"]]
        self.assertEqual(current["version"],action["version"])
        self.assertEqual(current["status"],"PENDING")
        self.step()
        self.assertTrue(any(d["status"]=="EXPIRED" and d["kind"]=="LAB_TEST" for d in self.engine.state["decisions"]))

    def test_delayed_choice_reserves_cash_then_executes_with_revalidation(self):
        self.engine.inject("outage")
        action=self.offer("REPAIR_PLANT")
        self.decide(action,choice="delay")
        self.assertEqual(self.engine.state["decisions"][-1]["status"],"WAITING")
        self.assertEqual(self.engine.state["world"]["metrics"]["repair_cost"],0)
        self.assertEqual(self.engine.snapshot()["metrics"]["budget_remaining"],12750000)
        self.step(8)
        self.assertEqual(self.engine.state["world"]["metrics"]["repair_cost"],250000)
        self.assertEqual(self.engine.state["decisions"][-1]["status"],"SCHEDULED")
        self.step(8)
        self.assertEqual(self.engine.state["world"]["capacity_factor"],1)

    def test_paused_disruption_produces_a_visible_affected_input_batch(self):
        state=self.engine.inject("heatwave",step_if_paused=True)
        self.assertEqual(state["tick"],1)
        self.assertFalse(state["running"])
        self.assertTrue(all(row["factors"]["weather"]==1.25 for row in state["latest_inputs"]["rows"]))
        self.assertEqual(state["last_input_change"]["changes"][0]["field"],"heatwave")

    def test_manual_inputs_cancel_future_guided_overrides(self):
        self.engine.control({"action":"reset","scenario":"guided","seed":77})
        self.engine.inject("rumor")
        self.step(8)
        self.assertEqual(self.engine.state["scenario"],"sandbox")
        self.assertEqual(self.engine.state["inputs"]["conversion"],0)
        self.assertTrue(all(x["done"] for x in self.engine.state["scheduled_events"]))

    def test_interval_contribution_includes_costs_paid_between_ticks(self):
        self.step()
        self.engine.inject("closure")
        self.decide(self.offer("AIR"))
        self.step()
        tape=self.engine.state["tape"]
        from engine.live import contribution
        self.assertAlmostEqual(sum(x["tick_contribution"] for x in tape),contribution(self.engine.state["world"]),places=5)
        self.assertLess(tape[-1]["tick_contribution"],0)
        self.assertGreater(tape[-1]["tick_revenue"],0)

    def test_demand_regimes_are_not_identical_after_a_week(self):
        first=generate_inputs(self.engine.state)
        other=copy.deepcopy(self.engine.state);other["day"]=7
        week_later=generate_inputs(other)
        self.assertNotEqual([x["daily_rate"] for x in first],[x["daily_rate"] for x in week_later])

    def test_comparison_financial_identity_and_service_arithmetic(self):
        self.engine.inject("viral");self.step(8)
        action=self.offer("TRANSFER")
        result=self.engine.compare({"id":action["id"],"version":action["version"]})
        self.assertEqual(len(result["branches"]),4)
        for row in result["branches"]:
            self.assertEqual(row["requested"],row["fulfilled"]+row["unfulfilled"])
            self.assertAlmostEqual(row["service_pct"],100*row["fulfilled"]/row["requested"],places=2)
            self.assertAlmostEqual(row["contribution_vs_wait"],row["service_value_vs_wait"]-row["extra_cost_vs_wait"],delta=1)
        delayed=next(x for x in result["branches"] if x["id"]=="delay")
        self.assertFalse(delayed["issue"] and 'Fresh warehouse' in delayed["issue"])

    def test_attention_without_conversion_does_not_leak_into_forecast(self):
        other=LiveEngine()
        try:
            other.control({"action":"reset","scenario":"sandbox","seed":77})
            self.engine.inject("rumor")
            self.step(8)
            for _ in range(8):other.control({"action":"step"})
            self.assertEqual(self.engine.state["world"]["last_orders"],other.state["world"]["last_orders"])
            self.assertEqual(self.engine.state["forecast_rates"],other.state["forecast_rates"])
        finally:other.close()

    def test_observed_viral_orders_adapt_nowcast_between_daily_boundaries(self):
        before=self.engine.snapshot()["market"][-1]["forecast"]
        regional_before=self.engine.state["forecast_rates"]["Dragon Passion|D1|QC"]
        self.engine.inject("viral")
        after=self.step(3)
        self.assertEqual(after["day"],.75)
        self.assertGreater(after["market"][-1]["forecast"],before*1.01)
        self.assertGreater(self.engine.state["forecast_rates"]["Dragon Passion|D1|QC"],regional_before*1.2)
        self.assertEqual(len(after["forecast_curves"]["Dragon Passion"]),14)
        self.assertEqual(len(self.engine.state["history"][next(iter(self.engine.state["history"]))]),14)

    def test_partial_day_is_not_trained_as_complete_when_speed_changes(self):
        self.step()
        self.engine.control({"action":"speed","days_per_tick":1})
        result=self.step()
        self.assertEqual(result["day"],1)
        self.assertEqual(self.engine.state["last_dt"],.75)
        self.assertEqual(sum(x["actual"] for x in self.engine.state["daily_scores"]),self.engine.state["world"]["metrics"]["requested"])

    def test_feed_loss_freezes_observations_but_not_physical_business(self):
        self.step(2)
        before=copy.deepcopy(self.engine.state["forecast_rates"])
        stock=copy.deepcopy(self.engine.state["reported_stock"])
        self.engine.inject("feed");self.engine.inject("viral");self.step(5)
        self.assertEqual(self.engine.state["forecast_rates"],before)
        self.assertEqual(self.engine.state["reported_stock"],stock)
        self.assertGreater(self.engine.snapshot()["feed_age_days"],1)
        self.decide(self.offer("RESTORE_FEED"));self.step()
        self.assertFalse(self.engine.snapshot()["inputs"]["feed_outage"])
        self.assertNotEqual(self.engine.state["reported_stock"],stock)
        self.assert_conserved()

    def test_approved_allocation_does_not_use_hidden_stock_during_feed_loss(self):
        self.engine.inject("viral");self.step(8)
        self.decide(self.offer("REPLAN"));self.step()
        weights=copy.deepcopy(self.engine.state["world"]["allocation_weights"])
        self.engine.inject("feed");self.step(3)
        self.assertEqual(self.engine.state["world"]["allocation_weights"],weights)

    def test_approval_reserves_stock_and_arrives_only_after_transit(self):
        self.engine.inject("viral");self.step(8)
        action=self.offer("TRANSFER")
        donor=action["params"]["sku"]+"|"+action["params"]["from"]
        initial=stock_total(self.engine.state["world"],donor,self.engine.state["day"])
        self.decide(action)
        after=stock_total(self.engine.state["world"],donor,self.engine.state["day"])
        self.assertEqual(initial-after,action["params"]["quantity"])
        entry=self.engine.state["decisions"][-1]
        self.assertEqual(entry["status"],"DISPATCHED")
        self.assertGreater(entry["eta"],self.engine.state["day"])
        with self.assertRaises(ValueError):self.decide(action)
        self.step(16)
        self.assertEqual(next(x for x in self.engine.state["decisions"] if x.get("execution_id")==entry["execution_id"])["status"],"RECEIVED")
        self.assert_conserved()

    def test_reject_or_expire_does_not_execute_and_old_run_cannot_approve(self):
        action=self.offer("BUFFER")
        self.decide(action,"REJECTED")
        self.assertEqual(self.engine.state["cash_buffer"],0)
        self.step(20)
        stale=self.offer("BUFFER")
        self.engine.control({"action":"reset","scenario":"sandbox","seed":77})
        with self.assertRaises(ValueError):self.decide(stale)
        self.assertEqual(self.engine.state["cash_buffer"],0)

    def test_closure_blocks_road_receipts_and_air_is_explicit(self):
        self.step(16)
        self.engine.inject("closure")
        received=self.engine.state["world"]["metrics"]["raw_received"]["passionfruit"]
        self.step(8)
        self.assertEqual(received,self.engine.state["world"]["metrics"]["raw_received"]["passionfruit"])
        action=self.offer("AIR");self.decide(action)
        self.assertEqual(received,self.engine.state["world"]["metrics"]["raw_received"]["passionfruit"])
        self.step(8)
        self.assertGreater(self.engine.state["world"]["metrics"]["raw_received"]["passionfruit"],received)
        self.assert_conserved()

    def test_other_input_edits_do_not_restart_a_known_closure(self):
        self.engine.inject("closure")
        reopen=self.engine.state["road_reopens"]
        self.step(3)
        self.engine.inputs({"road_closed":True,"closure_days":21,"heatwave":1.2})
        self.assertEqual(self.engine.state["road_reopens"],reopen)

    def test_import_delay_has_an_explicit_qualified_supplier_intervention(self):
        self.engine.inject("imports")
        action=self.offer("AIR_DRAGON")
        self.assertEqual(action["params"]["material"],"dragonfruit")
        self.decide(action)
        entry=self.engine.state["decisions"][-1]
        self.step(20)
        self.assertEqual(next(x for x in self.engine.state["decisions"] if x.get("execution_id")==entry["execution_id"])["status"],"RECEIVED")
        self.assert_conserved()

    def test_copacker_needs_14_days_and_reserves_its_maximum_cash(self):
        self.engine.inputs({"plant_availability":.65})
        action=self.offer("COPACKER")
        buffer=self.offer("BUFFER")
        self.decide(action)
        self.assertLess(self.engine.snapshot()["metrics"]["budget_remaining"],500000)
        with self.assertRaises(ValueError):self.decide(buffer)
        self.step(52)
        self.assertEqual(self.engine.state["world"]["metrics"]["copacker_cost"],0)
        self.step(8)
        self.assertGreater(self.engine.state["world"]["metrics"]["copacker_cost"],0)
        self.assert_conserved()

    def test_maintenance_restores_existing_capacity_only_after_completion(self):
        self.engine.inject("outage")
        action=self.offer("REPAIR_PLANT")
        self.decide(action)
        self.assertEqual(self.engine.state["world"]["capacity_factor"],.65)
        self.step(7)
        self.assertEqual(self.engine.state["world"]["capacity_factor"],.65)
        self.step()
        self.assertEqual(self.engine.state["world"]["capacity_factor"],1)
        self.assertEqual(self.engine.state["baseline"]["capacity_factor"],.65)
        self.assert_conserved()

    def test_quality_requires_test_and_separate_release(self):
        self.engine.inject("quality")
        held=self.engine.state["world"]["held_raw"]
        self.assertGreater(held,0)
        self.assertFalse(any(x["kind"]=="RELEASE_QA" for x in self.engine.snapshot()["actions"]))
        self.decide(self.offer("LAB_TEST"));self.step(4)
        self.assertEqual(self.engine.state["world"]["held_raw"],held)
        self.decide(self.offer("RELEASE_QA"))
        self.assertEqual(self.engine.state["world"]["held_raw"],0)
        self.assert_conserved()

    def test_failed_quality_batch_is_never_returned_to_production(self):
        self.engine.inputs({"quality_result":"FAIL"});self.engine.inject("quality")
        self.decide(self.offer("LAB_TEST"));self.step(4)
        self.assertEqual(self.engine.state["world"]["held_raw"],0)
        self.assertGreater(self.engine.state["world"]["metrics"]["raw_disposed"]["passionfruit"],0)
        self.assertFalse(any(x["kind"]=="RELEASE_QA" for x in self.engine.snapshot()["actions"]))
        self.assert_conserved()

    def test_changed_lab_assumption_invalidates_the_old_test_offer(self):
        self.engine.inject("quality")
        old=self.offer("LAB_TEST")
        self.engine.inputs({"quality_result":"FAIL"})
        current=self.offer("LAB_TEST")
        self.assertNotEqual(current["version"],old["version"])
        with self.assertRaises(ValueError):self.decide(old)
        self.decide(current);self.step(4)
        self.assertGreater(self.engine.state["world"]["metrics"]["raw_disposed"]["passionfruit"],0)

    def test_branching_is_read_only_and_uses_no_hidden_conversion(self):
        self.engine.inject("viral");self.step(8)
        action=self.offer("TRANSFER")
        before=copy.deepcopy(self.engine.state)
        branches=self.engine.compare({"id":action["id"],"version":action["version"]})
        self.assertEqual(before,self.engine.state)
        self.assertEqual(len(branches["branches"]),4)
        self.engine.state["inputs"]["conversion"]=0
        second=self.engine.compare({"id":action["id"],"version":action["version"]})
        self.assertEqual(branches["branches"],second["branches"])

    def test_invalid_inputs_and_unconfirmed_decisions_are_atomic(self):
        before=copy.deepcopy(self.engine.state)
        for value in (float('nan'),-1,10,True):
            with self.assertRaises(ValueError):self.engine.inputs({"plant_availability":value})
        with self.assertRaises(ValueError):self.decide(self.offer("BUFFER"),checks_confirmed=False)
        self.assertEqual(before,self.engine.state)

    def test_run_persists_and_exports_every_input_batch(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"test.sqlite"
            engine=LiveEngine(path)
            engine.control({"action":"step"})
            run=engine.snapshot()["run_id"]
            events=engine.export_events()
            tick=next(x for x in events["events"] if x["kind"]=="TICK")
            self.assertEqual(len(tick["payload"]["detail"]["order_batches"]),135)
            engine.close()
            engine=LiveEngine(path)
            try:
                self.assertEqual(engine.snapshot()["run_id"],run)
                self.assertEqual(engine.snapshot()["tick"],1)
                self.assertFalse(engine.snapshot()["running"])
            finally:engine.close()


class LiveHttpTests(unittest.TestCase):
    def test_real_disruption_and_review_endpoints_expose_inputs_and_hold_time(self):
        app=AppServer(("127.0.0.1",0),":memory:")
        thread=threading.Thread(target=app.serve_forever,daemon=True);thread.start()
        root=f"http://127.0.0.1:{app.server_port}"
        def request(path,body=None):
            payload=json.dumps(body).encode() if body is not None else None
            headers={"Content-Type":"application/json"} if payload else {}
            with urlopen(Request(root+path,data=payload,headers=headers),timeout=10) as response:return json.loads(response.read())
        try:
            changed=request('/api/live/inject',{'preset':'heatwave','step_if_paused':True})
            self.assertEqual(changed['tick'],1)
            self.assertEqual(changed['scenario'],'sandbox')
            self.assertTrue(all(r['factors']['weather']==1.25 for r in changed['latest_inputs']['rows']))
            request('/api/live/inject',{'preset':'quality'})
            before=request('/api/live/control',{'action':'start'})
            offer=next(x for x in before['actions'] if x['kind']=='LAB_TEST')
            opened=request('/api/live/review/open',{'id':offer['id'],'version':offer['version']})
            frozen_tick=opened['state']['tick']
            time.sleep(1.1)
            self.assertEqual(request('/api/live/state')['tick'],frozen_tick)
            result=request('/api/live/decide',{'id':offer['id'],'version':offer['version'],'choice':'wait',
                'actor':'API operator','reason':'Wait for further evidence','review_token':opened['review_token']})
            self.assertTrue(result['running'])
            self.assertEqual(result['decisions'][-1]['status'],'WAITED')
            request('/api/live/control',{'action':'pause'})
        finally:
            app.shutdown();thread.join(timeout=3);app.server_close()

    def test_stream_publishes_state_and_manual_tick_without_page_polling(self):
        app=AppServer(("127.0.0.1",0),":memory:")
        thread=threading.Thread(target=app.serve_forever,daemon=True);thread.start()
        root=f"http://127.0.0.1:{app.server_port}"
        stream=None
        try:
            stream=urlopen(root+"/api/live/stream",timeout=5)
            self.assertEqual(stream.headers.get_content_type(),"text/event-stream")
            def snapshot():
                while True:
                    line=stream.readline().decode('utf-8')
                    if line.startswith('data: '):return json.loads(line[6:])
            first=snapshot()
            raw=json.dumps({"action":"step"}).encode()
            with urlopen(Request(root+"/api/live/control",data=raw,headers={"Content-Type":"application/json"}),timeout=5) as response:
                self.assertEqual(response.status,200)
            second=snapshot()
            self.assertGreater(second["tick"],first["tick"])
            with urlopen(root+"/") as response:self.assertIn(b"Disruption studio",response.read())
        finally:
            if stream:stream.close()
            app.shutdown();thread.join(timeout=3);app.server_close()

    def test_token_protects_live_state_stream_and_mutation(self):
        with patch.dict(os.environ,{"CONTROL_TOWER_TOKEN":"local-test-token"}):
            app=AppServer(("127.0.0.1",0),":memory:")
        thread=threading.Thread(target=app.serve_forever,daemon=True);thread.start()
        root=f"http://127.0.0.1:{app.server_port}"
        try:
            for path in ("/api/live/state","/api/live/stream"):
                with self.assertRaises(HTTPError) as error:urlopen(root+path)
                self.assertEqual(error.exception.code,401)
            request=Request(root+"/api/live/state",headers={"Authorization":"Bearer local-test-token"})
            with urlopen(request) as response:self.assertEqual(response.status,200)
        finally:
            app.shutdown();thread.join(timeout=3);app.server_close()


if __name__=='__main__':unittest.main()
