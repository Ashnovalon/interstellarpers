import copy
import json
import os
import threading
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch
from urllib.request import Request, urlopen

from engine.external import poll_tomtom, poll_youtube
from engine.forecast import aggregate_orders, model_card
from engine.operations import Store, demo_records, local_today, plan, seed_demo, validate
from engine.replay import replay
from server import AppServer


DAY = date(2026, 10, 24)


class OperationalTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")

    def tearDown(self):
        self.store.close()

    def test_missing_feeds_are_unknown_not_zero_stock(self):
        result = plan(self.store, DAY)
        self.assertEqual(result["mode"], "NO OPERATIONAL FEEDS")
        self.assertEqual(result["metrics"]["critical_positions"], 0)
        self.assertEqual(result["quality"]["unknown_or_stale_stock_positions"], 45)
        self.assertTrue(all(p["quantity"] is None for p in result["positions"]))
        kinds = {a["kind"] for a in result["actions"]}
        self.assertIn("STOCK_DATA", kinds)
        self.assertIn("DATA_GAP", kinds)
        self.assertNotIn("SUPPLY", kinds)
        self.assertNotIn("TRANSFER", kinds)

    def test_demo_detects_orders_inventory_supply_and_road(self):
        seed_demo(self.store, DAY)
        result = plan(self.store, DAY)
        self.assertEqual(len(result["positions"]), 45)
        self.assertEqual(result["metrics"]["critical_positions"], 4)
        self.assertGreater(result["metrics"]["age_watch_positions"], 0)
        kinds = {a["kind"] for a in result["actions"]}
        self.assertTrue({"DEMAND", "TRANSFER", "SUPPLY", "ROAD", "AIR_REVIEW", "CAPACITY", "AGE"} <= kinds)
        self.assertNotIn("QUOTE", kinds)
        self.assertTrue(all(a["status"] == "PENDING" for a in result["actions"]))
        self.assertFalse(result["quality"]["order_feed_stale"])

    def test_external_attention_does_not_invent_bottle_demand(self):
        records = demo_records(DAY, viral=False, closure=False)
        for kind, rows in records.items():
            if rows:
                self.store.ingest(kind, rows)
        before = plan(self.store, DAY)["metrics"]["daily_demand_bottles"]
        for views in (1000, 1200, 1700):
            self.store.record_external("attention", {"state": "OBSERVED", "videos": [{"id": "campaign", "views": views}]})
        after = plan(self.store, DAY)
        self.assertEqual(before, after["metrics"]["daily_demand_bottles"])
        self.assertIn("ATTENTION_WATCH", {a["kind"] for a in after["actions"]})
        self.assertNotIn("DEMAND", {a["kind"] for a in after["actions"]})

    def test_public_attention_growth_uses_poll_intervals(self):
        self.store.record_external("attention", {"state":"OBSERVED","videos":[{"id":"v","views":1000}]})
        self.store.record_external("attention", {"state":"OBSERVED","videos":[{"id":"v","views":1200}]})
        now = datetime.now(timezone.utc)
        self.store.db.execute("UPDATE external_observations SET at=? WHERE seq=1", ((now-timedelta(minutes=60)).isoformat(),))
        self.store.db.execute("UPDATE external_observations SET at=? WHERE seq=2", ((now-timedelta(minutes=10)).isoformat(),))
        result = self.store.record_external("attention", {"state":"OBSERVED","videos":[{"id":"v","views":1700}]})
        self.assertGreater(result["view_growth_ratio"], 10)

    def test_import_validation_is_atomic_and_idempotent(self):
        valid = demo_records(DAY)["order"][0]
        result = self.store.ingest("order", [valid])
        self.assertEqual(result["changed"], 1)
        self.assertEqual(self.store.ingest("order", [valid])["changed"], 0)
        bad = dict(valid, id="bad", fulfilled=valid["requested"]+1)
        with self.assertRaises(ValueError):
            self.store.ingest("order", [dict(valid, id="new"), bad])
        self.assertEqual(len(self.store.records("order")), 1)
        with self.assertRaises(ValueError):
            validate("order", dict(valid, requested=1.5))
        with self.assertRaises(ValueError):
            validate("order", dict(valid, in_stock="maybe"))

    def test_preview_is_read_only_and_multiple_daily_orders_are_aggregated(self):
        rows = demo_records(DAY)["order"]
        first = next(r for r in rows if r["date"] == DAY.isoformat())
        another = dict(first, id="second-order-for-day", requested=100, fulfilled=90)
        checked = self.store.ingest("order", [first, another], dry_run=True)
        self.assertEqual(checked["received"], 2)
        self.assertEqual(checked["would_change"], 2)
        self.assertEqual(self.store.records("order"), [])
        self.store.ingest("order", [first, another])
        daily = aggregate_orders(self.store.records("order"))[(first["sku"],first["depot"],first["channel"])]
        self.assertEqual(daily[DAY.isoformat()]["requested"], first["requested"]+100)
        self.assertEqual(daily[DAY.isoformat()]["fulfilled"], first["fulfilled"]+90)

    def test_trained_forecast_activates_only_with_compatible_history(self):
        self.assertEqual(model_card()["status"], "VALIDATED")
        seed_demo(self.store, DAY)
        active = plan(self.store, DAY)
        self.assertEqual(active["forecast"]["model_positions"], 135)
        self.assertTrue(all(len(x["points"]) == 14 for x in active["forecast"]["series"]))
        self.assertGreater(active["forecast"]["series"][0]["points"][0]["high"], 0)
        # The same artifact cannot leak into dates preceding the training data end.
        earlier = plan(self.store, date(2026, 4, 1))
        self.assertEqual(earlier["forecast"]["model_positions"], 0)
        self.store.ingest("order", [{"id":"real-order", "date":DAY.isoformat(), "sku":"Dragon Passion",
            "depot":"D1", "channel":"QC", "requested":1000,"fulfilled":1000,"in_stock":True}])
        mixed = plan(self.store, DAY)
        self.assertEqual(mixed["forecast"]["model_positions"], 0)

    def test_approval_is_bound_to_current_recommendation_version(self):
        seed_demo(self.store, DAY)
        original = plan(self.store, DAY)
        action = next(a for a in original["actions"] if a["kind"] == "DEMAND")
        self.store.decide(action, "APPROVED", "Planner One", action["owner_role"], "Orders confirmed")
        approved = next(a for a in plan(self.store, DAY)["actions"] if a["id"] == action["id"])
        self.assertEqual(approved["status"], "APPROVED")
        changed = next(r for r in self.store.records("order") if r["sku"] == "Dragon Passion"
                       and r["channel"] == "QC" and r["date"] == DAY.isoformat())
        changed["requested"] += 2000
        changed["fulfilled"] += 2000
        self.store.ingest("order", [changed])
        current = next(a for a in plan(self.store, DAY)["actions"] if a["id"] == action["id"])
        self.assertNotEqual(current["version"], action["version"])
        self.assertEqual(current["status"], "PENDING")

    def test_expired_for_channel_batches_never_transfer(self):
        seed_demo(self.store, DAY)
        original = plan(self.store, DAY)
        transfers = [a for a in original["actions"] if a["kind"] == "TRANSFER"]
        self.assertTrue(transfers)
        donor_depots = {a["target"].split(":")[1] for a in transfers if a["target"].startswith("Dragon Passion:")}
        altered = []
        for r in self.store.records("lot"):
            if r["sku"] == "Dragon Passion" and r["depot"] in donor_depots:
                r["manufactured"] = (DAY-timedelta(days=28)).isoformat()
                r["expires"] = (DAY+timedelta(days=62)).isoformat()
                altered.append(r)
        self.store.ingest("lot", altered)
        result = plan(self.store, DAY)
        self.assertFalse(any(a["kind"] == "TRANSFER" and a["target"].startswith("Dragon Passion:")
                             for a in result["actions"]))

    def test_expired_physical_stock_is_quarantined_from_service(self):
        seed_demo(self.store, DAY)
        expired = {"id": "expired-physical", "date": DAY.isoformat(),
                   "sku": "Dragon Passion", "depot": "D1", "quantity": 5000,
                   "manufactured": (DAY-timedelta(days=95)).isoformat(),
                   "expires": (DAY-timedelta(days=5)).isoformat()}
        self.store.ingest("lot", [expired])
        result = plan(self.store, DAY)
        self.assertIn("EXPIRED_STOCK", {a["kind"] for a in result["actions"]})
        d1 = next(x for x in result["positions"] if x["sku"] == "Dragon Passion" and x["depot"] == "D1")
        control = Store(":memory:")
        try:
            seed_demo(control, DAY)
            original = next(x for x in plan(control, DAY)["positions"]
                            if x["sku"] == "Dragon Passion" and x["depot"] == "D1")
            self.assertEqual(d1["quantity"], original["quantity"])
        finally:
            control.close()

    def test_stale_route_cannot_be_treated_as_confirmed_current_closure(self):
        seed_demo(self.store, DAY)
        future = plan(self.store, DAY+timedelta(days=3))
        self.assertEqual(future["route"]["status"], "UNKNOWN")
        self.assertNotIn("AIR_REVIEW", {a["kind"] for a in future["actions"]})
        self.assertIn("ROUTE_STALE", {a["kind"] for a in future["actions"]})

    def test_road_receipts_are_excluded_during_confirmed_closure(self):
        seed_demo(self.store, DAY)
        closed = plan(self.store, DAY)
        passion = next(m for m in closed["materials"] if m["material"] == "passionfruit")
        self.assertEqual(passion["confirmed_inbound_next_14d_kg"], 0)
        self.store.ingest("route", [{"id": "demo-route", "date": DAY.isoformat(),
                                     "corridor": "PASSION_COOPERATIVE", "status": "OPEN", "confirmed": True}])
        opened = plan(self.store, DAY)
        passion_open = next(m for m in opened["materials"] if m["material"] == "passionfruit")
        self.assertEqual(passion_open["confirmed_inbound_next_14d_kg"], 5000)

    def test_new_sku_depot_and_channel_can_be_imported_together_with_rebalanced_shares(self):
        sku_rows = [
            {"id": "Mango Peach Basil", "date": DAY.isoformat(), "mix": .33,
             "recipe": {"mango": .08, "peach": .02, "basil": .001}},
            {"id": "Citrus Spark", "date": DAY.isoformat(), "mix": .05,
             "recipe": {"orange": .10}},
        ]
        self.store.ingest("sku_master", sku_rows)
        self.store.ingest("depot_master", [
            {"id": "D1", "date": DAY.isoformat(), "city": "Delhi", "region": "North", "share": .12},
            {"id": "D10", "date": DAY.isoformat(), "city": "Nagpur", "region": "Central", "share": .01},
        ])
        self.store.ingest("channel_master", [
            {"id": "GT", "date": DAY.isoformat(), "share": .50, "min_remaining_days": 0},
            {"id": "HORECA", "date": DAY.isoformat(), "share": .05, "min_remaining_days": 30},
        ])
        catalog = self.store.catalog(DAY)
        self.assertIn("Citrus Spark", catalog["skus"])
        self.assertIn("D10", catalog["depots"])
        self.assertIn("HORECA", catalog["channels"])
        self.store.ingest("order", [{"id": "new-order", "date": DAY.isoformat(),
                                     "sku": "Citrus Spark", "depot": "D10", "channel": "HORECA",
                                     "requested": 100, "fulfilled": 100, "in_stock": True}])
        result = plan(self.store, DAY)
        self.assertEqual(len(result["positions"]), 60)
        self.assertEqual(len(result["demand"]), 240)
        with self.assertRaises(ValueError):
            self.store.ingest("sku_master", [{"id": "Citrus Spark", "date": DAY.isoformat(),
                                               "mix": .20, "recipe": {"orange": .10}}])

    def test_quoted_air_requires_a_real_record(self):
        sample = demo_records(DAY)
        sample["freight_quote"] = []
        for kind, rows in sample.items():
            if rows:
                self.store.ingest(kind, rows)
        kinds = {a["kind"] for a in plan(self.store, DAY)["actions"]}
        self.assertIn("QUOTE", kinds)
        self.assertNotIn("AIR_REVIEW", kinds)

    def test_replay_advances_stock_and_uses_same_planner(self):
        result = replay()
        before = result["last_summer_planning"]
        after = result["approved_proposals"]
        self.assertTrue(before["viral_alert_on_second_day"])
        self.assertTrue(after["viral_alert_on_second_day"])
        self.assertGreater(after["transfer_bottles"], 0)
        self.assertGreater(result["difference"]["additional_fulfilled_bottles"], 0)
        self.assertGreater(result["difference"]["avoided_writeoff_bottles"], 0)
        self.assertEqual(before["requested_bottles"], after["requested_bottles"])
        for policy in (before, after):
            self.assertEqual(policy["requested_bottles"]-policy["fulfilled_bottles"], policy["unfulfilled_bottles"])
            self.assertLessEqual(policy["fulfilled_bottles"], policy["requested_bottles"])

    def test_official_connector_responses_are_only_watches(self):
        with patch.dict(os.environ, {"TOMTOM_API_KEY": "example", "PULP_ROUTE_BBOX": "1,1,2,2",
                                  "YOUTUBE_API_KEY": "example", "PULP_YOUTUBE_VIDEO_IDS": "abc"}):
            road = poll_tomtom(DAY, lambda _url: {"incidents": [{"properties": {"iconCategory": 8, "id": "i1"}}]})
            attention = poll_youtube(DAY, lambda _url: {"items": [{"id": "abc", "snippet": {"title": "Campaign"},
                                                                   "statistics": {"viewCount": "123"}}]})
        self.assertEqual(road["state"], "WATCH")
        self.assertEqual(attention["videos"][0]["views"], 123)
        self.assertNotIn("status", road)


