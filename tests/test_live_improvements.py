import copy
import math
import unittest
import tempfile
from pathlib import Path

from engine.allocation import allocate
from engine.live import LiveEngine, forecast_at, simulation_interval, contribution


class AllocationTests(unittest.TestCase):
    def test_unused_capacity_is_redistributed_around_an_ingredient_outage(self):
        result=allocate({"blocked":100,"open":100},{"blocked":1,"open":1},100,
            {"a":0,"b":100},{"blocked":{"a":1},"open":{"b":1}})
        self.assertEqual(result,{"blocked":0,"open":100})

    def test_shared_material_is_fair_and_iteration_order_does_not_choose_winner(self):
        caps={"first":100,"second":100};weights={"first":1,"second":1}
        recipes={p:{"shared":1} for p in caps}
        result=allocate(caps,weights,200,{"shared":50},recipes)
        reverse=allocate(dict(reversed(list(caps.items()))),weights,200,{"shared":50},recipes)
        self.assertEqual(result,{"first":25,"second":25})
        self.assertEqual(result,reverse)

    def test_caps_capacity_and_multiple_material_constraints_are_respected(self):
        caps={"blend":90,"single":40,"other":100};weights={"blend":4,"single":2,"other":1}
        recipes={"blend":{"a":2,"b":1},"single":{"a":1},"other":{"b":1}}
        result=allocate(caps,weights,100,{"a":80,"b":60},recipes)
        self.assertLessEqual(sum(result.values()),100)
        for p,qty in result.items():self.assertLessEqual(qty,caps[p])
        for material,stock in {"a":80,"b":60}.items():
            self.assertLessEqual(sum(qty*recipes[p].get(material,0) for p,qty in result.items()),stock)


