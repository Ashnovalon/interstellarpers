"""Pulp Riot operational decision engine.

All sample quantities beyond the published case are labelled SYNTHETIC.  The
engine never dispatches a physical order; approval is a recorded business
decision which must be revalidated by an execution integration.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


SKUS = {
    "Mango Peach Basil": {"mix": .38, "recipe": {"mango": .08, "peach": .02, "basil": .001}},
    "Guava Chilli": {"mix": .20, "recipe": {"guava": .10, "chilli": .001}},
    "Passionfruit Punch": {"mix": .16, "recipe": {"passionfruit": .10}},
    "Dragonfruit Bloom": {"mix": .14, "recipe": {"dragonfruit": .10}},
    "Dragon Passion": {"mix": .12, "recipe": {"passionfruit": .06, "dragonfruit": .04}},
}
DEPOTS = {
    "D1": ("Delhi", "North", .13), "D2": ("Jaipur", "North", .09),
    "D3": ("Mumbai", "West", .16), "D4": ("Pune", "West", .12),
    "D5": ("Ahmedabad", "West", .08), "D6": ("Bengaluru", "South", .16),
    "D7": ("Chennai", "South", .12), "D8": ("Kolkata", "East", .08),
    "D9": ("Bhubaneswar", "East", .06),
}
CHANNELS = {"GT": .55, "MT": .25, "QC": .20}
CASE = {
    "summer_bottles": 96_000_000, "model_summer_days": 112,
    "price_rupees": 60, "contribution_margin": .32,
    "plant_bottles_per_28_days": 25_000_000,
    "copacker_extra_share": .10, "copacker_notice_days": 14,
    "transfer_rupees_per_bottle": 1.5, "transfer_transit_days": 4,
    "bottle_life_days": 90, "mt_qc_min_remaining_days": 60,
    "normal_passion_road_days": 3,
}
KINDS = {"order", "lot", "material_lot", "inbound", "route", "signal", "freight_quote",
         "production", "capacity", "shipment", "sku_master", "depot_master", "channel_master"}
ROUTE_STATES = {"OPEN", "DEGRADED", "SUSPECTED_CLOSED", "CONFIRMED_CLOSED", "UNKNOWN"}


def iso_day(value: str) -> date:
    if not isinstance(value, str):
        raise ValueError("date must be YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("date must be YYYY-MM-DD") from exc


def number(value, name: str, allow_zero: bool = True) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number")
    try:
        result = float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not math.isfinite(result) or result < 0 or (not allow_zero and result == 0):
        raise ValueError(f"{name} must be finite and nonnegative")
    return result


def whole(value, name: str) -> int:
    result = number(value, name)
    if not result.is_integer():
        raise ValueError(f"{name} must be a whole number")
    return int(result)


def truth(value, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
        return value.strip().lower() == "true"
    raise ValueError(f"{name} must be true or false")


def validate(kind: str, record: dict, catalog: dict | None = None) -> dict:
    """Reject unrecognized or nonsensical operational data before storage."""
    if kind not in KINDS or not isinstance(record, dict):
        raise ValueError("unknown record kind or invalid record")
    catalog = catalog or {"skus": SKUS, "depots": DEPOTS, "channels": CHANNELS}
    skus, depots, channels = catalog["skus"], catalog["depots"], catalog["channels"]
    r = dict(record)
    if not isinstance(r.get("id"), str) or not r["id"].strip() or len(r["id"]) > 120:
        raise ValueError("id must be a nonempty string of at most 120 characters")
    r["id"] = r["id"].strip()
    r["date"] = iso_day(r.get("date")).isoformat()
    if kind in {"order", "lot"}:
        if r.get("sku") not in skus or r.get("depot") not in depots:
            raise ValueError("unknown SKU or depot")
    if kind == "order":
        if r.get("channel") not in channels:
            raise ValueError("unknown channel")
        for field in ("requested", "fulfilled"):
            r[field] = whole(r.get(field), field)
        if r["fulfilled"] > r["requested"]:
            raise ValueError("fulfilled exceeds requested")
        r["in_stock"] = truth(r.get("in_stock", True), "in_stock")
    elif kind == "lot":
        r["quantity"] = whole(r.get("quantity"), "quantity")
        r["manufactured"] = iso_day(r.get("manufactured")).isoformat()
        r["expires"] = iso_day(r.get("expires")).isoformat()
        if not iso_day(r["manufactured"]) <= iso_day(r["date"]):
            raise ValueError("lot observation precedes manufacture")
        if (iso_day(r["expires"]) - iso_day(r["manufactured"])).days > CASE["bottle_life_days"]:
            raise ValueError("bottled lot exceeds 90-day shelf life")
        r["hold"] = truth(r.get("hold", False), "hold")
    elif kind == "material_lot":
        if r.get("material") not in {m for s in skus.values() for m in s["recipe"]}:
            raise ValueError("unknown material")
        r["quantity_kg"] = number(r.get("quantity_kg"), "quantity_kg")
        r["expires"] = iso_day(r.get("expires")).isoformat()
    elif kind == "inbound":
        if r.get("material") not in {m for s in skus.values() for m in s["recipe"]}:
            raise ValueError("unknown material")
        r["quantity_kg"] = number(r.get("quantity_kg"), "quantity_kg")
        r["eta"] = iso_day(r.get("eta")).isoformat()
        if r.get("status") not in {"PLANNED", "CONFIRMED", "RECEIVED", "CANCELLED"}:
            raise ValueError("invalid inbound status")
        if r.get("mode") not in {"ROAD", "AIR", "SEA"}:
            raise ValueError("invalid transport mode")
    elif kind == "route":
        if r.get("corridor") != "PASSION_COOPERATIVE":
            raise ValueError("unknown corridor")
        if r.get("status") not in ROUTE_STATES:
            raise ValueError("invalid route status")
        r["confirmed"] = truth(r.get("confirmed", False), "confirmed")
        if r["status"] == "CONFIRMED_CLOSED" and not r["confirmed"]:
            raise ValueError("confirmed closure requires confirmation")
    elif kind == "signal":
        if r.get("sku") not in skus or r.get("source") not in {"YOUTUBE", "SEARCH", "WEATHER", "CAMPAIGN"}:
            raise ValueError("unknown SKU or signal source")
        r["value"] = number(r.get("value"), "value")
        r["baseline"] = number(r.get("baseline"), "baseline", allow_zero=False)
    elif kind == "freight_quote":
        if r.get("material") not in {m for s in skus.values() for m in s["recipe"]}:
            raise ValueError("unknown material")
        r["max_kg"] = number(r.get("max_kg"), "max_kg")
        r["incremental_cost_rupees"] = number(r.get("incremental_cost_rupees"), "incremental_cost_rupees")
        r["lead_days"] = whole(r.get("lead_days"), "lead_days")
        r["valid_until"] = iso_day(r.get("valid_until")).isoformat()
        r["cold_chain_confirmed"] = truth(r.get("cold_chain_confirmed", False), "cold_chain_confirmed")
    elif kind == "capacity":
        if r.get("facility") not in {"PLANT_1", "PLANT_2", "COPACKER"}:
            raise ValueError("unknown facility")
        r["capacity_bottles"] = whole(r.get("capacity_bottles"), "capacity_bottles")
        if r.get("status") not in {"AVAILABLE", "REDUCED", "DOWN"}:
            raise ValueError("invalid capacity status")
    elif kind == "production":
        if r.get("sku") not in skus or r.get("facility") not in {"PLANT_1", "PLANT_2", "COPACKER"}:
            raise ValueError("unknown SKU or facility")
        if r.get("depot") not in depots:
            raise ValueError("production needs assigned depot")
        r["bottles"] = whole(r.get("bottles"), "bottles")
        r["production_on"] = iso_day(r.get("production_on")).isoformat()
        r["eta_depot"] = iso_day(r.get("eta_depot")).isoformat()
        if not iso_day(r["date"]) <= iso_day(r["production_on"]) <= iso_day(r["eta_depot"]):
            raise ValueError("depot arrival precedes production")
        if r.get("status") not in {"PLANNED", "COMMITTED", "COMPLETED", "CANCELLED"}:
            raise ValueError("invalid production status")
    elif kind == "shipment":
        if r.get("sku") not in skus or r.get("to_depot") not in depots:
            raise ValueError("unknown SKU or receiving depot")
        if r.get("from_depot") not in depots and r.get("from_depot") != "PLANT":
            raise ValueError("unknown origin")
        r["bottles"] = whole(r.get("bottles"), "bottles")
        r["eta"] = iso_day(r.get("eta")).isoformat()
        r["expires"] = iso_day(r.get("expires")).isoformat()
        if iso_day(r["eta"]) < iso_day(r["date"]) or iso_day(r["expires"]) < iso_day(r["date"]):
            raise ValueError("shipment dates inconsistent")
        if r.get("status") not in {"PLANNED", "IN_TRANSIT", "RECEIVED", "CANCELLED"}:
            raise ValueError("invalid shipment status")
    elif kind == "sku_master":
        r["mix"] = number(r.get("mix"), "mix")
        if r["mix"] > 1 or not isinstance(r.get("recipe"), dict) or not r["recipe"]:
            raise ValueError("SKU needs mix 0..1 and nonempty recipe in kg/bottle")
        r["recipe"] = {str(m): number(kg, f"recipe {m}", allow_zero=False)
                       for m, kg in r["recipe"].items() if str(m).strip()}
        if not r["recipe"]:
            raise ValueError("recipe must contain materials")
    elif kind == "depot_master":
        if not isinstance(r.get("city"), str) or not r["city"].strip() or not isinstance(r.get("region"), str):
            raise ValueError("depot needs city and region")
        r["share"] = number(r.get("share"), "share")
        if r["share"] > 1:
            raise ValueError("depot share exceeds one")
    elif kind == "channel_master":
        r["share"] = number(r.get("share"), "share")
        r["min_remaining_days"] = whole(r.get("min_remaining_days"), "min_remaining_days")
        if r["share"] > 1 or r["min_remaining_days"] > CASE["bottle_life_days"]:
            raise ValueError("invalid channel share or freshness rule")
    return r


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()[:16]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def local_today() -> date:
    # India Standard Time has no daylight-saving transition.
    return datetime.now(timezone(timedelta(hours=5, minutes=30))).date()


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS records (
                kind TEXT NOT NULL, id TEXT NOT NULL, source TEXT NOT NULL,
                event_date TEXT NOT NULL, received_at TEXT NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY(kind, id)
            );
            CREATE INDEX IF NOT EXISTS records_kind_date ON records(kind,event_date);
            CREATE TABLE IF NOT EXISTS record_versions (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, id TEXT NOT NULL,
                source TEXT NOT NULL, received_at TEXT NOT NULL, payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS decisions (
                action_id TEXT NOT NULL, version TEXT NOT NULL, status TEXT NOT NULL,
                actor TEXT NOT NULL, role TEXT NOT NULL, reason TEXT NOT NULL,
                recorded_at TEXT NOT NULL, PRIMARY KEY(action_id,version)
            );
            CREATE TABLE IF NOT EXISTS audit (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL,
                event TEXT NOT NULL, detail TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS external_observations (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL,
                source TEXT NOT NULL, payload TEXT NOT NULL
            );
        """)
        self.db.commit()

    def close(self):
        self.db.close()

    def catalog(self, as_of: date | None = None) -> dict:
        skus = {name: {"mix": value["mix"], "recipe": dict(value["recipe"])}
                for name, value in SKUS.items()}
        depots = dict(DEPOTS)
        channels = dict(CHANNELS)
        limits = {"GT": 0, "MT": 60, "QC": 60}
        for r in self.records("sku_master", as_of):
            skus[r["id"]] = {"mix": r["mix"], "recipe": r["recipe"]}
        for r in self.records("depot_master", as_of):
            depots[r["id"]] = (r["city"], r["region"], r["share"])
        for r in self.records("channel_master", as_of):
            channels[r["id"]] = r["share"]
            limits[r["id"]] = r["min_remaining_days"]
        return {"skus": skus, "depots": depots, "channels": channels, "min_remaining": limits}

    def ingest(self, kind: str, records: list[dict], source="manual", dry_run=False) -> dict:
        if not isinstance(records, list) or len(records) > 10_000:
            raise ValueError("records must be a list of at most 10,000 items")
        if not isinstance(source, str) or not source or len(source) > 120:
            raise ValueError("invalid source")
        catalog = self.catalog(local_today())
        clean = [validate(kind, r, catalog) for r in records]
        if len({r["id"] for r in clean}) != len(clean):
            raise ValueError("duplicate IDs within upload")
        if kind in {"sku_master", "depot_master", "channel_master"}:
            shares = ({k: v["mix"] for k, v in catalog["skus"].items()} if kind == "sku_master" else
                      {k: v[2] for k, v in catalog["depots"].items()} if kind == "depot_master" else
                      dict(catalog["channels"]))
            for r in clean:
                shares[r["id"]] = r["mix"] if kind == "sku_master" else r["share"]
            if abs(sum(shares.values())-1) > 1e-6:
                raise ValueError(f"{kind} shares must total 1.0 after this batch; got {sum(shares.values()):.6f}")
        if dry_run:
            changes = 0
            for r in clean:
                old = self.db.execute("SELECT payload FROM records WHERE kind=? AND id=?", (kind, r["id"])).fetchone()
                changes += not old or old[0] != json.dumps(r, sort_keys=True)
            return {"received": len(clean), "would_change": changes, "preview": clean[:5], "valid": True}
        changed = 0
        with self.db:
            for r in clean:
                payload = json.dumps(r, sort_keys=True)
                old = self.db.execute("SELECT payload FROM records WHERE kind=? AND id=?", (kind, r["id"])).fetchone()
                if old and old[0] == payload:
                    continue
                self.db.execute("INSERT INTO records VALUES (?,?,?,?,?,?) ON CONFLICT(kind,id) DO UPDATE SET source=excluded.source,event_date=excluded.event_date,received_at=excluded.received_at,payload=excluded.payload",
                                (kind, r["id"], source, r["date"], utc_now(), payload))
                self.db.execute("INSERT INTO record_versions(kind,id,source,received_at,payload) VALUES (?,?,?,?,?)",
                                (kind, r["id"], source, utc_now(), payload))
                changed += 1
            self.db.execute("INSERT INTO audit(at,event,detail) VALUES (?,?,?)",
                            (utc_now(), "INGEST", json.dumps({"kind": kind, "source": source, "received": len(clean), "changed": changed})))
        return {"received": len(clean), "changed": changed}

    def records(self, kind: str, as_of: date | None = None) -> list[dict]:
        if kind not in KINDS:
            raise ValueError("unknown record kind")
        if as_of:
            rows = self.db.execute("SELECT payload FROM records WHERE kind=? AND event_date<=?", (kind, as_of.isoformat())).fetchall()
        else:
            rows = self.db.execute("SELECT payload FROM records WHERE kind=?", (kind,)).fetchall()
        return [json.loads(x[0]) for x in rows]

    def decisions(self) -> dict[tuple[str, str], dict]:
        return {(r["action_id"], r["version"]): dict(r) for r in self.db.execute("SELECT * FROM decisions")}

    def decide(self, action: dict, status: str, actor: str, role: str, reason: str) -> dict:
        if status not in {"APPROVED", "REJECTED"}:
            raise ValueError("status must be APPROVED or REJECTED")
        if not actor.strip() or not reason.strip() or role != action["owner_role"]:
            raise ValueError("named actor, matching owner role, and reason required")
        if action["status"] != "PENDING":
            raise ValueError("decision is already recorded")
        row = {"action_id": action["id"], "version": action["version"], "status": status,
               "actor": actor.strip(), "role": role, "reason": reason.strip(), "recorded_at": utc_now()}
        with self.db:
            self.db.execute("INSERT INTO decisions VALUES (?,?,?,?,?,?,?)", tuple(row.values()))
            self.db.execute("INSERT INTO audit(at,event,detail) VALUES (?,?,?)",
                            (row["recorded_at"], "DECISION", json.dumps(row)))
        return row

    def audit(self, limit=100):
        return [dict(r) for r in self.db.execute("SELECT * FROM audit ORDER BY seq DESC LIMIT ?", (limit,))]

    def record_external(self, source: str, payload: dict):
        if source not in {"road", "attention"}:
            raise ValueError("unknown external source")
        payload = dict(payload)
        if source == "attention" and payload.get("state") == "OBSERVED":
            prior = self.external_history("attention", 2)
            if len(prior) == 2 and all(x.get("state") == "OBSERVED" for x in prior):
                def views(x):
                    return {v["id"]: v["views"] for v in x.get("videos", [])}
                current, recent, earlier = views(payload), views(prior[0]), views(prior[1])
                common = set(current) & set(recent) & set(earlier)
                new_growth = sum(max(0, current[k]-recent[k]) for k in common)
                old_growth = sum(max(0, recent[k]-earlier[k]) for k in common)
                if old_growth >= 100 and new_growth >= 100:
                    now = datetime.fromisoformat(utc_now())
                    recent_at = datetime.fromisoformat(prior[0]["observed_at"])
                    earlier_at = datetime.fromisoformat(prior[1]["observed_at"])
                    new_seconds = max(1, (now-recent_at).total_seconds())
                    old_seconds = max(1, (recent_at-earlier_at).total_seconds())
                    payload["view_growth_ratio"] = round((new_growth/new_seconds)/(old_growth/old_seconds), 2)
                    payload["compared_video_count"] = len(common)
        with self.db:
            self.db.execute("INSERT INTO external_observations(at,source,payload) VALUES (?,?,?)",
                            (utc_now(), source, json.dumps(payload)))
            self.db.execute("INSERT INTO audit(at,event,detail) VALUES (?,?,?)",
                            (utc_now(), "EXTERNAL_POLL", json.dumps({"source": source, "state": payload.get("state")})))
        return payload

    def external_history(self, source: str, limit=3) -> list[dict]:
        return [{**json.loads(r[0]), "observed_at": r[1]} for r in self.db.execute(
            "SELECT payload,at FROM external_observations WHERE source=? ORDER BY seq DESC LIMIT ?", (source, limit))]

    def external_latest(self) -> dict:
        result = {}
        for r in self.db.execute("SELECT source,payload,at FROM external_observations ORDER BY seq DESC"):
            if r["source"] not in result:
                result[r["source"]] = {**json.loads(r["payload"]), "observed_at": r["at"]}
        return result

    def process_mining_summary(self, limit=500) -> dict:
        try:
            import pandas as pd
            import pm4py
        except Exception as exc:  # pragma: no cover - depends on optional library
            return {"status": "unavailable", "error": str(exc)}

        rows = self.db.execute(
            "SELECT at, event, detail FROM audit ORDER BY seq ASC LIMIT ?",
            (limit,),
        ).fetchall()
        if not rows:
            return {"status": "empty", "event_count": 0, "activity_count": 0, "case_count": 0,
                    "activities": [], "start_activities": [], "end_activities": [], "dfg": []}

        def event_label(event: str, detail: dict) -> str:
            if event == "INGEST":
                kind = str(detail.get("kind", "INGEST")).upper()
                return f"INGEST_{kind}"
            if event == "DECISION":
                status = str(detail.get("status", "DECISION")).upper()
                return f"DECISION_{status}"
            if event == "EXTERNAL_POLL":
                source = str(detail.get("source", "EXTERNAL")).upper()
                return f"EXTERNAL_{source}"
            return event

        events = []
        for row in rows:
            detail = json.loads(row["detail"]) if row["detail"] else {}
            case_name = "case"
            if row["event"] == "DECISION":
                action_id = detail.get("action_id") or detail.get("version") or "decision"
                case_name = f"decision:{action_id}"
            elif row["event"] == "INGEST":
                kind = detail.get("kind") or "ingest"
                case_name = f"ingest:{kind}"
            elif row["event"] == "EXTERNAL_POLL":
                source = detail.get("source") or "external"
                case_name = f"external:{source}"
            events.append({
                "case:concept:name": case_name,
                "time:timestamp": row["at"],
                "concept:name": event_label(row["event"], detail),
            })

        frame = pd.DataFrame(events)
        frame["time:timestamp"] = pd.to_datetime(frame["time:timestamp"], errors="coerce")
        frame = frame.dropna(subset=["time:timestamp"]).copy()
        if frame.empty:
            return {"status": "empty", "event_count": 0, "activity_count": 0, "case_count": 0,
                    "activities": [], "start_activities": [], "end_activities": [], "dfg": []}

        dfg, start_activities, end_activities = pm4py.discover_dfg(
            frame,
            activity_key="concept:name",
            timestamp_key="time:timestamp",
            case_id_key="case:concept:name",
        )
        ordered_edges = [
            {"from": src, "to": dst, "count": count}
            for (src, dst), count in sorted(dfg.items(), key=lambda item: (-item[1], item[0][0], item[0][1]))
        ]
        return {
            "status": "ok",
            "event_count": int(len(frame)),
            "case_count": int(frame["case:concept:name"].nunique()),
            "activity_count": int(frame["concept:name"].nunique()),
            "activities": sorted(frame["concept:name"].unique().tolist()),
            "start_activities": sorted(start_activities.items(), key=lambda item: (-item[1], item[0])),
            "end_activities": sorted(end_activities.items(), key=lambda item: (-item[1], item[0])),
            "dfg": ordered_edges[:25],
        }