class HttpTests(unittest.TestCase):
    def test_health_plan_ingest_decision_and_static_ui(self):
        app = AppServer(("127.0.0.1", 0), ":memory:")
        thread = threading.Thread(target=app.serve_forever, daemon=True)
        thread.start()
        root = f"http://127.0.0.1:{app.server_port}"
        def request(path, body=None):
            raw = json.dumps(body).encode() if body is not None else None
            headers = {"Content-Type": "application/json"} if body is not None else {}
            with urlopen(Request(root+path, data=raw, headers=headers), timeout=10) as response:
                data = response.read()
                return json.loads(data) if path.startswith("/api/") else data
        try:
            self.assertEqual(request("/api/health")["status"], "ok")
            self.assertIn(b"Operations Control Tower", request("/"))
            self.assertIn(b"live-chart", request("/"))
            self.assertIn(b"forecast-chart", request("/operations"))
            self.assertIn(b"renderForecast", request("/operations-v2.js"))
            self.assertTrue(request("/api/template?kind=route"))
            with app.lock:
                seed_demo(app.store, local_today())
            p = request("/api/plan")
            self.assertGreater(p["forecast"]["model_positions"], 0)
            order = request("/api/template?kind=order")[0]
            order["id"] = "http-preview-only"
            result = request("/api/validate", {"kind":"order","records":[order],"source":"test"})
            self.assertTrue(result["valid"])
            self.assertFalse(any(r["id"] == order["id"] for r in request("/api/records?kind=order")))
            action = next(a for a in p["actions"] if a["kind"] == "DEMAND")
            result = request("/api/decide", {"id": action["id"], "version": action["version"],
                                             "status": "APPROVED", "actor": "Planner Test",
                                             "role": action["owner_role"], "reason": "Confirmed orders"})
            self.assertEqual(result["status"], "APPROVED")
            self.assertTrue(any(a["status"] == "APPROVED" and a["id"] == action["id"]
                                for a in request("/api/plan")["actions"]))
        finally:
            app.shutdown()
            thread.join(timeout=5)
            app.server_close()


if __name__ == "__main__":
    unittest.main()