class ImprovementTests(unittest.TestCase):
    def setUp(self):
        self.engine=LiveEngine()
        self.engine.control({"action":"reset","scenario":"sandbox","seed":77})

    def tearDown(self):self.engine.close()

    def action(self,kind):
        return next(a for a in self.engine.snapshot()["actions"] if a["kind"]==kind and a["available"])

    def approve(self,action,**extra):
        return self.engine.decide({"id":action["id"],"version":action["version"],"choice":"full",
            "actor":"Test operator","reason":"Verify improvements","checks_confirmed":True,**extra})

    def step(self,count=1):
        for _ in range(count):self.engine.control({"action":"step"})

    def test_comparison_uses_live_interval_and_covers_copacker_operating_period(self):
        self.engine.inject("outage")
        action=self.action("COPACKER")
        for speed in (.125,.5,1):
            self.engine.control({"action":"speed","days_per_tick":speed})
            result=self.engine.compare({"id":action["id"],"version":action["version"]})
            self.assertEqual(result["step_days"],speed)
            self.assertGreaterEqual(result["horizon_days"],30)
            self.assertEqual(len({b["requested"] for b in result["branches"]}),1)
            for branch in result["branches"]:
                points=branch["trajectory"]
                self.assertEqual(points[0]["day"],speed)
                self.assertEqual(points[-1]["day"],result["end_day"])
                self.assertLessEqual(max(b["day"]-a["day"] for a,b in zip(points,points[1:])),speed+.001)

    def test_season_end_is_a_hard_projection_boundary(self):
        action=self.action("BUFFER")
        self.engine.state["day"]=111.5
        result=self.engine.compare({"id":action["id"],"version":action["version"]})
        self.assertEqual(result["end_day"],112)
        self.assertEqual(result["horizon_days"],.5)
        self.assertTrue(result["horizon_truncated"])

    def test_recovery_is_scheduled_progressive_and_visible_to_comparison(self):
        self.engine.inject("heatwave",lifecycle={"duration_days":1,"recovery_days":1})
        self.step(4)
        self.assertEqual(self.engine.state["inputs"]["heatwave"],1.25)
        self.step(3)
        self.assertLess(self.engine.state["inputs"]["heatwave"],1.25)
        self.assertGreater(self.engine.state["inputs"]["heatwave"],1)
        self.step(2)
        self.assertEqual(self.engine.state["inputs"]["heatwave"],1)
        self.assertEqual(self.engine.state["lifecycles"][-1]["status"],"COMPLETED")
        self.assertTrue(any(m["kind"]=="RECOVERY_END" for m in self.engine.snapshot()["markers"]))

    def test_manual_override_does_not_get_undone_by_an_old_recovery(self):
        self.engine.inject("heatwave",lifecycle={"duration_days":1})
        self.engine.inputs({"heatwave":1.4})
        self.step(8)
        self.assertEqual(self.engine.state["inputs"]["heatwave"],1.4)

    def test_quality_cannot_be_released_by_a_timer(self):
        before=copy.deepcopy(self.engine.state)
        with self.assertRaises(ValueError):self.engine.inject("quality",lifecycle={"duration_days":1})
        self.assertEqual(before,self.engine.state)

    def test_comparison_includes_known_recovery_without_mutating_live_state(self):
        self.engine.inject("outage",lifecycle={"duration_days":1,"recovery_days":1})
        action=self.action("REPAIR_PLANT");before=copy.deepcopy(self.engine.state)
        scheduled=self.engine.compare({"id":action["id"],"version":action["version"]})
        self.assertEqual(before,self.engine.state)
        permanent=copy.deepcopy(before);permanent["lifecycles"]=[]
        self.engine.state=permanent;self.engine.comparison_cache.clear()
        other=self.engine.compare({"id":action["id"],"version":action["version"]})
        # Opening inventory can mask the service impact. Production is the direct
        # consequence of known capacity recovery even while both serve all orders.
        self.assertGreater(scheduled["branches"][0]["produced"],other["branches"][0]["produced"])

    def test_timed_road_closure_does_not_reclose_during_recovery(self):
        self.engine.inject("closure",lifecycle={"duration_days":1,"recovery_days":2})
        self.step(5)
        self.assertFalse(self.engine.state["inputs"]["road_closed"])
        self.step(8)
        self.assertFalse(self.engine.state["inputs"]["road_closed"])

    def test_approval_saves_projection_evidence_and_realized_reference(self):
        self.engine.inject("outage")
        action=self.action("REPAIR_PLANT")
        self.approve(action)
        track=self.engine.state["outcome_tracks"][-1]
        self.assertEqual(track["projection"]["id"],"full")
        self.assertTrue(track["evidence"]["calculations"])
        self.assertEqual(track["shadow"]["world"]["metrics"]["repair_cost"],0)
        self.assertEqual(self.engine.state["world"]["metrics"]["repair_cost"],250000)
        self.step()
        result=self.engine.snapshot()["outcomes"][-1]
        self.assertNotIn("shadow",result)
        self.assertEqual(result["realized"]["contribution_vs_reference"],-250000)
        self.approve(self.action("REPLAN"))
        self.assertEqual(track["subsequent_actions"],1)
        track["end_day"]=self.engine.state["day"]+.125
        self.step()
        self.assertEqual(track["status"],"COMPLETED")
        self.assertNotIn("shadow",track)
        self.assertEqual(self.engine.snapshot()["metrics"]["bottle_conservation_error"],0)

    def test_four_forecasters_change_predictions_without_changing_generated_requests(self):
        from engine.live import generate_inputs
        expected=generate_inputs(self.engine.state)
        for mode in ("blend","trained","nowcast","seasonal"):
            self.engine.state["forecast_mode"]=mode
            rates=forecast_at(self.engine.state)
            self.assertEqual(len(rates),135)
            self.assertTrue(all(math.isfinite(v) and v>=0 for v in rates.values()))
            self.assertEqual(generate_inputs(self.engine.state),expected)

    def test_approval_evidence_uses_pre_execution_stock_and_survives_restart(self):
        self.engine.inject("viral");self.step(8)
        action=self.action("TRANSFER")
        comparison=self.engine.compare({"id":action["id"],"version":action["version"]})
        self.approve(action)
        track=self.engine.state["outcome_tracks"][-1]
        self.assertEqual(track["evidence"],comparison["evidence"])
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"persist.sqlite"
            other=LiveEngine(path)
            other.state=copy.deepcopy(self.engine.state)
            other._persist("TEST_SAVE","Persist outcome reference")
            other.close()
            restored=LiveEngine(path)
            try:
                self.assertEqual(restored.state["outcome_tracks"][-1]["id"],track["id"])
                restored.control({"action":"step"})
                self.assertIsNotNone(restored.snapshot()["outcomes"][-1]["realized"])
                self.assertFalse(restored.state["running"])
            finally:restored.close()


class ImprovementHttpTests(unittest.TestCase):
    def test_timed_input_and_benchmark_report_are_available_over_http(self):
        import json
        import threading
        from urllib.request import Request,urlopen
        from server import AppServer
        app=AppServer(("127.0.0.1",0),":memory:")
        thread=threading.Thread(target=app.serve_forever,daemon=True);thread.start()
        root=f"http://127.0.0.1:{app.server_port}"
        try:
            payload=json.dumps({"preset":"heatwave","lifecycle":{"duration_days":2,"recovery_days":1},"step_if_paused":True}).encode()
            with urlopen(Request(root+"/api/live/inject",data=payload,headers={"Content-Type":"application/json"})) as response:
                state=json.load(response)
            self.assertEqual(state["lifecycles"][-1]["recover_at"],2)
            self.assertTrue(state["markers"])
            with urlopen(root+"/api/live/benchmarks") as response:report=json.load(response)
            self.assertEqual({r["mode"] for r in report["summary"]},{"blend","nowcast","trained","seasonal"})
            self.assertIn("current_source",report)
        finally:app.shutdown();thread.join(timeout=3);app.server_close()


if __name__=="__main__":unittest.main()
