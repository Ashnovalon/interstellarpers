"""Causal daily replay using the operational planner on selected decision days.

Both policies receive identical synthetic demand and disruption events.  The
proposed policy assumes the named approvers accept eligible recommendations
immediately in this counterfactual; the real app never auto-approves.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from .operations import CASE, CHANNELS, DEPOTS, SKUS, Store, baseline_daily, plan


START = date(2026, 3, 1)
VIRAL_START, VIRAL_END = 15, 29
CLOSURE_START, CLOSURE_END, RECEIPT_RESUMES = 64, 85, 88
HORIZON = 98
HOT = {"D1", "D3", "D4", "D6"}
HOT_SHARE = sum(DEPOTS[d][2] for d in HOT)
QUIET_QC = (4-HOT_SHARE*5)/(1-HOT_SHARE)
FAST, SLOW = {"D1", "D3", "D6"}, {"D8", "D9"}
FAST_SHARE = sum(DEPOTS[d][2] for d in FAST)
SLOW_SHARE = sum(DEPOTS[d][2] for d in SLOW)
OTHER_FACTOR = (1-FAST_SHARE*1.30-SLOW_SHARE*.65)/(1-FAST_SHARE-SLOW_SHARE)


def demand_for(day: int, sku: str, depot: str, channel: str) -> int:
    multiplier = 1
    if sku == "Dragon Passion" and channel == "QC" and VIRAL_START <= day < VIRAL_END:
        multiplier = 5 if depot in HOT else QUIET_QC
    if sku in {"Mango Peach Basil", "Guava Chilli"}:
        multiplier = 1.30 if depot in FAST else (.65 if depot in SLOW else OTHER_FACTOR)
    return round(baseline_daily(sku, depot, channel)*multiplier)


def daily_passion_baseline() -> float:
    return sum(baseline_daily(s, d, c)*SKUS[s]["recipe"].get("passionfruit", 0)
               for s in SKUS for d in DEPOTS for c in CHANNELS)


def take_stock(lots: list[dict], qty: int, day: date, channel: str, receipt: date | None = None,
               min_remaining_days: int | None = None) -> tuple[int, list[dict]]:
    """Remove oldest eligible bottles, preserving manufacture/expiry on moves."""
    required_life = min_remaining_days if min_remaining_days is not None else (60 if channel in {"MT", "QC"} else 0)
    cutoff = (receipt or day) + timedelta(days=required_life)
    moved = []
    remaining = qty
    for lot in sorted(lots, key=lambda x: x["expires"]):
        if lot["quantity"] <= 0 or lot["expires"] < cutoff:
            continue
        n = min(remaining, lot["quantity"])
        if n:
            lot["quantity"] -= n
            moved.append({**lot, "quantity": n})
            remaining -= n
        if remaining == 0:
            break
    return qty-remaining, moved


def run_policy(proposed: bool) -> dict:
    db = Store(":memory:")
    stock = defaultdict(list)
    for sku in SKUS:
        for depot in DEPOTS:
            base = sum(baseline_daily(sku, depot, c) for c in CHANNELS)
            old_age = 60 if sku in {"Mango Peach Basil", "Guava Chilli"} and depot in SLOW else 7
            stock[(sku, depot)].append({"id": f"opening:{sku}:{depot}", "quantity": round(base*21),
                "manufactured": START-timedelta(days=old_age),
                "expires": START+timedelta(days=90-old_age)})
    scheduled = defaultdict(list)
    daily_raw = daily_passion_baseline()
    target_raw_days = 24 if proposed else 14
    raw_kg = daily_raw*target_raw_days
    requested_total = fulfilled_total = written_off = 0
    freight_cost_rupees = transfer_cost_rupees = 0
    max_passion_gap = 0
    alerts = []
    transfers_dispatched = 0
    action_days = {0, VIRAL_START+1, CLOSURE_START, CLOSURE_START+14, RECEIPT_RESUMES}
    recorded_viral = False
    records_count = 0
    for index in range(HORIZON):
        today = START+timedelta(days=index)
        for shipment in scheduled.pop(index, []):
            stock[(shipment["sku"], shipment["depot"])].append(shipment)
        # This explicit approximation represents previously booked routine
        # three-day inbound deliveries. They stop for closure plus restart lead.
        if index < CLOSURE_START or index >= RECEIPT_RESUMES:
            raw_kg = min(daily_raw*target_raw_days, raw_kg+daily_raw)
        # Remove bottle batches on their actual expiry day.
        for lots in stock.values():
            for lot in lots:
                if lot["expires"] < today and lot["quantity"]:
                    written_off += lot["quantity"]
                    lot["quantity"] = 0
        day_orders = []
        for sku in SKUS:
            for depot in DEPOTS:
                for channel in CHANNELS:
                    asked = demand_for(index, sku, depot, channel)
                    supplied, _ = take_stock(stock[(sku, depot)], asked, today, channel)
                    requested_total += asked
                    fulfilled_total += supplied
                    day_orders.append({"id": f"{today}:{sku}:{depot}:{channel}", "date": today.isoformat(),
                        "sku": sku, "depot": depot, "channel": channel,
                        "requested": asked, "fulfilled": supplied, "in_stock": supplied == asked,
                        "sample": True})
        db.ingest("order", day_orders, "synthetic-replay")
        records_count += len(day_orders)
        if CLOSURE_START <= index < CLOSURE_END:
            db.ingest("route", [{"id": "corridor", "date": today.isoformat(),
                "corridor": "PASSION_COOPERATIVE", "status": "CONFIRMED_CLOSED",
                "confirmed": True, "sample": True}], "synthetic-replay")
        if index == RECEIPT_RESUMES:
            db.ingest("route", [{"id": "corridor", "date": today.isoformat(),
                "corridor": "PASSION_COOPERATIVE", "status": "OPEN", "confirmed": True,
                "sample": True}], "synthetic-replay")
        if index in action_days or (proposed and VIRAL_START+1 <= index < VIRAL_END):
            lot_rows = []
            for (sku, depot), lots in stock.items():
                for lot in lots:
                    if lot["expires"] >= today:
                        lot_rows.append({"id": lot["id"], "date": today.isoformat(),
                            "sku": sku, "depot": depot, "quantity": lot["quantity"],
                            "manufactured": lot["manufactured"].isoformat(),
                            "expires": lot["expires"].isoformat(), "sample": True})
            db.ingest("lot", lot_rows, "synthetic-replay")
            db.ingest("material_lot", [{"id": "passion-pulp", "date": today.isoformat(),
                "material": "passionfruit", "quantity_kg": round(raw_kg),
                "expires": (today+timedelta(days=150)).isoformat(), "sample": True}], "synthetic-replay")
            snapshot = plan(db, today, use_model=False)
            if index == VIRAL_START+1:
                recorded_viral = any(a["kind"] == "DEMAND" and a["target"] == "Dragon Passion"
                                     for a in snapshot["actions"])
            if index in action_days:
                alerts.append({"date": today.isoformat(), "day": index, "trigger": "preseason risk" if index == 0 else
                               "viral day 2" if index == VIRAL_START+1 else
                               "closure reported" if index == CLOSURE_START else
                               "closure week 3" if index == CLOSURE_START+14 else "road receipts resume",
                               "critical_positions": snapshot["metrics"]["critical_positions"],
                               "passion_cover_days": next((m["cover_days"] for m in snapshot["materials"]
                                                          if m["material"] == "passionfruit"), None),
                               "transfer_candidates": len([a for a in snapshot["actions"] if a["kind"] == "TRANSFER"]),
                               "recommendations": [a["title"] for a in snapshot["actions"][:5]]})
            if proposed and VIRAL_START+1 <= index < VIRAL_END:
                for a in snapshot["actions"]:
                    if a["kind"] not in {"TRANSFER", "GT_TRANSFER"}:
                        continue
                    sku, donor, receiver = a["target"].split(":")
                    qty = a["numbers"]["bottles"]
                    arrival_day = index+CASE["transfer_transit_days"]
                    moved, batches = take_stock(stock[(sku, donor)], qty, today, "QC" if a["kind"] == "TRANSFER" else "GT",
                                                today+timedelta(days=CASE["transfer_transit_days"]),
                                                60 if a["kind"] == "TRANSFER" else 7)
                    if moved == 0:
                        continue
                    for b in batches:
                        scheduled[arrival_day].append({**b, "id": f"transfer:{a['id']}:{b['id']}", "sku": sku, "depot": receiver})
                    transfer_cost_rupees += round(moved*CASE["transfer_rupees_per_bottle"])
                    transfers_dispatched += moved
        # Production is finite and constrained by raw passionfruit. Baseline
        # allocation persists; the proposed policy redirects spare capacity
        # after the two-day observation, then sends it to hot depots.
        capacity_left = CASE["plant_bottles_per_28_days"]/28
        for sku in SKUS:
            for depot in DEPOTS:
                base = sum(baseline_daily(sku, depot, c) for c in CHANNELS)
                wanted = base
                if proposed and sku == "Dragon Passion" and VIRAL_START+1 <= index < VIRAL_END and depot in HOT:
                    wanted += baseline_daily(sku, depot, "QC")*4
                make = min(wanted, capacity_left)
                passion_per = SKUS[sku]["recipe"].get("passionfruit", 0)
                if passion_per:
                    make = min(make, raw_kg/passion_per)
                units = int(max(0, make))
                capacity_left -= units
                raw_kg -= units*passion_per
                if units:
                    scheduled[index+2].append({"id": f"production:{index}:{sku}:{depot}",
                        "sku": sku, "depot": depot, "quantity": units,
                        "manufactured": today, "expires": today+timedelta(days=90)})
        if CLOSURE_START <= index < RECEIPT_RESUMES:
            gap = max(0, target_raw_days-raw_kg/max(daily_raw, 1))
            max_passion_gap = max(max_passion_gap, round(gap, 1))
    db.close()
    return {"policy": "approved_proposals" if proposed else "last_summer_planning",
            "period": {"start": START.isoformat(), "days": HORIZON},
            "requested_bottles": requested_total, "fulfilled_bottles": fulfilled_total,
            "unfulfilled_bottles": requested_total-fulfilled_total,
            "service_pct": round(fulfilled_total/requested_total*100, 2),
            "writeoff_bottles": written_off, "transfer_bottles": transfers_dispatched,
            "transfer_cost_rupees": transfer_cost_rupees,
            "max_passion_cover_gap_days_proxy": max_passion_gap,
            "viral_alert_on_second_day": recorded_viral,
            "freight_cost_rupees": freight_cost_rupees, "records_processed": records_count,
            "milestones": alerts}


def replay() -> dict:
    old = run_policy(False)
    new = run_policy(True)
    return {"data_type": "SYNTHETIC CASE-CONSTRAINED COUNTERFACTUAL",
            "last_summer_planning": old, "approved_proposals": new,
            "difference": {"additional_fulfilled_bottles": new["fulfilled_bottles"]-old["fulfilled_bottles"],
                           "avoided_writeoff_bottles": old["writeoff_bottles"]-new["writeoff_bottles"],
                           "added_transfer_cost_rupees": new["transfer_cost_rupees"]-old["transfer_cost_rupees"]},
            "assumptions": ["All daily depot/channel orders, recipes, batch ages, routing and production travel times are synthetic.",
                            "This policy replay uses observed-order rules, not the separately backtested forecasting model, preventing future-trained model leakage.",
                            "Viral QC orders run for 14 days starting day 15; the road closes on day 64 for 21 days plus three-day normal receipt lead.",
                            "The proposed case assumes a funded 24-day pre-season pulp buffer and same-day human approvals.",
                            "Routine inbound deliveries are represented by daily booked receipts outside the closure; no alternate road is used.",
                            "No historical company transactions were supplied; simulated improvement is not a forecast or measured saving."]}