def baseline_daily(sku: str, depot: str, channel: str, catalog: dict | None = None) -> float:
    catalog = catalog or {"skus": SKUS, "depots": DEPOTS, "channels": CHANNELS}
    return (CASE["summer_bottles"] / CASE["model_summer_days"]
            * catalog["skus"][sku]["mix"] * catalog["depots"][depot][2] * catalog["channels"][channel])


def latest_route(records: list[dict]) -> dict:
    if not records:
        return {"status": "UNKNOWN", "confirmed": False, "source": "none", "date": None}
    return max(records, key=lambda r: (r["date"], r["id"]))


def make_action(kind: str, target: str, title: str, owner_role: str,
                why: str, numbers: dict, checks: list[str], priority: int) -> dict:
    action_id = f"{kind}-{digest([kind, target])[:10]}"
    version = digest([kind, target, title, owner_role, why, numbers, checks])
    return {"id": action_id, "version": version, "kind": kind, "target": target,
            "title": title, "owner_role": owner_role, "why": why,
            "numbers": numbers, "checks": checks, "priority": priority,
            "status": "PENDING"}


def plan(store: Store, as_of: date | None = None, use_model=True) -> dict:
    as_of = as_of or local_today()
    catalog = store.catalog(as_of)
    skus, depots, channels = catalog["skus"], catalog["depots"], catalog["channels"]
    max_buyer_life = max(catalog["min_remaining"].values())
    all_orders = [r for r in store.records("order", as_of) if (as_of - iso_day(r["date"])).days <= 21]
    from engine.forecast import aggregate_orders, dashboard_forecast
    orders = defaultdict(dict, aggregate_orders(all_orders))
    signals = [r for r in store.records("signal", as_of) if (as_of - iso_day(r["date"])).days <= 3]
    signal_by_sku = defaultdict(list)
    for r in signals:
        signal_by_sku[r["sku"]].append(r)

    demand_rows, spikes = [], []
    daily_by_sku_depot = defaultdict(float)
    for sku in skus:
        for depot in depots:
            for channel in channels:
                key = (sku, depot, channel)
                history = orders[key]
                older = []
                for days_ago in range(3, 15):
                    day = (as_of - timedelta(days=days_ago)).isoformat()
                    if day in history and history[day]["in_stock"]:
                        older.append(history[day]["requested"])
                base = statistics.median(older) if len(older) >= 5 else baseline_daily(*key, catalog=catalog)
                recent = [history.get((as_of - timedelta(days=d)).isoformat()) for d in (1, 0)]
                fresh = all(x is not None for x in recent)
                if fresh and all(x["requested"] >= 1.5 * max(base, 1) for x in recent):
                    forecast = max(base, statistics.mean(x["requested"] for x in recent))
                    spikes.append({"sku": sku, "depot": depot, "channel": channel,
                                   "ratio": round(forecast / max(base, 1), 2), "extra_per_day": round(forecast-base)})
                    reason = "two observed order days above 1.5x baseline"
                else:
                    forecast = base
                    reason = "recent validated order baseline" if older else "case-mix sample baseline"
                daily_by_sku_depot[(sku, depot)] += forecast
                demand_rows.append({"sku": sku, "depot": depot, "channel": channel,
                                    "baseline": round(base), "forecast_per_day": round(forecast),
                                    "data_days": len(older) + sum(x is not None for x in recent),
                                    "reason": reason, "signal_watch": bool(signal_by_sku[sku])})

    prediction = dashboard_forecast(all_orders, as_of, demand_rows, enabled=use_model)
    daily_by_sku_depot.clear()
    for row, model_result in zip(demand_rows, prediction["series"]):
        row["forecast_per_day"] = round(model_result["daily"])
        row["forecast_source"] = model_result["source"]
        daily_by_sku_depot[(row["sku"], row["depot"])] += model_result["daily"]

    all_lots = store.records("lot", as_of)
    expired_lots = [r for r in all_lots if r["quantity"] > 0 and iso_day(r["expires"]) < as_of]
    lots = [r for r in all_lots if iso_day(r["expires"]) >= as_of and not r["hold"]]
    reported_positions = defaultdict(list)
    for r in all_lots:
        reported_positions[(r["sku"], r["depot"])].append(r)
    pipeline = defaultdict(int)
    for r in store.records("production", as_of):
        if r["status"] == "COMMITTED" and as_of < iso_day(r["eta_depot"]) <= as_of+timedelta(days=18):
            pipeline[(r["sku"], r["depot"])] += r["bottles"]
    for r in store.records("shipment", as_of):
        if r["status"] == "IN_TRANSIT" and as_of < iso_day(r["eta"]) <= as_of+timedelta(days=18):
            eligibility_factor = 1 if iso_day(r["expires"]) >= iso_day(r["eta"])+timedelta(days=max_buyer_life) else channels.get("GT", 0)
            if iso_day(r["expires"]) >= iso_day(r["eta"]):
                pipeline[(r["sku"], r["to_depot"])] += round(r["bottles"]*eligibility_factor)
    by_position = defaultdict(list)
    for r in lots:
        by_position[(r["sku"], r["depot"])].append(r)
    positions, at_risk = [], []
    unknown_positions = 0
    for sku in skus:
        for depot in depots:
            group = by_position[(sku, depot)]
            reports = reported_positions[(sku, depot)]
            report_date = max((r["date"] for r in reports), default=None)
            stale = bool(report_date and (as_of-iso_day(report_date)).days > 1)
            qty = sum(r["quantity"] for r in group) if reports and not stale else None
            daily = daily_by_sku_depot[(sku, depot)]
            days_cover = qty / daily if daily and qty is not None else None
            arrival = as_of + timedelta(days=CASE["transfer_transit_days"])
            eligible = sum(r["quantity"] for r in group if iso_day(r["expires"]) >= arrival + timedelta(days=max_buyer_life)) if qty is not None else None
            gt_only = sum(r["quantity"] for r in group if arrival+timedelta(days=7) <= iso_day(r["expires"]) < arrival+timedelta(days=max_buyer_life)) if qty is not None else None
            freshness_risk = max(0, round(qty - daily * 21)) if qty is not None and eligible < qty else 0
            flag = "UNKNOWN" if not reports else "STALE" if stale else "CRITICAL" if days_cover is not None and days_cover < 14 else "OK"
            row = {"sku": sku, "depot": depot, "city": depots[depot][0],
                   "quantity": qty, "daily_demand": round(daily),
                   "cover_days": round(days_cover, 1) if days_cover is not None else None,
                   "stock_report_date": report_date,
                   "mt_qc_eligible_on_transfer_arrival": eligible,
                   "gt_only_on_transfer_arrival": gt_only,
                   "committed_inbound_next_18d": pipeline[(sku, depot)],
                   "age_watch_bottles_proxy": freshness_risk,
                   "service_flag": flag}
            positions.append(row)
            if row["service_flag"] == "CRITICAL":
                at_risk.append(row)
            if flag in {"UNKNOWN", "STALE"}:
                unknown_positions += 1

    actions = []
    if expired_lots:
        actions.append(make_action("EXPIRED_STOCK", "ALL", "Quarantine expired finished stock", "Inventory Planner",
            "Physical batches remain recorded after their 90-day selling life; they are excluded from usable stock.",
            {"batches": len(expired_lots), "bottles": sum(r["quantity"] for r in expired_lots)},
            ["Confirm warehouse counts", "Block all channel allocation and record approved disposal"], 1))
    if unknown_positions:
        actions.append(make_action("STOCK_DATA", "DEPOTS", "Refresh unknown or stale depot stock", "Inventory Planner",
            "Some depot/flavor positions lack a current batch report; they are not assumed to contain zero stock.",
            {"positions_needing_report": unknown_positions},
            ["Import current warehouse batch snapshots", "Do not dispatch proposed transfers from stale donors"], 1))
    by_spike = defaultdict(list)
    for x in spikes:
        by_spike[x["sku"]].append(x)
    for sku, group in by_spike.items():
        extra = sum(x["extra_per_day"] for x in group)
        actions.append(make_action("DEMAND", sku, f"Confirm {sku} demand shift", "Demand Planner",
            f"{len(group)} depot/channel series crossed the two-day order rule; public attention is corroboration only.",
            {"extra_orders_per_day": extra, "affected_series": len(group)},
            ["Check duplicate orders, campaigns, and stockout-censored fulfillment", "Approve forecast change before replanning"], 1))

    # Transfer only eligible stock.  Donor is protected for 10 days after
    # four days of transit; recipient aims at 14 days after arrival.
    transit = CASE["transfer_transit_days"]
    for sku in skus:
        group = [p for p in positions if p["sku"] == sku]
        donors = sorted([p for p in group if p["quantity"] is not None],
                        key=lambda p: (p["cover_days"] or 0), reverse=True)
        sinks = sorted([p for p in group if p["cover_days"] is not None and p["cover_days"] < 14],
                       key=lambda p: p["cover_days"])
        donor_left = {p["depot"]: max(0, math.floor(p["mt_qc_eligible_on_transfer_arrival"]
                      - p["daily_demand"] * (transit + 10))) for p in donors}
        shipped_from = defaultdict(int)
        remaining_by_sink = {}
        for sink in sinks:
            need = max(0, math.ceil(sink["daily_demand"] * (transit + 14) - sink["quantity"]
                                    - sink["committed_inbound_next_18d"]))
            for donor in donors:
                if donor["depot"] == sink["depot"] or need < 1000:
                    continue
                qty = int(min(need, donor_left[donor["depot"]]) // 1000 * 1000)
                if qty < 1000:
                    continue
                donor_left[donor["depot"]] -= qty
                shipped_from[donor["depot"]] += qty
                need -= qty
                actions.append(make_action("TRANSFER", f"{sku}:{donor['depot']}:{sink['depot']}",
                    f"Transfer {qty:,} {sku} bottles: {donor['city']} → {sink['city']}", "Distribution Manager",
                    "Same-flavor eligible batch can arrive in four days while protecting donor service.",
                    {"bottles": qty, "cost_rupees": round(qty*CASE["transfer_rupees_per_bottle"]),
                     "arrival_date": arrival.isoformat(), "remaining_receiver_target_gap": need},
                    ["Confirm exact batch and receipt age", "Confirm carrier and lane time",
                     "Recheck donor stock and reservations before dispatch"], 2))
            remaining_by_sink[sink["depot"]] = need
        # Batches too old for MT/QC may still fulfill confirmed GT demand
        # before expiry. Do not treat absent GT outlet data as consumer sales.
        for donor in donors:
            old_lots = [r for r in by_position[(sku, donor["depot"])]
                        if arrival+timedelta(days=7) <= iso_day(r["expires"]) < arrival+timedelta(days=max_buyer_life)]
            if not old_lots:
                continue
            oldest_expiry = min(iso_day(r["expires"]) for r in old_lots)
            window = min(10, (oldest_expiry-arrival).days)
            safe = max(0, donor["quantity"]-donor["daily_demand"]*(transit+10)
                       - shipped_from[donor["depot"]])
            left = int(min(donor["gt_only_on_transfer_arrival"], safe)//1000*1000)
            for sink in sinks:
                if left < 1000 or sink["depot"] == donor["depot"]:
                    continue
                gt_daily = sum(r["forecast_per_day"] for r in demand_rows
                               if r["sku"] == sku and r["depot"] == sink["depot"] and r["channel"] == "GT")
                need = remaining_by_sink.get(sink["depot"], 0)
                qty = int(min(left, need*channels.get("GT", 0), gt_daily*window)//1000*1000)
                if qty < 1000:
                    continue
                left -= qty
                remaining_by_sink[sink["depot"]] -= qty
                actions.append(make_action("GT_TRANSFER", f"{sku}:{donor['depot']}:{sink['depot']}",
                    f"Route {qty:,} aging {sku} bottles to verified GT demand", "Distribution Manager",
                    "Batch cannot meet the MT/QC 60-day receipt rule but can reach a GT customer with at least seven days of life.",
                    {"bottles": qty, "cost_rupees": round(qty*CASE["transfer_rupees_per_bottle"]),
                     "arrival_date": arrival.isoformat(), "oldest_batch_expires": oldest_expiry.isoformat()},
                    ["Confirm distributor order and buyer acceptance", "Allocate only listed eligible GT batches",
                     "Recheck donor balance and delivery date before dispatch"], 2))
    age_rows = [p for p in positions if p["age_watch_bottles_proxy"] > 0]
    if age_rows:
        actions.append(make_action("AGE", "ALL", "Review aging stock and slow-mover replenishment", "Inventory Planner",
            "Projected volume may cross the MT/QC acceptance window; this is a screening proxy, not observed write-off.",
            {"positions": len(age_rows), "proxy_bottles": sum(p["age_watch_bottles_proxy"] for p in age_rows)},
            ["Inspect actual batch ages and recipient demand", "Do not transfer across flavors"], 3))

    daily_total = sum(daily_by_sku_depot.values())
    capacity = CASE["plant_bottles_per_28_days"] / 28
    capacity_rows = [r for r in store.records("capacity", as_of) if r["date"] == as_of.isoformat()
                     and r["facility"] != "COPACKER"]
    if capacity_rows:
        observed_capacity = sum(r["capacity_bottles"] for r in capacity_rows if r["status"] != "DOWN")
        capacity = min(capacity, observed_capacity)
        if len({r["facility"] for r in capacity_rows}) < 2:
            actions.append(make_action("CAPACITY_DATA", "PLANTS", "Complete both plant availability reports", "Plant Planner",
                "Only one plant has a current capacity report; remaining available capacity is treated as zero.",
                {"reported_plants": len({r["facility"] for r in capacity_rows})},
                ["Import the second plant's capacity before committing new output"], 1))
    capacity_gap = max(0, round(daily_total-capacity))
    if capacity_gap:
        actions.append(make_action("CAPACITY", "PLANTS", "Resolve projected production capacity gap", "COO",
            "Projected demand exceeds fixed in-house daily capacity.",
            {"gap_bottles_per_day": capacity_gap, "copacker_max_per_day": round(capacity*.1),
             "earliest_copacker_date": (as_of+timedelta(days=14)).isoformat()},
            ["Validate ingredient availability", "Review SKU mix and contribution",
             "Obtain COO/Finance approval for co-packer premium"], 1))

    all_material_lots = store.records("material_lot", as_of)
    material_lots = [r for r in all_material_lots if iso_day(r["expires"]) >= as_of]
    route = dict(latest_route(store.records("route", as_of)))
    if route.get("date") and (as_of-iso_day(route["date"])).days > 1:
        route["reported_status"] = route["status"]
        route["status"] = "UNKNOWN"
        route["stale"] = True
    road_status = route["status"]
    inbound = [r for r in store.records("inbound", as_of)
               if r["status"] == "CONFIRMED" and as_of < iso_day(r["eta"]) <= as_of+timedelta(days=14)
               and not (r["material"] == "passionfruit" and r["mode"] == "ROAD"
                        and road_status == "CONFIRMED_CLOSED")]
    required_kg = defaultdict(float)
    for (sku, _depot), units in daily_by_sku_depot.items():
        for material, kg in skus[sku]["recipe"].items():
            required_kg[material] += units*kg
    material_rows = []
    for material in sorted(required_kg):
        reports = [r for r in all_material_lots if r["material"] == material]
        report_day = max((iso_day(r["date"]) for r in reports), default=None)
        stock = (sum(r["quantity_kg"] for r in material_lots if r["material"] == material)
                 if report_day and (as_of-report_day).days <= 1 else None)
        incoming = sum(r["quantity_kg"] for r in inbound if r["material"] == material)
        cover = stock/required_kg[material] if stock is not None and required_kg[material] else None
        material_rows.append({"material": material, "stock_kg": round(stock) if stock is not None else None,
                              "confirmed_inbound_next_14d_kg": round(incoming),
                              "projected_14d_balance_kg": round(stock+incoming-14*required_kg[material]) if stock is not None else None,
                              "forecast_kg_per_day": round(required_kg[material]),
                              "cover_days": round(cover, 1) if cover is not None else None})
    passion = next((m for m in material_rows if m["material"] == "passionfruit"), None)
    missing_materials = [m["material"] for m in material_rows if m["stock_kg"] is None]
    if missing_materials:
        actions.append(make_action("DATA_GAP", "MATERIAL", "Validate missing ingredient inventory", "Procurement Manager",
            "Required ingredients have no recorded stock or confirmed receipt; production feasibility cannot be verified.",
            {"missing_materials": ", ".join(missing_materials)},
            ["Import raw-material batches and open purchase orders", "Do not authorize additional production from an unknown supply position"], 1))
    external = store.external_latest()
    def fresh_external(source):
        stamp = external.get(source, {}).get("observed_at")
        return bool(stamp and abs((datetime.now(timezone.utc)-datetime.fromisoformat(stamp)).total_seconds()) <= 6*3600)
    attention_ratio = external.get("attention", {}).get("view_growth_ratio") if fresh_external("attention") else None
    if attention_ratio is not None and attention_ratio >= 1.5:
        actions.append(make_action("ATTENTION_WATCH", "DRAGON_PASSION", "Verify rising product attention against orders", "Demand Planner",
            "Tracked campaign-video view growth accelerated; this is a watch signal, not a bottle forecast.",
            {"view_growth_ratio": attention_ratio,
             "tracked_videos": external["attention"].get("compared_video_count", 0)},
            ["Confirm product relevance and geography", "Check QC orders and stock availability before changing forecast"], 2))
    if fresh_external("road") and external.get("road", {}).get("state") == "WATCH" and road_status != "CONFIRMED_CLOSED":
        actions.append(make_action("ROAD_WATCH", "PASSION_COOPERATIVE", "Investigate reported road closure", "Logistics Manager",
            "A map provider reported a closure inside the configured corridor box; route intersection and transporter confirmation are outstanding.",
            {"incidents_in_box": external["road"]["closure_incidents_in_bbox"],
             "observation_time": external["road"]["observed_at"]},
            ["Confirm the incident lies on the approved road", "Obtain transporter or authority confirmation"], 1))
    if passion and passion["cover_days"] is not None and passion["cover_days"] < 24:
        actions.append(make_action("SUPPLY", "PASSION", "Validate passionfruit disruption cover", "Procurement Manager",
            "Single cooperative and sole road; a 21-day closure plus ordinary three-day receipt lead requires 24 days in this stress case.",
            {"current_cover_days": passion["cover_days"], "stress_target_days": 24,
             "material_shortfall_kg_at_24d": max(0, round(24*required_kg["passionfruit"]-passion["stock_kg"]))},
            ["Check six-month pulp life, cold storage, and funding", "Confirm supplier quantities and realistic lead times"], 1))
    if road_status in {"SUSPECTED_CLOSED", "CONFIRMED_CLOSED", "DEGRADED"}:
        actions.append(make_action("ROAD", "PASSION_COOPERATIVE", "Verify cooperative road disruption", "Logistics Manager",
            f"Latest corridor report is {road_status}; no approved alternate road exists in the case.",
            {"route_status": road_status, "observed_date": route["date"]},
            ["Confirm with supplier/transport authority", "Recheck incoming pulp and plant cover"], 1))
    if route.get("stale"):
        actions.append(make_action("ROUTE_STALE", "PASSION_COOPERATIVE", "Refresh cooperative corridor status", "Logistics Manager",
            "The last route report is more than one day old; current access is unknown.",
            {"last_reported_status": route["reported_status"], "report_date": route["date"]},
            ["Confirm current road state before accepting inbound ETA or emergency freight choice"], 1))
    if road_status == "CONFIRMED_CLOSED" and passion and passion["cover_days"] is not None and passion["cover_days"] < 24:
        quotes = [q for q in store.records("freight_quote", as_of)
                  if q["material"] == "passionfruit" and iso_day(q["valid_until"]) >= as_of
                  and q["cold_chain_confirmed"]]
        if quotes:
            quote = min(quotes, key=lambda q: q["incremental_cost_rupees"] / max(q["max_kg"], 1))
            actions.append(make_action("AIR_REVIEW", "PASSION", "Review targeted air-freight option", "COO",
                "Confirmed closure and insufficient stress cover; quote exists but production/service economics still need validation.",
                {"quoted_max_kg": quote["max_kg"], "incremental_cost_rupees": quote["incremental_cost_rupees"],
                 "lead_days": quote["lead_days"], "quote_id": quote["id"]},
                ["Confirm cargo origin access and cold chain", "Check production capacity and SKU allocation",
                 "Confirm price with Finance before commitment"], 1))
        else:
            actions.append(make_action("QUOTE", "PASSION", "Request validated cold-chain air quote", "Logistics Manager",
                "No current confirmed quote; the system cannot price or dispatch air freight.",
                {"material_shortfall_kg_at_24d": max(0, round(24*required_kg["passionfruit"]-passion["stock_kg"]))},
                ["Confirm pickup access, cargo space, cold chain, arrival time and binding price"], 1))

    decisions = store.decisions()
    for a in actions:
        saved = decisions.get((a["id"], a["version"]))
        if saved:
            a["status"] = saved["status"]
            a["decision"] = {"actor": saved["actor"], "role": saved["role"],
                             "reason": saved["reason"], "recorded_at": saved["recorded_at"]}
    actions.sort(key=lambda a: (a["priority"], a["kind"], a["id"]))
    freshest_order = max((r["date"] for r in all_orders), default=None)
    quality = {"latest_order_date": freshest_order,
               "order_feed_stale": not freshest_order or (as_of-iso_day(freshest_order)).days > 1,
               "public_signals_count": len(signals), "route_observation_date": route.get("date"),
               "unknown_or_stale_stock_positions": unknown_positions,
               "record_counts": {k: len(store.records(k, as_of)) for k in KINDS}}
    return {"as_of": as_of.isoformat(), "mode": "NO OPERATIONAL FEEDS" if not all_orders else "SYNTHETIC DEMO" if any(r.get("sample") for r in all_orders) else "INGESTED DATA",
            "case": CASE, "quality": quality, "route": route,
            "metrics": {"daily_demand_bottles": round(daily_total), "daily_plant_capacity_bottles": round(capacity),
                        "capacity_gap_bottles_per_day": capacity_gap, "critical_positions": len(at_risk),
                        "age_watch_positions": len(age_rows), "pending_actions": sum(a["status"] == "PENDING" for a in actions)},
            "signals": signals, "external": external, "demand": demand_rows, "forecast": prediction, "positions": positions,
            "materials": material_rows, "actions": actions,
            "notes": ["Recipes, depot shares, daily records, batch ages, and costs in the seeded demo are synthetic.",
                      "Case summer volume and monthly capacity are rounded; 112/28-day periods are modeling assumptions.",
                      "Public attention is a watch signal; bottle forecasts are based on validated orders.",
                      "Road observations require confirmation and do not create an approved alternative route.",
                      "Approvals are recorded; no purchase, dispatch, or air cargo is executed by this application."]}


def demo_records(as_of: date, viral=True, closure=True) -> dict[str, list[dict]]:
    """Deterministic, case-constrained example input records for a complete run."""
    records = {kind: [] for kind in KINDS}
    for sku, entry in SKUS.items():
        records["sku_master"].append({"id": sku, "date": as_of.isoformat(),
                                      "mix": entry["mix"], "recipe": entry["recipe"], "sample": True})
    for depot, (city, region, share) in DEPOTS.items():
        records["depot_master"].append({"id": depot, "date": as_of.isoformat(),
                                        "city": city, "region": region, "share": share, "sample": True})
    for channel, share in CHANNELS.items():
        records["channel_master"].append({"id": channel, "date": as_of.isoformat(),
            "share": share, "min_remaining_days": 0 if channel == "GT" else 60, "sample": True})
    hot = {"D1", "D3", "D4", "D6"}
    hot_share = sum(DEPOTS[d][2] for d in hot)
    quiet_qc = (4 - hot_share*5)/(1-hot_share)
    fast = {"D1", "D3", "D6"}
    slow = {"D8", "D9"}
    fast_share = sum(DEPOTS[d][2] for d in fast)
    slow_share = sum(DEPOTS[d][2] for d in slow)
    other_factor = (1-fast_share*1.30-slow_share*.65)/(1-fast_share-slow_share)
    for sku in SKUS:
        for depot in DEPOTS:
            base_total = sum(baseline_daily(sku, depot, ch) for ch in CHANNELS)
            old_age = 27 if sku in {"Mango Peach Basil", "Guava Chilli"} and depot in slow else 7
            records["lot"].append({"id": f"demo-lot:{sku}:{depot}", "date": as_of.isoformat(),
                "sku": sku, "depot": depot, "quantity": round(base_total*21),
                "manufactured": (as_of-timedelta(days=old_age)).isoformat(),
                "expires": (as_of+timedelta(days=90-old_age)).isoformat(), "sample": True})
            for channel in CHANNELS:
                base = baseline_daily(sku, depot, channel)
                for age in range(13, -1, -1):
                    day = as_of - timedelta(days=age)
                    multiplier = (5 if depot in hot else quiet_qc) if sku == "Dragon Passion" and channel == "QC" and viral and age <= 1 else 1
                    if sku in {"Mango Peach Basil", "Guava Chilli"}:
                        multiplier = 1.30 if depot in fast else (.65 if depot in slow else other_factor)
                    requested = round(base*multiplier)
                    fulfilled = requested
                    records["order"].append({"id": f"demo-order:{day}:{sku}:{depot}:{channel}",
                        "date": day.isoformat(), "sku": sku, "depot": depot, "channel": channel,
                        "requested": requested, "fulfilled": fulfilled, "in_stock": True, "sample": True})
    material_daily = defaultdict(float)
    for sku in SKUS:
        for depot in DEPOTS:
            for channel in CHANNELS:
                for material, kg in SKUS[sku]["recipe"].items():
                    material_daily[material] += baseline_daily(sku, depot, channel)*kg
    for material, daily in material_daily.items():
        qty = daily * (14 if material == "passionfruit" else 42 if material == "dragonfruit" else 30)
        records["material_lot"].append({"id": f"demo-material:{material}", "date": as_of.isoformat(),
            "material": material, "quantity_kg": round(qty),
            "expires": (as_of+timedelta(days=150)).isoformat(), "sample": True})
    records["route"].append({"id": "demo-route", "date": as_of.isoformat(),
        "corridor": "PASSION_COOPERATIVE", "status": "CONFIRMED_CLOSED" if closure else "OPEN",
        "confirmed": bool(closure), "source_note": "synthetic transporter confirmation" if closure else "synthetic open report",
        "sample": True})
    for facility in ("PLANT_1", "PLANT_2"):
        records["capacity"].append({"id": f"demo-capacity:{facility}:{as_of}", "date": as_of.isoformat(),
            "facility": facility, "capacity_bottles": round(CASE["plant_bottles_per_28_days"]/56),
            "status": "AVAILABLE", "sample": True})
    records["production"].append({"id": "demo-committed:dragon-passion:d1", "date": as_of.isoformat(),
        "sku": "Dragon Passion", "facility": "PLANT_1", "depot": "D1", "bottles": 10000,
        "production_on": (as_of+timedelta(days=1)).isoformat(),
        "eta_depot": (as_of+timedelta(days=3)).isoformat(), "status": "COMMITTED", "sample": True})
    records["shipment"].append({"id": "demo-in-transit:guava:d1", "date": as_of.isoformat(),
        "sku": "Guava Chilli", "from_depot": "PLANT", "to_depot": "D1", "bottles": 5000,
        "eta": (as_of+timedelta(days=2)).isoformat(),
        "expires": (as_of+timedelta(days=70)).isoformat(), "status": "IN_TRANSIT", "sample": True})
    records["inbound"].append({"id": "demo-road-pulp-inbound", "date": as_of.isoformat(),
        "material": "passionfruit", "quantity_kg": 5000,
        "eta": (as_of+timedelta(days=3)).isoformat(), "status": "CONFIRMED",
        "mode": "ROAD", "sample": True})
    if closure:
        records["freight_quote"].append({"id": "demo-illustrative-air-quote", "date": as_of.isoformat(),
            "material": "passionfruit", "max_kg": 5000, "incremental_cost_rupees": 400000,
            "lead_days": 2, "valid_until": (as_of+timedelta(days=1)).isoformat(),
            "cold_chain_confirmed": True, "sample": True})
    if viral:
        records["signal"].append({"id": "demo-attention", "date": as_of.isoformat(),
            "sku": "Dragon Passion", "source": "CAMPAIGN", "value": 4, "baseline": 1, "sample": True})
    return records


def seed_demo(store: Store, as_of: date | None = None) -> dict:
    as_of = as_of or local_today()
    existing_orders = store.records("order")
    if existing_orders and not all(r.get("sample") for r in existing_orders):
        raise ValueError("database contains non-demo orders; demo seed is disabled")
    result = {}
    for kind, rows in demo_records(as_of).items():
        existing_ids = {r["id"] for r in store.records(kind)}
        missing = [r for r in rows if r["id"] not in existing_ids]
        if missing:
            result[kind] = store.ingest(kind, missing, "synthetic-case-demo")
    return result
