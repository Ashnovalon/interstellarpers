"""Regressions found by the critical audit, beyond happy-path UI tests."""
import copy
import unittest
from unittest.mock import patch
from engine.live import LiveEngine, advance_world, new_world, rates_base, PLANT_CAPACITY, forecast_at


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.e=LiveEngine()
        self.e.control({"action":"reset","scenario":"sandbox","seed":77})
    def tearDown(self):self.e.close()
    def step(self,n=1):
        for _ in range(n):self.e.control({"action":"step"})
    def offer(self,kind):return next(a for a in self.e.snapshot()["actions"] if a["kind"]==kind and a["available"])
    def approve(self,a,choice="full",capture=True):
        return self.e.decide({"id":a["id"],"version":a["version"],"choice":choice,"actor":"Audit",
            "reason":"Regression scenario","checks_confirmed":True},capture_outcomes=capture)

    def test_copacker_does_not_produce_before_activation_boundary(self):
        w=new_world();w["capacity_factor"]=0;w["copacker_start"]=14;w["copacker_end"]=28
        advance_world(w,13.75,.25,rates_base(),self.e.state["inputs"])
        self.assertEqual(w["last_production"],0)

    def test_copacker_never_exceeds_fourteen_days_of_reserved_output(self):
        w=new_world();w["capacity_factor"]=0;w["copacker_start"]=14;w["copacker_end"]=28
        for day in range(13,29):advance_world(w,day,1,rates_base(),self.e.state["inputs"])
        self.assertLessEqual(w["metrics"]["produced"],14*.1*PLANT_CAPACITY)

    def test_repair_at_interval_end_does_not_create_earlier_production(self):
        w=new_world();w["capacity_factor"]=0
        w["commands"]=[{"kind":"REPAIR_PLANT","eta":2,"status":"SCHEDULED"}]
        advance_world(w,1.75,.25,rates_base(),self.e.state["inputs"])
        self.assertEqual(w["last_production"],0)
        self.assertEqual(w["capacity_factor"],1)

    def test_production_batches_keep_distinct_manufacturing_times(self):
        w=new_world()
        advance_world(w,0,.25,rates_base(),self.e.state["inputs"])
        advance_world(w,.25,.25,rates_base(),self.e.state["inputs"])
        lots=[x["lots"][0] for x in w["shipments"] if x["sku"]=="Dragon Passion" and x["to"]=="D1"]
        self.assertEqual(len({l["id"] for l in lots}),len(lots))

    def test_delayed_replan_lasts_seven_days_after_execution(self):
        self.e.inject("outage")
        self.approve(self.offer("REPLAN"),"delay",False)
        self.step(28)
        entry=next(d for d in self.e.state["decisions"] if d.get("kind")=="REPLAN")
        self.assertEqual(entry["status"],"ACTIVE")
        self.step(8)
        self.assertEqual(entry["status"],"COMPLETED")

    def test_quality_disruption_also_reaches_outcome_reference(self):
        self.e.inject("outage");self.approve(self.offer("REPAIR_PLANT"))
        self.e.inject("quality")
        track=self.e.state["outcome_tracks"][-1]
        self.assertGreater(track["shadow"]["world"]["held_raw"],0)
        self.assertEqual(track["shadow"]["world"]["held_raw"],self.e.state["world"]["held_raw"])

    def test_feed_restoration_is_not_given_free_to_wait_reference(self):
        self.e.inject("feed");self.approve(self.offer("RESTORE_FEED"))
        self.step()
        shadow=self.e.state["outcome_tracks"][-1]["shadow"]
        self.assertTrue(shadow["inputs"]["feed_outage"])

    def test_outcome_totals_include_deferred_execution_at_interval_end(self):
        self.e.inject("outage");self.approve(self.offer("REPAIR_PLANT"),"delay")
        self.step(8)
        outcome=self.e.snapshot()["outcomes"][-1]
        self.assertEqual(outcome["realized"]["contribution_vs_reference"],-250000)

    def test_midday_projection_uses_next_calendar_horizon_after_midnight(self):
        s=copy.deepcopy(self.e.state);s["day"]=.75;s["forecast_mode"]="trained"
        for k in s["model_curves"]:s["model_curves"][k]=list(range(100,114))
        self.assertEqual(set(forecast_at(s,.25).values()),{101})

    def test_forecast_chart_uses_selected_method(self):
        self.e.state["forecast_mode"]="nowcast"
        self.e._refresh_forecasts()
        curve=self.e.snapshot()["forecast_curves"]["Dragon Passion"]
        self.assertEqual(len(set(curve)),1)

    def test_timed_recovery_is_complete_at_displayed_end_time(self):
        self.e.inject("heatwave",lifecycle={"duration_days":1,"recovery_days":1})
        self.step(8)
        self.assertEqual(self.e.state["day"],2)
        self.assertEqual(self.e.state["inputs"]["heatwave"],1)
        self.assertEqual(self.e.state["lifecycles"][-1]["status"],"COMPLETED")

    def test_stale_trigger_cannot_be_approved_through_api(self):
        action=self.offer("BUFFER")
        self.e.state["offers"][action["id"]]["trigger_changed"]=True
        with self.assertRaises(ValueError):self.approve(action,capture=False)
        with self.assertRaises(ValueError):self.e.begin_review({"id":action["id"],"version":action["version"]})
        with self.assertRaises(ValueError):self.e.compare({"id":action["id"],"version":action["version"]})

    def test_aging_transfer_portfolio_does_not_reuse_same_stock(self):
        positions=self.e._positions()
        sku=positions[0]["sku"]
        group=[p for p in positions if p["sku"]==sku]
        donor=group[0]
        for p in positions:
            p.update(quantity=100000,eligible=0,gt_eligible=0,daily_precise=1000,cover=100,status="HEALTHY",inbound=0)
        donor["gt_eligible"]=10000
        for p in group[1:]:p.update(quantity=0,cover=0,status="CRITICAL")
        self.e.state["offers"]={}
        with patch.object(self.e,"_positions",return_value=positions):self.e._refresh_offers()
        planned=[a for a in self.e.state["offers"].values() if a["kind"]=="GT_TRANSFER" and a["params"]["from"]==donor["depot"] and a["params"]["sku"]==sku]
        self.assertGreater(len(planned),0)
        self.assertLessEqual(sum(a["params"]["quantity"] for a in planned),10000)


if __name__=="__main__":unittest.main()
