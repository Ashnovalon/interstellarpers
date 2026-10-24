"""Persistent, accelerated operating simulation with human-controlled interventions.

All quantities are synthetic. One wall-clock tick advances a configurable fraction
of a business day. Operational records and the historical demo remain isolated.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import random
import sqlite3
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .forecast import features, load_model, model_card, predict_tree_model
from .operations import CASE, CHANNELS, DEPOTS, SKUS, baseline_daily, digest, local_today

PRICE = CASE["price_rupees"]
UNIT_CONTRIBUTION = PRICE * CASE["contribution_margin"]
ASSUMED_UNIT_COST = PRICE - UNIT_CONTRIBUTION
PLANT_CAPACITY = CASE["plant_bottles_per_28_days"] / 28
MATERIALS = sorted({m for s in SKUS.values() for m in s["recipe"]})
FAST_DEPOTS={"D1","D3","D6"}
SLOW_DEPOTS={"D8","D9"}
FAST_SHARE=sum(DEPOTS[d][2] for d in FAST_DEPOTS)
SLOW_SHARE=sum(DEPOTS[d][2] for d in SLOW_DEPOTS)
OTHER_SPATIAL_FACTOR=(1-1.30*FAST_SHARE-.65*SLOW_SHARE)/(1-FAST_SHARE-SLOW_SHARE)
DEFAULT_INPUTS = {"trend": 1.0, "conversion": .75, "target_sku": "Dragon Passion",
    "region": "ALL", "road_closed": False, "closure_days": 21,
    "traffic_delay_days": 0.0, "plant_availability": 1.0,
    "import_delay_days": 0.0, "heatwave": 1.0, "competitor_pressure": 0.0,
    "feed_outage": False, "quality_result": "PASS"}
PRESETS = {
    "viral": {"label": "Influencer goes viral", "changes": {"trend": 5.0, "conversion": .75}},
    "rumor": {"label": "Attention without conversion", "changes": {"trend": 5.0, "conversion": 0.0}},
    "closure": {"label": "Sole supplier road closes", "changes": {"road_closed": True, "closure_days": 21}},
    "outage": {"label": "Plant loses 35% capacity", "changes": {"plant_availability": .65}},
    "traffic": {"label": "Transfer traffic adds 2 days", "changes": {"traffic_delay_days": 2.0}},
    "imports": {"label": "Imported dragonfruit delayed", "changes": {"import_delay_days": 14.0}},
    "heatwave": {"label": "Heatwave lifts demand", "changes": {"heatwave": 1.25}},
    "feed": {"label": "Order and warehouse feeds stop", "changes": {"feed_outage": True}},
    "competitor": {"label": "Competitor takes 25% of blend demand", "changes": {"competitor_pressure": .25}},
    "quality": {"label": "Passionfruit batch quarantined", "changes": {}},
}


def key(sku, depot, channel=None):
    return "|".join((sku, depot, channel)) if channel else "|".join((sku, depot))


def noise(seed, tick, series):
    value = int(hashlib.sha256(f"{seed}:{tick}:{series}".encode()).hexdigest()[:12], 16)
    return .96 + .08 * value / (16**12 - 1)


def rates_at(state):
    """Hidden simulator demand. Forecast code never receives conversion or this function."""
    return {row["series"]:row["daily_rate"] for row in generate_inputs(state)}


def smooth_regime(seed, day, series, span, amplitude):
    """Seeded correlated variation survives aggregation without favoring upward growth."""
    segment=math.floor(day/span)
    phase=(day/span)-segment
    left=(noise(seed,segment,series)-1)/.04
    right=(noise(seed,segment+1,series)-1)/.04
    return 1+amplitude*((1-phase)*left+phase*right)


def generate_inputs(state, at_day=None):
    result = []
    inputs = state["inputs"]
    day=state["day"] if at_day is None else at_day
    macro=smooth_regime(state["seed"],day,"network",3,.12)
    for sku in SKUS:
        for depot, (_city, region, _share) in DEPOTS.items():
            for channel in CHANNELS:
                spatial=1.0
                if sku in {"Mango Peach Basil", "Guava Chilli"}:
                    spatial=1.30 if depot in FAST_DEPOTS else .65 if depot in SLOW_DEPOTS else OTHER_SPATIAL_FACTOR
                relevant = inputs["region"] == "ALL" or inputs["region"] == region
                attention=1.0
                if sku == inputs["target_sku"] and relevant and channel == "QC":
                    age = max(0, day-state["trend_changed_day"])
                    attention=1+(inputs["trend"]-1)*inputs["conversion"]*(1-math.exp(-age/.5))
                competition=1-inputs["competitor_pressure"] if sku=="Dragon Passion" else 1.0
                calendar=1+.018*math.sin(2*math.pi*day/7+list(CHANNELS).index(channel))
                regional=smooth_regime(state["seed"],day,"region:"+region,4,.12)
                product=smooth_regime(state["seed"],day,"sku:"+sku,6,.08)
                k = key(sku,depot,channel)
                local=noise(state["seed"],state["tick"],k)
                factors={"spatial":spatial,"attention":attention,"weather":inputs["heatwave"],
                    "competition":competition,"calendar":calendar,"network_regime":macro,
                    "regional_regime":regional,"product_regime":product,"local_noise":local}
                base=baseline_daily(sku,depot,channel)
                daily=base*math.prod(factors.values())
                result.append({"series":k,"sku":sku,"depot":depot,"city":DEPOTS[depot][0],"region":region,
                    "channel":channel,"baseline_daily":base,"daily_rate":daily,"factors":factors})
    return result


def raw_daily():
    return {m:sum(baseline_daily(s,d,c)*SKUS[s]["recipe"].get(m,0)
                  for s in SKUS for d in DEPOTS for c in CHANNELS) for m in MATERIALS}


def new_world():
    stock = {}
    for sku in SKUS:
        for depot in DEPOTS:
            units = round(sum(baseline_daily(sku,depot,c) for c in CHANNELS)*21)
            age = 26 if sku in {"Mango Peach Basil","Guava Chilli"} and depot in {"D8","D9"} else 7
            stock[key(sku,depot)] = [{"id":f"opening:{sku}:{depot}","qty":units,"made":-age,"expires":90-age,"hold":False}]
    daily = raw_daily()
    raw = {m:qty*(14 if m=="passionfruit" else 21 if m=="dragonfruit" else 30) for m,qty in daily.items()}
    return {"stock":stock,"raw":raw,"held_raw":0.0,"raw_receipts":[],"shipments":[],
        "commands":[],"allocation_until":-1,"allocation_weights":{},"copacker_start":-1,"copacker_end":-1,"capacity_factor":1.0,
        "metrics":{"requested":0,"fulfilled":0,"expired":0,"revenue":0.0,"transfer_cost":0.0,
                   "air_cost":0.0,"copacker_cost":0.0,"quality_cost":0.0,"writeoff_cost":0.0,"holding_cost":0.0,"repair_cost":0.0,
                   "produced":0,"initial_bottles":sum(x[0]["qty"] for x in stock.values()),
                   "raw_initial":dict(raw),"raw_received":{m:0.0 for m in MATERIALS},
                   "raw_consumed":{m:0.0 for m in MATERIALS},"raw_disposed":{m:0.0 for m in MATERIALS}},
        "last_orders":{},"last_fulfilled":{},"last_production":0,"last_unfulfilled":0}


def contribution(world):
    m = world["metrics"]
    return m["fulfilled"]*UNIT_CONTRIBUTION-sum(m[k] for k in
        ("transfer_cost","air_cost","copacker_cost","quality_cost","writeoff_cost","holding_cost","repair_cost"))


def stock_total(world, position, day, min_life=0):
    return sum(l["qty"] for l in world["stock"][position] if not l["hold"] and l["expires"] >= day+min_life)


def take(world, position, quantity, day, min_life=0):
    remaining = int(quantity)
    picked = []
    for lot in sorted(world["stock"][position], key=lambda x:x["expires"]):
        if lot["hold"] or lot["expires"] < day+min_life or lot["qty"] <= 0:
            continue
        qty = min(remaining, lot["qty"])
        if qty:
            lot["qty"] -= qty
            picked.append({**lot,"qty":qty})
            remaining -= qty
        if remaining <= 0:
            break
    return int(quantity)-remaining,picked


def add_lot(world, position, lot):
    current = next((x for x in world["stock"][position] if x["id"]==lot["id"]),None)
    if current:
        current["qty"] += lot["qty"]
    else:
        world["stock"][position].append(dict(lot))


def advance_world(world, day, dt, rates, inputs, forecast_rates=None):
    """Conserve stock and material mass for both human and no-intervention policies."""
    end = day+dt
    events = []
    for receipt in world["raw_receipts"]:
        if receipt["status"]!="IN_TRANSIT" or receipt["eta"]>end:
            continue
        blocked = receipt["material"]=="passionfruit" and receipt["mode"]=="ROAD" and inputs["road_closed"]
        if blocked:
            receipt["eta"] = end+3
            continue
        world["raw"][receipt["material"]] += receipt["kg"]
        world["metrics"]["raw_received"][receipt["material"]] += receipt["kg"]
        receipt["status"] = "RECEIVED"
        events.append(("RECEIPT",f"{receipt['kg']:,.0f} kg {receipt['material']} received"))
    for shipment in world["shipments"]:
        if shipment["status"]=="IN_TRANSIT" and shipment["eta"]<=end:
            for lot in shipment["lots"]:
                add_lot(world,key(shipment["sku"],shipment["to"]),lot)
            shipment["status"]="RECEIVED"
            events.append(("ARRIVAL",f"{shipment['quantity']:,} {shipment['sku']} bottles received in {DEPOTS[shipment['to']][0]}"))
    for command in world["commands"]:
        if command["status"]=="SCHEDULED" and command["eta"]<=end:
            command["status"]="COMPLETED"
            if command["kind"]=="REPAIR_PLANT":
                world["capacity_factor"]=1.0
                events.append(("PLANT_RESTORED","Maintenance restored installed plant capacity; no new summer line was added"))
            if command["kind"]=="LAB_TEST":
                if command["result"]=="PASS":
                    command["status"]="PASSED"
                    events.append(("LAB_PASS","Lab passed the quarantined pulp; QA release approval is now required"))
                else:
                    command["status"]="FAILED"
                    qty=world["held_raw"]
                    world["held_raw"]=0
                    world["metrics"]["raw_disposed"]["passionfruit"]+=qty
                    world["metrics"]["writeoff_cost"]+=qty*180
                    events.append(("LAB_FAIL",f"Quarantined pulp failed; {qty:,.0f} kg disposed at assumed ₹180/kg"))
    # Contracted routine receipts represent pre-existing procurement, not new recommendations.
    if math.floor(end)>math.floor(day):
        daily=raw_daily()
        for m,kg in daily.items():
            if m=="dragonfruit":
                portions=((.6,3,"ROAD"),(.4,42+inputs["import_delay_days"],"SEA"))
            else:
                portions=((1,3,"ROAD"),)
            for share,lead,mode in portions:
                world["raw_receipts"].append({"id":f"routine:{math.floor(end)}:{m}:{mode}","material":m,
                    "kg":kg*share,"eta":end+lead,"mode":mode,"status":"IN_TRANSIT"})
    for lots in world["stock"].values():
        for lot in lots:
            if lot["expires"]<end and lot["qty"]:
                world["metrics"]["expired"]+=lot["qty"]
                world["metrics"]["writeoff_cost"]+=lot["qty"]*ASSUMED_UNIT_COST
                lot["qty"]=0
    orders,served={},{}
    for sku in SKUS:
        for depot in DEPOTS:
            # Serve channels with strict receipt-age requirements before GT.
            for channel in ("MT","QC","GT"):
                k=key(sku,depot,channel)
                quantity=max(0,round(rates[k]*dt))
                done,_=take(world,key(sku,depot),quantity,end,60 if channel!="GT" else 0)
                orders[k]=quantity;served[k]=done
    m=world["metrics"]
    m["requested"]+=sum(orders.values());m["fulfilled"]+=sum(served.values())
    m["revenue"]+=sum(served.values())*PRICE
    world["last_orders"]=orders;world["last_fulfilled"]=served
    world["last_unfulfilled"]=sum(orders.values())-sum(served.values())
    # Approved plan allocates finite plant capacity by projected cover and demand.
    adaptive = world["allocation_until"]>=end and forecast_rates is not None
    targets={key(s,d):sum((forecast_rates if adaptive else rates_base())[key(s,d,c)] for c in CHANNELS)
             for s in SKUS for d in DEPOTS}
    plant=PLANT_CAPACITY*world.get("capacity_factor",inputs["plant_availability"])*dt
    copack=PLANT_CAPACITY*.1*dt if world["copacker_start"]<=end<=world["copacker_end"] and world["copacker_start"]>=0 else 0
    capacity=plant+copack
    # Proportional targets keep every product supplied; adaptive weights favor short cover.
    weights={p:(max(0.25, min(3,14/max(stock_total(world,p,end)/max(target,1),1))) if adaptive else 1)*target
             for p,target in targets.items()}
    if adaptive:
        if inputs["feed_outage"] and world.get("allocation_weights"):
            weights=dict(world["allocation_weights"])
        else:
            world["allocation_weights"]=dict(weights)
    total_weight=max(sum(weights.values()),1)
    produced=0
    for p,target in targets.items():
        sku,depot=p.split("|")
        units=min(target*dt*1.5 if adaptive else target*dt,capacity*weights[p]/total_weight)
        for material,kg in SKUS[sku]["recipe"].items():
            units=min(units,world["raw"][material]/kg)
        qty=max(0,int(units))
        for material,kg in SKUS[sku]["recipe"].items():
            consumed=qty*kg
            world["raw"][material]-=consumed;m["raw_consumed"][material]+=consumed
        produced+=qty
        if qty:
            lot={"id":f"production:{math.floor(end)}:{sku}:{depot}","qty":qty,"made":end,"expires":end+90,"hold":False}
            world["shipments"].append({"id":f"prod:{end}:{sku}:{depot}","sku":sku,"from":"PLANT","to":depot,
                "quantity":qty,"lots":[lot],"eta":end+2+inputs["traffic_delay_days"],"status":"IN_TRANSIT","type":"PRODUCTION"})
    m["produced"]+=produced
    # Copacker premium is charged only on the fraction actually manufactured there.
    copacked=min(copack,max(0,produced-plant))
    m["copacker_cost"]+=copacked*ASSUMED_UNIT_COST*.25
    m["holding_cost"]+=max(0,world["raw"]["passionfruit"]-raw_daily()["passionfruit"]*14)*.10*dt
    world["last_production"]=produced
    world["raw_receipts"]=[x for x in world["raw_receipts"] if x["status"]!="RECEIVED" or x["eta"]>end-2]
    world["shipments"]=[x for x in world["shipments"] if x["status"]!="RECEIVED" or x["eta"]>end-2]
    for p,lots in world["stock"].items():
        world["stock"][p]=[x for x in lots if x["qty"]>0]
    return events


_BASE_RATES = None
def rates_base():
    global _BASE_RATES
    if _BASE_RATES is None:
        _BASE_RATES={key(s,d,c):baseline_daily(s,d,c) for s in SKUS for d in DEPOTS for c in CHANNELS}
    return _BASE_RATES


class LiveEngine:
    def __init__(self, db_path=":memory:"):
        self.lock=threading.RLock()
        self.changed=threading.Condition(self.lock)
        self.stop=threading.Event()
        self.thread=None
        self.pending_events=[]
        self.db=sqlite3.connect(str(db_path),check_same_thread=False)
        self.db.row_factory=sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS live_runs(id TEXT PRIMARY KEY,updated_at TEXT NOT NULL,state TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS live_events(seq INTEGER PRIMARY KEY AUTOINCREMENT,run_id TEXT NOT NULL,
              business_day REAL NOT NULL,received_at TEXT NOT NULL,kind TEXT NOT NULL,payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS live_events_run ON live_events(run_id,seq);
        """)
        saved=self.db.execute("SELECT state FROM live_runs ORDER BY updated_at DESC,rowid DESC LIMIT 1").fetchone()
        self.state=json.loads(saved[0]) if saved else self._new_state(42,"guided")
        self.state["running"]=False
        self.state["review"]=None
        self.state.setdefault("scheduled_decisions",[])
        self.state.setdefault("latest_inputs",None)
        self.state.setdefault("last_input_change",None)
        self.state["generator_version"]="v2-correlated"
        for offer in self.state["offers"].values():
            if offer["status"]=="PENDING" and "review_until_tick" not in offer:
                offer["operational_deadline"]=offer["deadline"]
                offer["review_until_tick"]=self.state["tick"]+10
                offer["deadline"]=max(offer["deadline"],self.state["day"]+10*self.state["days_per_tick"])
        for world in (self.state["world"],self.state["baseline"]):
            world["metrics"].setdefault("repair_cost",0.0)
            world.setdefault("capacity_factor",self.state["inputs"]["plant_availability"])
        self._refresh_model()
        self._refresh_forecasts()
        self._refresh_offers()
        self._persist("RESUME_READY" if saved else "CREATED","Simulation ready; press Start to advance business time")

    def _new_state(self, seed, scenario):
        reference=max(local_today(),date(2026,10,24))
        start=date(reference.year if reference.month<3 else reference.year+1,3,1)
        state={"run_id":uuid.uuid4().hex[:12],"seed":seed,"scenario":scenario,"day":0.0,"tick":0,"event_seq":0,
            "revision":0,"start_date":start.isoformat(),"running":False,"days_per_tick":.25,
            "review":None,"scheduled_decisions":[],"latest_inputs":None,"last_input_change":None,"generator_version":"v2-correlated",
            "inputs":dict(DEFAULT_INPUTS),"trend_changed_day":0,"road_reopens":None,
            "world":new_world(),"baseline":new_world(),"history":{},"nowcast":{},
            "model_curves":{},"model_used":False,"forecast_rates":{},"bucket":{},"bucket_coverage":0.0,
            "last_feed_day":0.0,"reported_stock":{},"reported_day":0.0,
            "offers":{},"decisions":[],"events":[],"tape":[],"daily_scores":[],"model_daily_prediction":{},
            "budget":25000000,"rollout_reserved":12000000,"cash_buffer":0.0,"copacker_reserved":0.0,"copacker_baseline_cost":0.0,
            "scheduled_events":[{"day":1,"preset":"viral","done":False},
                {"day":6,"preset":"closure","done":False},
                {"day":12,"preset":"outage","done":False}] if scenario=="guided" else []}
        state["inputs"]["region"]="North"
        initial=rates_at(state)
        for k,rate in initial.items():
            state["history"][k]=[{"date":(start-timedelta(days=ago)).isoformat(),
                "requested":round(rate*(1+.03*math.sin(ago*2*math.pi/7)))} for ago in range(14,0,-1)]
            state["nowcast"][k]=rate
            state["bucket"][k]=0
        state["reported_stock"]=self._stock_observations(state["world"],0)
        return state

    def _stock_observations(self, world, day):
        return {p:{"quantity":stock_total(world,p,day),
                   "eligible":stock_total(world,p,day+4,60),
                   "gt_eligible":stock_total(world,p,day+4,7),
                   "oldest_expiry":min((x["expires"] for x in lots if x["qty"]>0),default=None)}
                for p,lots in world["stock"].items()}

    def _refresh_model(self):
        s=self.state
        if s["inputs"]["feed_outage"] and s["model_curves"]:
            s["model_used"]=0
            return
        model=load_model()
        today=date.fromisoformat(s["start_date"])+timedelta(days=math.floor(s["day"]))
        used=0
        for k,history in s["history"].items():
            lookup={r["date"]:r["requested"] for r in history}
            days=[(today-timedelta(days=d)).isoformat() for d in range(14,0,-1)]
            complete=all(d in lookup for d in days)
            values=[lookup[d] for d in days] if complete else [r["requested"] for r in history[-14:]]
            fallback=sum(values[-7:])/max(1,len(values[-7:]))
            eligible=bool(model and complete and model["card"]["status"]=="VALIDATED"
                and model["card"]["synthetic"] and today.isoformat()>=model["card"]["data_end"])
            curve=[]
            for horizon in range(1,15):
                if eligible:
                    x,scale=features(values,today+timedelta(days=horizon-1),horizon)
                    prediction=predict_tree_model(model,x)*scale
                else:
                    prediction=fallback
                curve.append(max(0,prediction))
            s["model_curves"][k]=curve
            used+=eligible
        s["model_used"]=used
        s["model_daily_prediction"]={sku:sum(v[0] for k,v in s["model_curves"].items() if k.startswith(sku+"|")) for sku in SKUS}

    def _refresh_forecasts(self):
        s=self.state
        for k,curve in s["model_curves"].items():
            s["forecast_rates"][k]=max(0,.35*curve[0]+.65*s["nowcast"][k])
        if s.get("forecast_origin_day")!=math.floor(s["day"]):
            s["forecast_origin_day"]=math.floor(s["day"])
            s["forecast_origin_fraction"]=s["day"]-math.floor(s["day"])
            s["adaptive_day_prediction"]={sku:sum(v for k,v in s["forecast_rates"].items() if k.startswith(sku+"|")) for sku in SKUS}

    def _event(self, kind, message, detail=None):
        s=self.state
        s["event_seq"]=s.get("event_seq",0)+1
        event={"seq":s["event_seq"],"day":round(s["day"],3),"kind":kind,"message":message,
               "detail":detail or {},"received_at":datetime.now(timezone.utc).isoformat(timespec="seconds")}
        visible=dict(event)
        if kind=="TICK":
            visible["detail"]={k:detail[k] for k in ("requested","fulfilled","production","feed_observed","dt") if detail and k in detail}
        s["events"].append(visible)
        s["events"]=s["events"][-100:]
        self.pending_events.append(event)
        return event

    def _persist(self, kind, message, detail=None):
        s=self.state
        event=self._event(kind,message,detail)
        s["revision"]+=1
        stamp=datetime.now(timezone.utc).isoformat(timespec="microseconds")
        with self.db:
            self.db.executemany("INSERT INTO live_events(run_id,business_day,received_at,kind,payload) VALUES (?,?,?,?,?)",
                [(s["run_id"],e["day"],e["received_at"],e["kind"],json.dumps(e,ensure_ascii=False)) for e in self.pending_events])
            self.db.execute("INSERT INTO live_runs VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at,state=excluded.state",
                (s["run_id"],stamp,json.dumps(s,ensure_ascii=False,separators=(",",":"))))
        self.pending_events=[]
        with self.changed:
            self.changed.notify_all()

    def start_worker(self):
        if self.thread:
            return
        def loop():
            due=time.monotonic()+1
            while not self.stop.wait(max(0,due-time.monotonic())):
                due+=1
                with self.lock:
                    if self.state["running"]:
                        try:
                            self._step()
                        except Exception as exc:
                            self.state["running"]=False
                            self._persist("ERROR",f"Simulation paused: {type(exc).__name__}: {exc}")
                if time.monotonic()-due>1:
                    due=time.monotonic()+1
        self.thread=threading.Thread(target=loop,name="live-simulation",daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        with self.lock:
            self.changed.notify_all()
        if self.thread:
            self.thread.join(timeout=3)
        with self.lock:
            self.db.close()

    def control(self, body):
        with self.lock:
            action=body.get("action")
            if self.state.get("review") and action not in {"reset","pause"}:
                raise ValueError("Finish or close the current review before advancing business time")
            if action=="reset":
                seed=body.get("seed",42)
                if isinstance(seed,bool) or not isinstance(seed,int) or not 0<=seed<=999999:
                    raise ValueError("Seed must be an integer from 0 to 999999")
                scenario=body.get("scenario","guided")
                if scenario not in {"guided","sandbox"}:
                    raise ValueError("Scenario must be guided or sandbox")
                self.state=self._new_state(seed,scenario)
                self._refresh_model();self._refresh_forecasts();self._refresh_offers()
            elif action in {"start","pause"}:
                if action=="start" and self.state["day"]>=112:
                    raise ValueError("The 112-day season is complete; create a new run")
                self.state["running"]=action=="start"
            elif action=="speed":
                value=body.get("days_per_tick")
                if isinstance(value,bool) or value not in {.125,.25,.5,1}:
                    raise ValueError("Speed must be 3, 6, 12 or 24 business hours per second")
                self.state["days_per_tick"]=value
            elif action=="step":
                if self.state["running"]:
                    raise ValueError("Pause before stepping manually")
                self._step()
                return self.snapshot()
            else:
                raise ValueError("Unknown control action")
            self._persist("CONTROL",f"User selected {action}")
            return self.snapshot()

    def _validate_inputs(self, body):
        permitted=set(DEFAULT_INPUTS)
        if set(body)-permitted:
            raise ValueError("Unknown input: "+", ".join(sorted(set(body)-permitted)))
        numeric={"trend":(1,6),"conversion":(0,1),"closure_days":(1,35),"traffic_delay_days":(0,7),
            "plant_availability":(0,1),"import_delay_days":(0,56),"heatwave":(.6,1.5),"competitor_pressure":(0,.6)}
        for k,(low,high) in numeric.items():
            if k in body and (isinstance(body[k],bool) or not isinstance(body[k],(int,float)) or not math.isfinite(body[k]) or not low<=body[k]<=high):
                raise ValueError(f"{k} must be between {low} and {high}")
        for k in ("road_closed","feed_outage"):
            if k in body and not isinstance(body[k],bool):
                raise ValueError(f"{k} must be true or false")
        if "target_sku" in body and body["target_sku"] not in SKUS:
            raise ValueError("Unknown target flavor")
        if "region" in body and body["region"] not in {"ALL","North","South","East","West"}:
            raise ValueError("Unknown region")
        if "quality_result" in body and body["quality_result"] not in {"PASS","FAIL"}:
            raise ValueError("Lab outcome must be PASS or FAIL")
        return dict(body)

    def inputs(self, body, step_if_paused=False):
        with self.lock:
            if self.state["day"]>=112:raise ValueError("This season is complete. Use New run to test another disruption")
            if self.state.get("review"):
                raise ValueError("Close the active decision review before changing scenario conditions")
            changes=self._validate_inputs(body)
            self._manual_override()
            before=dict(self.state["inputs"])
            self._apply_inputs(changes)
            self._input_change("INPUT","Scenario assumptions applied",before)
            self._refresh_offers()
            self._persist("INPUT","Scenario assumptions updated",changes)
            if step_if_paused and not self.state["running"]:
                self._step()
            return self.snapshot()

    def inject(self, name, step_if_paused=False):
        with self.lock:
            if self.state["day"]>=112:raise ValueError("This season is complete. Use New run to test another disruption")
            if self.state.get("review"):
                raise ValueError("Close the active decision review before injecting another disruption")
            if name not in PRESETS:
                raise ValueError("Unknown disruption preset")
            self._manual_override()
            self._inject(name)
            self._refresh_offers()
            self._persist("DISRUPTION",PRESETS[name]["label"])
            if step_if_paused and not self.state["running"]:
                self._step()
            return self.snapshot()

    def _inject(self, name):
        s=self.state
        before=dict(s["inputs"])
        self._apply_inputs(PRESETS[name]["changes"])
        if name=="outage":
            for world in (s["world"],s["baseline"]):
                world["capacity_factor"]=s["inputs"]["plant_availability"]
        if name=="quality":
            if s["world"]["held_raw"]>0:
                raise ValueError("A quarantined batch is already awaiting a decision")
            for w in (s["world"],s["baseline"]):
                qty=w["raw"]["passionfruit"]*.3
                w["raw"]["passionfruit"]-=qty;w["held_raw"]+=qty
        self._event("DISRUPTION",PRESETS[name]["label"])
        self._input_change("DISRUPTION",PRESETS[name]["label"],before)

    def _input_change(self, kind, message, before):
        s=self.state
        s["last_input_change"]={"kind":kind,"message":message,"day":s["day"],"tick":s["tick"],
            "changes":[{"field":k,"before":before[k],"after":v} for k,v in s["inputs"].items() if before[k]!=v],
            "applied_inputs":dict(s["inputs"]),"held_pulp_kg":round(s["world"]["held_raw"]),
            "effective_capacity":s["world"]["capacity_factor"]}

    def _manual_override(self):
        s=self.state
        if s["scenario"]=="guided":
            s["scenario"]="sandbox"
            for event in s["scheduled_events"]:
                if not event["done"]:
                    event["done"]=True;event["cancelled_by_operator"]=True
            self._event("MANUAL_OVERRIDE","Manual inputs took control; remaining guided shocks were cancelled")

    @staticmethod
    def _expired(s, offer):
        return s["day"]>=offer["deadline"] and s["tick"]>=offer.get("review_until_tick",0)

    @staticmethod
    def _effective_deadline(s, offer):
        return max(offer["deadline"],s["day"]+max(0,offer.get("review_until_tick",0)-s["tick"])*s["days_per_tick"])

    def begin_review(self, body):
        with self.lock:
            s=self.state
            if s["day"]>=112:
                raise ValueError("This season has finished. Use New run to start another live season")
            if s.get("review"):
                raise ValueError("A decision review is already open; complete or close it first")
            action=s["offers"].get(body.get("id"))
            if not action or action["status"]!="PENDING" or action["version"]!=body.get("version") or self._expired(s,action):
                raise ValueError("This offer changed; select its current version")
            token=uuid.uuid4().hex
            s["review"]={"id":action["id"],"version":action["version"],"token":token,"was_running":s["running"]}
            s["running"]=False
            self._persist("REVIEW_OPEN","Business clock paused while the operator reviews a decision",{"action_id":action["id"]})
            return {"state":self.snapshot(),"review_token":token}

    def end_review(self, body):
        with self.lock:
            review=self.state.get("review")
            if not review:
                return self.snapshot()
            if review["token"]!=body.get("review_token"):
                raise ValueError("This review is no longer active")
            self.state["review"]=None
            self.state["running"]=bool(review["was_running"] and self.state["day"]<112)
            self._persist("REVIEW_CLOSED","Review closed; previous clock state restored")
            return self.snapshot()

    def _apply_inputs(self, changes):
        s=self.state
        old=s["inputs"]
        restart_closure=changes.get("road_closed",old["road_closed"]) and (
            not old["road_closed"] or changes.get("closure_days",old["closure_days"])!=old["closure_days"])
        if any(k in changes and changes[k]!=old[k] for k in ("trend","target_sku","region","conversion")):
            s["trend_changed_day"]=s["day"]
        delay=max(0,changes.get("traffic_delay_days",old["traffic_delay_days"])-old["traffic_delay_days"])
        imports=max(0,changes.get("import_delay_days",old["import_delay_days"])-old["import_delay_days"])
        if delay or imports:
            for world in (s["world"],s["baseline"]):
                for shipment in world["shipments"]:
                    if shipment["status"]=="IN_TRANSIT":
                        shipment["eta"]+=delay
                for receipt in world["raw_receipts"]:
                    if receipt["material"]=="dragonfruit" and receipt["mode"]=="SEA" and receipt["status"]=="IN_TRANSIT":
                        receipt["eta"]+=imports
        if "plant_availability" in changes and changes["plant_availability"]!=old["plant_availability"]:
            for world in (s["world"],s["baseline"]):
                world["capacity_factor"]=changes["plant_availability"]
        s["inputs"].update(changes)
        if restart_closure:
            s["road_reopens"]=s["day"]+s["inputs"]["closure_days"]
        elif "road_closed" in changes and not changes["road_closed"]:
            s["road_reopens"]=None

    def _step(self):
        s=self.state
        if s.get("review"):
            raise ValueError("The clock is paused for a decision review")
        if s["day"]>=112:
            s["running"]=False
            return
        dt=min(s["days_per_tick"],112-s["day"],1-(s["day"]-math.floor(s["day"])))
        for event in s["scheduled_events"]:
            if not event["done"] and event["day"]<=s["day"]:
                self._inject(event["preset"]);event["done"]=True
        if s["road_reopens"] is not None and s["day"]>=s["road_reopens"]:
            s["inputs"]["road_closed"]=False;s["road_reopens"]=None
            self._event("ROAD_OPEN","Supplier road reopened; stranded road receipts still need their three-day transit")
        self._execute_due_decisions()
        generated=generate_inputs(s,s["day"]+dt/2)
        actual={r["series"]:r["daily_rate"] for r in generated}
        before_contribution=s["tape"][-1]["contribution"] if s["tape"] else 0
        events=advance_world(s["world"],s["day"],dt,actual,s["inputs"],s["forecast_rates"])
        advance_world(s["baseline"],s["day"],dt,actual,s["inputs"])
        old_day=s["day"]
        s["day"]=round(s["day"]+dt,5);s["tick"]+=1
        s["last_dt"]=dt
        fresh=not s["inputs"]["feed_outage"]
        incoming=[]
        for row in generated:
            series=row["series"]
            incoming.append({**row,"id":f"{s['run_id']}:{s['tick']}:{series}",
                "requested":s["world"]["last_orders"][series],"fulfilled":s["world"]["last_fulfilled"][series],
                "observed":fresh,"synthetic":True})
        s["latest_inputs"]={"tick":s["tick"],"day_start":old_day,"day_end":s["day"],"dt":dt,
            "requested":sum(s["world"]["last_orders"].values()),"fulfilled":sum(s["world"]["last_fulfilled"].values()),
            "observed":fresh,"generator_version":s["generator_version"],"parameters":dict(s["inputs"]),"rows":incoming}
        if fresh:
            alpha=1-math.exp(-dt/.65)
            for k,qty in s["world"]["last_orders"].items():
                s["nowcast"][k]=(1-alpha)*s["nowcast"][k]+alpha*qty/dt
                s["bucket"][k]+=qty
            s["bucket_coverage"]+=dt
            s["last_feed_day"]=s["day"]
            s["reported_stock"]=self._stock_observations(s["world"],s["day"])
            s["reported_day"]=s["day"]
        if math.floor(s["day"])>math.floor(old_day):
            if s["bucket_coverage"]>=.999:
                completed=(date.fromisoformat(s["start_date"])+timedelta(days=math.floor(old_day))).isoformat()
                for k,qty in s["bucket"].items():
                    s["history"][k].append({"date":completed,"requested":qty})
                    s["history"][k]=s["history"][k][-35:]
                for sku in SKUS:
                    real=sum(v for k,v in s["bucket"].items() if k.startswith(sku+"|"))
                    s["daily_scores"].append({"day":math.floor(old_day),"sku":sku,"actual":real,
                        "prediction":s["model_daily_prediction"][sku],"adaptive_prediction":s["adaptive_day_prediction"][sku]
                            if s.get("forecast_origin_fraction",0)<.001 else None})
                s["daily_scores"]=s["daily_scores"][-350:]
            s["bucket"]={k:0 for k in s["bucket"]};s["bucket_coverage"]=0
            self._refresh_model()
        self._refresh_forecasts()
        self._execute_due_decisions()
        for kind,message in events[:8]:
            self._event(kind,message)
        if len(events)>8:
            self._event("ARRIVALS",f"{len(events)-8} additional receipts completed this tick")
        self._sync_commands()
        self._refresh_offers()
        s["tape"].append({"day":s["day"],"tick":s["tick"],"forecast":sum(s["forecast_rates"].values()),
            "actual":sum(s["world"]["last_orders"].values())/dt if fresh else None,
            "fulfilled":sum(s["world"]["last_fulfilled"].values())/dt if fresh else None,
            "contribution":contribution(s["world"]),"baseline":contribution(s["baseline"]),
            "tick_revenue":sum(s["world"]["last_fulfilled"].values())*PRICE,
            "tick_contribution":contribution(s["world"])-before_contribution,"dt":dt,
            "unfulfilled_rate":s["world"]["last_unfulfilled"]/dt,
            "sku":{sku:{"forecast":sum(v for k,v in s["forecast_rates"].items() if k.startswith(sku+"|")),
                "actual":sum(v for k,v in s["world"]["last_orders"].items() if k.startswith(sku+"|"))/dt if fresh else None}
                for sku in SKUS}})
        s["tape"]=s["tape"][-180:]
        if s["day"]>=112:
            s["running"]=False
        self._persist("TICK",f"{sum(s['world']['last_orders'].values()):,} requested; {s['world']['last_unfulfilled']:,} unfulfilled",
            {"requested":sum(s["world"]["last_orders"].values()),"fulfilled":sum(s["world"]["last_fulfilled"].values()),
             "production":s["world"]["last_production"],"feed_observed":fresh,"dt":dt,
             "inputs":dict(s["inputs"]),"raw_kg":dict(s["world"]["raw"]),
             "generator_version":s["generator_version"],"order_batches":incoming,
             "stock_snapshot":[{"sku":p.split("|")[0],"depot":p.split("|")[1],"bottles":stock_total(s["world"],p,s["day"])} for p in s["world"]["stock"]]})

    def _sync_commands(self):
        s=self.state
        for decision in s["decisions"]:
            if decision["status"] in {"REJECTED","WAITED","WAITING","EXPIRED","COMPLETED","RECEIVED","FAILED"}:
                continue
            ref=decision.get("execution_id")
            shipment=next((x for x in s["world"]["shipments"] if x["id"]==ref),None)
            receipt=next((x for x in s["world"]["raw_receipts"] if x["id"]==ref),None)
            command=next((x for x in s["world"]["commands"] if x["id"]==ref),None)
            item=shipment or receipt or command
            if item and item["status"] in {"RECEIVED","COMPLETED","PASSED","FAILED"}:
                decision["status"]="FAILED" if item["status"]=="FAILED" else "RECEIVED" if shipment or receipt else "COMPLETED"
            elif decision["kind"]=="REPLAN" and s["day"]>=decision["day"]+7:
                decision["status"]="COMPLETED"
            elif decision["kind"]=="COPACKER" and s["day"]>=decision["day"]+28:
                decision["status"]="COMPLETED";s["copacker_reserved"]=0

    def _cash_available(self):
        return self._cash_for(self.state)

    @staticmethod
    def _cash_for(s):
        m=s["world"]["metrics"]
        spent=sum(m[k] for k in ("transfer_cost","air_cost","quality_cost","copacker_cost","holding_cost","repair_cost"))
        copacker=max(0,s["copacker_reserved"]-(m["copacker_cost"]-s.get("copacker_baseline_cost",0)))
        delayed=sum(j["cash_reserved"] for j in s.get("scheduled_decisions",[]) if j["status"]=="WAITING")
        return max(0,s["budget"]-s["rollout_reserved"]-s["cash_buffer"]-spent-copacker-delayed)

    def _positions(self):
        s=self.state;world=s["world"];rows=[]
        stale=s["day"]-s["reported_day"]>1 or s["inputs"]["feed_outage"]
        lead=4+s["inputs"]["traffic_delay_days"]
        for sku in SKUS:
            for depot in DEPOTS:
                p=key(sku,depot);report=s["reported_stock"][p]
                daily=sum(s["forecast_rates"][key(sku,depot,c)] for c in CHANNELS)
                qty=report["quantity"]
                cover=qty/max(daily,1)
                eligible=stock_total(world,p,s["day"]+lead,60) if not stale else report["eligible"]
                gt=stock_total(world,p,s["day"]+lead,7) if not stale else report["gt_eligible"]
                incoming=sum(x["quantity"] for x in world["shipments"] if x["sku"]==sku and x["to"]==depot
                    and x["status"]=="IN_TRANSIT" and x["eta"]<=s["day"]+lead+14
                    and all(l["expires"]>=x["eta"]+60 for l in x["lots"]))
                rows.append({"sku":sku,"depot":depot,"city":DEPOTS[depot][0],"region":DEPOTS[depot][1],
                    "quantity":qty,"daily":round(daily),"daily_precise":daily,"cover":round(cover,2),"eligible":eligible,"gt_eligible":gt,
                    "inbound":incoming,"status":"STALE" if stale else "CRITICAL" if cover<14 else "HEALTHY",
                    "oldest_expiry":report["oldest_expiry"],"reported_day":s["reported_day"]})
        return rows

    def _offer(self, kind, target, title, why, params, lead=0, deadline=2, role="Operations Manager", checks=None):
        s=self.state
        ident=f"{kind}-{digest(target)[:10]}"
        old=s["offers"].get(ident)
        changed=bool(old and (old["lead"]!=lead or old["params"]["cash"]>self._cash_available()+.01
            or (kind=="LAB_TEST" and old["params"].get("result")!=params.get("result"))
            or old.get("trigger_changed",False)
            or ("quantity" in params and params["quantity"]<old["params"].get("quantity",0))))
        if old and old["status"]=="PENDING" and not self._expired(s,old) and not changed:
            old["trigger_changed"]=False
            return ident
        if old and old.get("suppress_until",-1)>s["day"]:
            return None
        number=old.get("generation",0)+1 if old else 1
        offer={"id":ident,"kind":kind,"target":target,"title":title,"why":why,"params":params,
            "lead":lead,"deadline":round(s["day"]+max(10*s["days_per_tick"],deadline),3),
            "operational_deadline":s["day"]+max(.25,deadline),"review_until_tick":s["tick"]+10,
            "created":s["day"],"generation":number,
            "role":role,"status":"PENDING","checks":checks or [],"priority":1 if deadline<3 else 2}
        if old and old["status"]=="PENDING" and not self._expired(s,old):
            for field in ("deadline","created","review_until_tick"):
                offer[field]=old[field]
        offer["version"]=digest([s["run_id"],ident,number,params,lead,offer["deadline"]])
        s["offers"][ident]=offer
        if not old or old["status"]!="PENDING":
            self._event("RECOMMENDATION",title,{"id":ident,"version":offer["version"],"deadline":offer["deadline"]})
        return ident

    def _refresh_offers(self):
        s=self.state;world=s["world"];now=s["day"];inputs=s["inputs"]
        for offer in list(s["offers"].values()):
            if offer["status"]=="PENDING" and self._expired(s,offer):
                offer["status"]="EXPIRED"
                s["decisions"].append({"id":offer["id"],"kind":offer["kind"],"title":offer["title"],
                    "status":"EXPIRED","day":now,"actor":"System clock","reason":"Decision window elapsed"})
                self._event("MISSED_WINDOW",f"Decision window elapsed: {offer['title']}")
        active=set()
        def offer(*args,**kwargs):
            ident=self._offer(*args,**kwargs)
            if ident:
                active.add(ident)
        positions=self._positions()
        critical=[x for x in positions if x["status"]=="CRITICAL"]
        cash=self._cash_available()
        stale=inputs["feed_outage"] or now-s["last_feed_day"]>1
        total=sum(s["forecast_rates"].values())
        availability=world["capacity_factor"]
        if stale:
            offer("RESTORE_FEED","FEEDS","Restore the order and warehouse feed",
                "Demand and stock observations have stopped. Physical stock keeps moving; transfer decisions need fresh evidence.",
                {"cash":0},deadline=.5,role="Data Owner",checks=["Confirm source recovery and reconcile missed observations"])
        if not stale and (critical or total>PLANT_CAPACITY*availability*1.03) and world["allocation_until"]<=now:
            offer("REPLAN","NETWORK","Rebalance the next 7 days of production",
                "Use observed demand and depot cover to allocate the same finite capacity. Ingredient limits remain binding.",
                {"cash":0,"duration":7,"daily_capacity":round(PLANT_CAPACITY*availability)},
                deadline=min([max(.5,p["cover"]-2-inputs["traffic_delay_days"]) for p in critical] or [3]),
                role="COO",checks=["Review all five flavors and protected service levels","This changes allocation, not installed plant capacity"])
        if not stale:
            lead=4+inputs["traffic_delay_days"]
            for sku in SKUS:
                group=[p for p in positions if p["sku"]==sku]
                donors=sorted(group,key=lambda p:-p["cover"])
                available={p["depot"]:max(0,p["eligible"]-p["daily_precise"]*(lead+10)) for p in donors}
                for sink in sorted([p for p in group if p["cover"]<14],key=lambda p:p["cover"]):
                    need=max(0,sink["daily_precise"]*(lead+14)-sink["quantity"]-sink["inbound"])
                    for donor in donors:
                        if donor["depot"]==sink["depot"]:
                            continue
                        qty=int(min(need,available[donor["depot"]],100000,cash/1.5)//1000*1000)
                        if qty<1000:
                            continue
                        available[donor["depot"]]-=qty;need-=qty
                        offer("TRANSFER",f"{sku}|{donor['depot']}|{sink['depot']}",
                            f"Move {qty:,} {sku}: {donor['city']} → {sink['city']}",
                            "Same-flavor stock meets MT/QC freshness at arrival; donor retains ten projected days after transit.",
                            {"sku":sku,"from":donor["depot"],"to":sink["depot"],"quantity":qty,"cash":qty*1.5,
                             "unit_cost":1.5,"min_life":60},lead=lead,deadline=max(.25,sink["cover"]-lead),
                            role="Distribution Manager",checks=["Batch eligibility and stock are checked again at approval","Late action can mitigate later losses but cannot undo earlier shortages"])
                        break
                    if need>=1000:
                        for donor in donors:
                            if donor["depot"]==sink["depot"]:
                                continue
                            old=max(0,donor["gt_eligible"]-donor["eligible"])
                            safe=max(0,donor["quantity"]-donor["daily_precise"]*(lead+10))
                            gt_daily=s["forecast_rates"][key(sku,sink["depot"],"GT")]
                            qty=int(min(old,safe,need*.55,gt_daily*7,cash/1.5)//1000*1000)
                            if qty>=1000:
                                offer("GT_TRANSFER",f"{sku}|{donor['depot']}|{sink['depot']}",
                                    f"Rescue {qty:,} aging {sku} bottles through GT",
                                    "These batches cannot meet MT/QC acceptance. Use only verified distributor demand and at least seven days of remaining life at arrival.",
                                    {"sku":sku,"from":donor["depot"],"to":sink["depot"],"quantity":qty,"cash":qty*1.5,"unit_cost":1.5,"min_life":7},
                                    lead=lead,deadline=max(.25,min(2,sink["cover"]-lead)),role="Distribution Manager",
                                    checks=["Approver must verify distributor order and GT buyer acceptance","No outlet-level GT data is invented"])
                                break
        required=sum(v*SKUS[k.split("|")[0]]["recipe"].get("passionfruit",0) for k,v in s["forecast_rates"].items())
        cover=world["raw"]["passionfruit"]/max(required,1)
        if cover<24 and not inputs["road_closed"]:
            extra=sum(r["kg"] for r in world["raw_receipts"] if r["status"]=="IN_TRANSIT" and r.get("type")=="BUFFER")
            qty=int(min(max(0,24*required-world["raw"]["passionfruit"]-extra),50000,cash/180)//1000*1000)
            if qty>=1000:
                offer("BUFFER","PASSION","Build a limited pre-disruption pulp buffer",
                    "A 21-day closure plus three-day receipt lead exceeds opening cover. Additional stock ties up capital within the first-year envelope.",
                    {"material":"passionfruit","quantity":qty,"cash":qty*180,"unit_cost":180},lead=3,deadline=3,
                    role="Procurement Manager",checks=["Synthetic pulp price ₹180/kg; replace with a supplier quote","Purchase cash is tracked separately from contribution to avoid double-counting COGS"])
        if inputs["road_closed"]:
            remaining=max(0,(s["road_reopens"] or now+21)-now)+3
            pending=sum(r["kg"] for r in world["raw_receipts"] if r["mode"]=="AIR" and r["status"]=="IN_TRANSIT")
            qty=int(min(max(0,remaining*required-world["raw"]["passionfruit"]-pending),100000,cash/80)//1000*1000)
            if qty>=1000:
                offer("AIR","PASSION","Compare a targeted emergency air shipment",
                    "Confirmed simulated closure blocks the sole road. Air buys time, with an explicit incremental freight bill and two-day lead.",
                    {"material":"passionfruit","quantity":qty,"cash":qty*80,"unit_cost":80},lead=2,deadline=max(.25,cover-2),
                    role="COO",checks=["Synthetic quote ₹80/kg incremental, cold chain assumed for this simulation","Compare conditional contribution against waiting before approval"])
        dragon_required=sum(v*SKUS[k.split("|")[0]]["recipe"].get("dragonfruit",0) for k,v in s["forecast_rates"].items())
        domestic=raw_daily()["dragonfruit"]*.6
        depletion=world["raw"]["dragonfruit"]/max(dragon_required-domestic,1)
        sea=[r["eta"] for r in world["raw_receipts"] if r["material"]=="dragonfruit" and r["mode"]=="SEA" and r["status"]=="IN_TRANSIT"]
        next_sea=max(0,min(sea)-now) if sea else 42+inputs["import_delay_days"]
        if inputs["import_delay_days"]>0 and depletion<next_sea+5:
            pending=sum(r["kg"] for r in world["raw_receipts"] if r["material"]=="dragonfruit" and r["mode"]=="AIR" and r["status"]=="IN_TRANSIT")
            qty=int(min(max(0,(dragon_required-domestic)*min(14,next_sea-depletion+5)-pending),30000,cash/100)//1000*1000)
            if qty>=1000:
                offer("AIR_DRAGON","DRAGONFRUIT","Review expediting already-qualified dragonfruit supply",
                    "The delayed imported 40% leaves a projected gap after domestic supply. An explicit synthetic air quote can bridge part of the gap.",
                    {"material":"dragonfruit","quantity":qty,"cash":qty*100,"unit_cost":100},lead=5,
                    deadline=max(.25,depletion-5),role="Procurement Manager",
                    checks=["Synthetic incremental quote ₹100/kg; five-day clearance and cold chain must be verified","This uses the existing qualified supplier, not an invented alternative cooperative road"])
        if availability<1 and cash>=250000 and not any(x["kind"]=="REPAIR_PLANT" and x["status"]=="SCHEDULED" for x in world["commands"]):
            offer("REPAIR_PLANT","PLANTS","Restore existing plant capacity through maintenance",
                "A two-day maintenance intervention restores the installed lines. Compare it with waiting or booking the slower co-packer.",
                {"cash":250000},lead=2,deadline=2,role="Plant Manager",
                checks=["Synthetic maintenance quote ₹2.5 lakh; verify repair scope and completion lead","Restores original capacity only; fixed summer capacity is never exceeded"])
        if total>PLANT_CAPACITY*availability*1.02 and world["copacker_end"]<now and cash>=PLANT_CAPACITY*.1*14*ASSUMED_UNIT_COST*.25:
            maximum=PLANT_CAPACITY*.1*14*ASSUMED_UNIT_COST*.25
            offer("COPACKER","CAPACITY","Book co-packer capacity with 14-day notice",
                "Up to 10% extra volume becomes available after two weeks; it cannot fix an immediate shortage.",
                {"cash":round(maximum),"duration":14,"extra_per_day":round(PLANT_CAPACITY*.1)},lead=14,deadline=2,
                role="COO",checks=["Maximum premium reserved against the budget","Assumed unit cost is ₹40.80; premium is 25% of that proxy"])
        tests=[x for x in world["commands"] if x["kind"]=="LAB_TEST" and x["status"] in {"SCHEDULED","PASSED"}]
        if world["held_raw"]>0:
            if not tests and cash>=20000:
                offer("LAB_TEST","QUALITY","Test quarantined passionfruit pulp",
                    "Held ingredients cannot be used in production. A one-day lab test provides evidence for QA.",
                    {"cash":20000,"result":inputs["quality_result"]},lead=1,deadline=1,role="Quality Manager",
                    checks=["A passing result still requires an explicit QA release","A failed result writes off the held batch"])
            elif any(x["status"]=="PASSED" for x in tests):
                offer("RELEASE_QA","QUALITY","Release the lab-cleared pulp batch",
                    "The simulated laboratory has passed the held batch; QA must authorize its return to usable stock.",
                    {"cash":0,"quantity":world["held_raw"]},deadline=2,role="Quality Manager",checks=["Confirm the passing test relates to this held batch"])
        for ident,existing in s["offers"].items():
            if existing["status"]=="PENDING" and ident not in active:
                if s["tick"]<existing.get("review_until_tick",0):
                    existing["trigger_changed"]=True
                else:
                    existing["status"]="WITHDRAWN"
        s["decisions"]=s["decisions"][-100:]

    def _execute_into(self, s, offer, fraction=1.0):
        world=s["world"];p=offer["params"];kind=offer["kind"];now=s["day"]
        ref=f"decision:{uuid.uuid4().hex[:12]}"
        qty=math.floor(p.get("quantity",0)*fraction)
        cost=p["cash"]*fraction if "quantity" in p else p["cash"]
        if cost>self._cash_for(s)+.01:
            raise ValueError("This action exceeds the remaining first-year cash envelope; compare a smaller intervention")
        if kind in {"TRANSFER","GT_TRANSFER"}:
            if s["inputs"]["feed_outage"] or now-s["reported_day"]>1:
                raise ValueError("Fresh warehouse and order observations are required before moving stock")
            donor=key(p["sku"],p["from"])
            lead=4+s["inputs"]["traffic_delay_days"]
            daily=sum(s["forecast_rates"][key(p["sku"],p["from"],c)] for c in CHANNELS)
            safe=max(0,stock_total(world,donor,now)-daily*(lead+10))
            eligible=stock_total(world,donor,now+lead,p["min_life"])
            if qty<1 or qty>min(safe,eligible):
                raise ValueError("Donor stock or batch eligibility changed; refresh and review a revised or smaller transfer")
            moved,batches=take(world,donor,qty,now+lead,p["min_life"])
            assert moved==qty
            world["shipments"].append({"id":ref,"sku":p["sku"],"from":p["from"],"to":p["to"],"quantity":qty,
                "lots":batches,"eta":now+lead,"status":"IN_TRANSIT","type":kind})
            world["metrics"]["transfer_cost"]+=cost
        elif kind in {"AIR","AIR_DRAGON","BUFFER"}:
            if kind=="BUFFER" and s["inputs"]["road_closed"]:
                raise ValueError("The road is now closed; this buffer order cannot use the approved road")
            world["raw_receipts"].append({"id":ref,"material":p["material"],"kg":qty,"eta":now+offer["lead"],
                "mode":"AIR" if kind in {"AIR","AIR_DRAGON"} else "ROAD","status":"IN_TRANSIT","type":kind})
            if kind in {"AIR","AIR_DRAGON"}:
                world["metrics"]["air_cost"]+=cost
            else:
                s["cash_buffer"]+=cost
        elif kind=="REPLAN":
            world["allocation_until"]=now+7
            world["allocation_weights"]={}
            for position,report in s["reported_stock"].items():
                sku,depot=position.split("|")
                daily=sum(s["forecast_rates"][key(sku,depot,c)] for c in CHANNELS)
                cover=report["quantity"]/max(daily,1)
                world["allocation_weights"][position]=max(.25,min(3,14/max(cover,1)))*daily
        elif kind=="COPACKER":
            world["copacker_start"]=now+14;world["copacker_end"]=now+28
            s["copacker_reserved"]=cost
            s["copacker_baseline_cost"]=world["metrics"]["copacker_cost"]
        elif kind=="LAB_TEST":
            if world["held_raw"]<=0:
                raise ValueError("No quarantined material remains")
            world["metrics"]["quality_cost"]+=cost
            world["commands"].append({"id":ref,"kind":kind,"status":"SCHEDULED","eta":now+1,"result":p["result"]})
        elif kind=="REPAIR_PLANT":
            if world["capacity_factor"]>=1:
                raise ValueError("The installed plant capacity has already been restored")
            world["metrics"]["repair_cost"]+=cost
            world["commands"].append({"id":ref,"kind":kind,"status":"SCHEDULED","eta":now+2})
        elif kind=="RELEASE_QA":
            passed=next((x for x in world["commands"] if x["kind"]=="LAB_TEST" and x["status"]=="PASSED"),None)
            if not passed or world["held_raw"]<=0:
                raise ValueError("A passing lab result for the held batch is required")
            world["raw"]["passionfruit"]+=world["held_raw"];world["held_raw"]=0
            passed["status"]="RELEASED"
        elif kind=="RESTORE_FEED":
            s["inputs"]["feed_outage"]=False
            s["last_feed_day"]=now;s["reported_day"]=now
            s["reported_stock"]=self._stock_observations(world,now)
        else:
            raise ValueError("Unsupported action")
        if not s["inputs"]["feed_outage"]:
            s["reported_stock"]=self._stock_observations(world,now)
            s["reported_day"]=now
        return ref,cost,qty

    def decide(self, body):
        with self.lock:
            s=self.state
            offer=s["offers"].get(body.get("id"))
            if not offer or offer["status"]!="PENDING" or offer["version"]!=body.get("version") or self._expired(s,offer):
                raise ValueError("Recommendation changed or its decision window expired; review the current offer")
            review=s.get("review")
            if review and (review["token"]!=body.get("review_token") or review["id"]!=offer["id"]):
                raise ValueError("Use the active review to submit this decision")
            status=body.get("status")
            choice=body.get("choice")
            if choice is not None:
                if choice not in {"wait","full","half","delay","reject"}:
                    raise ValueError("Select one available decision path")
                status="WAITED" if choice=="wait" else "REJECTED" if choice=="reject" else "APPROVED"
            actor=body.get("actor","");reason=body.get("reason","")
            if not isinstance(actor,str) or not actor.strip() or len(actor)>100 or not isinstance(reason,str) or not reason.strip() or len(reason)>1000:
                raise ValueError("An operator name and reason are required")
            if status not in {"APPROVED","REJECTED","WAITED"}:
                raise ValueError("Choose an approval, wait or rejection")
            fraction=(.5 if choice=="half" else 1) if choice is not None else body.get("fraction",1)
            if isinstance(fraction,bool) or fraction not in {.5,1} or (fraction!=1 and offer["kind"] not in {"TRANSFER","GT_TRANSFER","AIR","AIR_DRAGON","BUFFER"}):
                raise ValueError("This action supports only the full quantity, or half for eligible transfers and receipts")
            ref=None;cash=qty=0
            delayed=choice=="delay"
            if status=="APPROVED":
                if body.get("checks_confirmed") is not True:
                    raise ValueError("Review and confirm the action's operational checks")
                if delayed:
                    expiry=self._effective_deadline(s,offer)
                    if s["day"]+2>=expiry:
                        raise ValueError("This offer expires before the two-day delay. Choose a current feasible path")
                    cash=offer["params"]["cash"]
                    if cash>self._cash_available()+.01:
                        raise ValueError("Insufficient uncommitted cash for the deferred action")
                    qty=offer["params"].get("quantity",0)
                    ref="deferred:"+uuid.uuid4().hex[:12]
                    frozen=copy.deepcopy(offer);frozen["deadline"]=expiry
                    s["scheduled_decisions"].append({"id":ref,"offer":frozen,"fraction":fraction,
                        "execute_day":s["day"]+2,"cash_reserved":cash,"status":"WAITING"})
                else:
                    ref,cash,qty=self._execute_into(s,offer,fraction)
            offer["status"]=status
            offer["suppress_until"]=s["day"]+(max(offer["lead"],2) if status=="APPROVED" else 2)
            lifecycle="WAITING" if delayed else self._execution_status(offer["kind"]) if status=="APPROVED" else status
            entry={"id":offer["id"],"version":offer["version"],"kind":offer["kind"],"title":offer["title"],
                "status":lifecycle,"decision":status,"actor":actor.strip(),"reason":reason.strip(),"role":offer["role"],
                "day":s["day"],"execution_id":ref,"cash":cash,"quantity":qty,"fraction":fraction,
                "choice":choice or ("half" if fraction==.5 else "full") if status=="APPROVED" else choice or "reject",
                "execute_day":s["day"]+2 if delayed else None,
                "eta":s["day"]+(2 if delayed else 0)+offer["lead"] if status=="APPROVED" and offer["lead"] else None}
            s["decisions"].append(entry)
            self._event("DECISION",f"{actor.strip()} {status.lower()}: {offer['title']}",entry)
            if ref and lifecycle=="DISPATCHED":
                self._event("RESERVED","Approved quantity reserved and dispatched; it cannot be allocated twice",{"execution_id":ref})
            self._refresh_offers()
            if review:
                s["review"]=None
                s["running"]=bool(review["was_running"] and s["day"]<112)
            self._persist("DECISION_RECORDED",f"Decision applied: {status}",entry)
            return self.snapshot()

    @staticmethod
    def _execution_status(kind):
        if kind in {"TRANSFER","GT_TRANSFER","AIR","AIR_DRAGON","BUFFER"}:return "DISPATCHED"
        if kind in {"COPACKER","LAB_TEST","REPAIR_PLANT"}:return "SCHEDULED"
        return "ACTIVE" if kind=="REPLAN" else "COMPLETED"

    def _execute_due_decisions(self, state=None, record=True):
        s=self.state if state is None else state
        for job in s.get("scheduled_decisions",[]):
            if job["status"]!="WAITING" or job["execute_day"]>s["day"]:continue
            entry=next((d for d in s["decisions"] if d.get("execution_id")==job["id"]),None)
            job["status"]="EXECUTING" # Release this job's reservation during its own cash validation.
            try:
                if s["day"]>=job["offer"]["deadline"]:
                    raise ValueError("The approval window expired before deferred execution")
                ref,cash,qty=self._execute_into(s,job["offer"],job["fraction"])
                job["status"]="EXECUTED"
                if entry:
                    entry.update({"execution_id":ref,"cash":cash,"quantity":qty,"status":self._execution_status(job["offer"]["kind"]),
                                  "eta":s["day"]+job["offer"]["lead"],"executed_day":s["day"]})
                if record:self._event("DEFERRED_EXECUTED",job["offer"]["title"])
            except ValueError as exc:
                job["status"]="FAILED"
                if entry:entry.update({"status":"FAILED","failure":str(exc),"cash":0})
                if record:self._event("DEFERRED_FAILED",str(exc),{"action_id":job["offer"]["id"]})

    def compare(self, body):
        with self.lock:
            s=copy.deepcopy(self.state)
            offer=copy.deepcopy(s["offers"].get(body.get("id")))
            if not offer or offer["version"]!=body.get("version") or offer["status"]!="PENDING":
                raise ValueError("Recommendation changed; select the current offer")
            offer["deadline"]=self._effective_deadline(s,offer)
        branches=[]
        choices=[("wait","Wait / take no new action",None,0),("full","Approve full action",1,0)]
        if offer["kind"] in {"TRANSFER","GT_TRANSFER","AIR","AIR_DRAGON","BUFFER"}:
            choices.append(("half","Approve half quantity",.5,0))
        choices.append(("delay","Wait 2 business days, then act",1,2))
        for ident,label,fraction,delay in choices:
            candidate=copy.deepcopy(s)
            w=candidate["world"]
            before=copy.deepcopy(w["metrics"]);before_cm=contribution(w)
            executed=False;issue=None
            for i in range(28):
                offset=i*.5
                candidate["day"]=s["day"]+offset
                self._execute_due_decisions(candidate,False)
                if fraction is not None and not executed and offset>=delay:
                    try:
                        if candidate["day"]>=offer["deadline"]:
                            raise ValueError("The original decision window expires before this delayed approval")
                        self._execute_into(candidate,offer,fraction)
                    except ValueError as exc:
                        issue=str(exc)
                    executed=True
                if candidate["road_reopens"] is not None and candidate["day"]>=candidate["road_reopens"]:
                    candidate["inputs"]["road_closed"]=False
                projected={}
                h=min(13,int(offset))
                for k,curve in s["model_curves"].items():
                    blend=.65*math.exp(-offset/4)
                    projected[k]=max(0,(1-blend)*curve[h]+blend*s["nowcast"][k])
                advance_world(w,candidate["day"],.5,projected,candidate["inputs"],projected)
                if not candidate["inputs"]["feed_outage"]:
                    candidate["reported_stock"]=self._stock_observations(w,candidate["day"]+.5)
                    candidate["reported_day"]=candidate["day"]+.5
                    candidate["last_feed_day"]=candidate["day"]+.5
                candidate["forecast_rates"]=projected
            requested=w["metrics"]["requested"]-before["requested"]
            fulfilled=w["metrics"]["fulfilled"]-before["fulfilled"]
            costs=sum(w["metrics"][k]-before[k] for k in ("transfer_cost","air_cost","copacker_cost","quality_cost","writeoff_cost","holding_cost","repair_cost"))
            branches.append({"id":ident,"label":label,"contribution":round(contribution(w)-before_cm),"requested":requested,
                "unfulfilled":requested-fulfilled,"fulfilled":fulfilled,
                "modeled_costs":costs,"cash_commitment":round(offer["params"]["cash"]*fraction) if fraction and not issue else 0,
                "writeoffs":w["metrics"]["expired"]-before["expired"],
                "service_pct":round(100*fulfilled/max(requested,1),2),"issue":issue})
        for row in branches:
            row["contribution_vs_wait"]=row["contribution"]-branches[0]["contribution"]
            row["additional_fulfilled"]=row["fulfilled"]-branches[0]["fulfilled"]
            row["service_value_vs_wait"]=round(row["additional_fulfilled"]*UNIT_CONTRIBUTION)
            row["extra_cost_vs_wait"]=round(row["modeled_costs"]-branches[0]["modeled_costs"])
            row["available"]=row["issue"] is None
        return {"run_id":s["run_id"],"as_of_day":s["day"],"action_id":offer["id"],"version":offer["version"],
            "horizon_days":14,"branches":branches,"assumptions":[
                "All branches start from the same current stock and booked shipments.",
                "Demand follows today's trained forecast plus a decaying nowcast; future hidden simulator demand is not used.",
                "Only current known disruptions and scheduled reopening are included; no future surprise events are revealed.",
                "Contribution uses ₹19.20 per fulfilled bottle less modeled incremental costs; this is conditional scenario evidence, not guaranteed profit.",
                "A passing lab result still needs a separate QA approval; a test alone does not release material."]}

    def snapshot(self):
        with self.lock:
            s=self.state;w=s["world"];b=s["baseline"];m=w["metrics"]
            positions=self._positions()
            market=[];curves={}
            for sku in SKUS:
                selected=[p for p in positions if p["sku"]==sku]
                predicted=sum(v for k,v in s["forecast_rates"].items() if k.startswith(sku+"|"))
                base=sum(baseline_daily(sku,d,c) for d in DEPOTS for c in CHANNELS)
                actual=sum(v for k,v in w["last_orders"].items() if k.startswith(sku+"|"))/max(s.get("last_dt",s["days_per_tick"]),.001) if s["tick"] else None
                curve=[]
                for h in range(14):
                    blend=.65*math.exp(-h/4)
                    n=sum((1-blend)*v[h]+blend*s["nowcast"][k] for k,v in s["model_curves"].items() if k.startswith(sku+"|"))
                    curve.append(round(n))
                curves[sku]=curve
                scores=[x for x in s["daily_scores"] if x["sku"]==sku]
                wape=100*sum(abs(x["actual"]-x["prediction"]) for x in scores)/max(sum(x["actual"] for x in scores),1) if scores else None
                adaptive_scores=[x for x in scores if x.get("adaptive_prediction") is not None]
                adaptive_wape=100*sum(abs(x["actual"]-x["adaptive_prediction"]) for x in adaptive_scores)/max(sum(x["actual"] for x in adaptive_scores),1) if adaptive_scores else None
                market.append({"sku":sku,"forecast":round(predicted),"actual":round(actual) if actual is not None and not s["inputs"]["feed_outage"] else None,
                    "change_pct":round(100*(predicted/base-1),2),"stock":sum(p["quantity"] for p in selected),
                    "cover":round(sum(p["quantity"] for p in selected)/max(predicted,1),2),
                    "critical":sum(p["status"]=="CRITICAL" for p in selected),"online_wape":round(wape,2) if wape is not None else None,
                    "adaptive_wape":round(adaptive_wape,2) if adaptive_wape is not None else None})
            required={material:sum(rate*SKUS[k.split("|")[0]]["recipe"].get(material,0) for k,rate in s["forecast_rates"].items()) for material in MATERIALS}
            materials=[{"material":material,"kg":round(w["raw"][material]),"daily":round(required[material]),
                "cover":round(w["raw"][material]/max(required[material],1),2),
                "inbound":round(sum(r["kg"] for r in w["raw_receipts"] if r["material"]==material and r["status"]=="IN_TRANSIT"
                    and not (material=="passionfruit" and r["mode"]=="ROAD" and s["inputs"]["road_closed"])))} for material in MATERIALS]
            timestamp=datetime.combine(date.fromisoformat(s["start_date"]),datetime.min.time())+timedelta(days=s["day"])
            pending=[copy.deepcopy(x) for x in s["offers"].values() if x["status"]=="PENDING"]
            for action in pending:
                action["deadline"]=self._effective_deadline(s,action)
                action["remaining_days"]=round(max(0,action["deadline"]-s["day"]),3)
                action["wall_seconds"]=round(action["remaining_days"]/s["days_per_tick"],1)
                action["operational_remaining"]=round(action.get("operational_deadline",action["deadline"])-s["day"],2)
                action["available"]=not action.get("trigger_changed",False)
            transit=sum(x["quantity"] for x in w["shipments"] if x["status"]=="IN_TRANSIT")
            physical=sum(l["qty"] for lots in w["stock"].values() for l in lots)
            invariant=m["initial_bottles"]+m["produced"]-m["fulfilled"]-m["expired"]-physical-transit
            card=model_card()
            return {"run_id":s["run_id"],"seed":s["seed"],"scenario":s["scenario"],"revision":s["revision"],
                "running":s["running"],"day":s["day"],"tick":s["tick"],"business_time":timestamp.strftime("%d %b %Y · %H:%M"),
                "days_per_tick":s["days_per_tick"],"inputs":dict(s["inputs"]),"road_reopens":s["road_reopens"],"effective_availability":w["capacity_factor"],
                "last_feed_day":s["last_feed_day"],"feed_age_days":round(s["day"]-s["last_feed_day"],3),
                "review":{k:v for k,v in s["review"].items() if k!="token"} if s.get("review") else None,
                "latest_inputs":copy.deepcopy(s.get("latest_inputs")),"last_input_change":copy.deepcopy(s.get("last_input_change")),
                "generator_version":s["generator_version"],
                "metrics":{"requested":m["requested"],"fulfilled":m["fulfilled"],"unfulfilled":m["requested"]-m["fulfilled"],
                    "revenue":m["revenue"],"last_interval_revenue":s["tape"][-1].get("tick_revenue",0) if s["tape"] else 0,
                    "last_interval_contribution":s["tape"][-1].get("tick_contribution",0) if s["tape"] else 0,
                    "service_pct":round(100*m["fulfilled"]/max(m["requested"],1),2) if m["requested"] else 100,
                    "contribution":round(contribution(w)),"baseline_contribution":round(contribution(b)),
                    "contribution_lift":round(contribution(w)-contribution(b)),"writeoffs":m["expired"],
                    "incremental_cost":round(sum(m[k] for k in ("transfer_cost","air_cost","quality_cost","copacker_cost","holding_cost","repair_cost"))),
                    "critical_positions":sum(p["status"]=="CRITICAL" for p in positions),"pending":len(pending),
                    "budget_remaining":round(self._cash_available()),"cash_buffer":s["cash_buffer"],"budget":s["budget"],
                    "rollout_reserved":s["rollout_reserved"],"held_pulp_kg":round(w["held_raw"]),
                    "bottle_conservation_error":invariant,"produced":m["produced"],"in_transit":transit},
                "market":market,"forecast_curves":curves,"positions":positions,"materials":materials,
                "actions":sorted(pending,key=lambda a:a["deadline"]),"decisions":copy.deepcopy(s["decisions"][-50:]),
                "events":copy.deepcopy(s["events"][-50:]),"tape":copy.deepcopy(s["tape"]),
                "shipments":[{k:v for k,v in x.items() if k!="lots"} for x in w["shipments"] if x["status"]=="IN_TRANSIT"][-30:],
                "receipts":[dict(x) for x in w["raw_receipts"] if x["status"]=="IN_TRANSIT"][-25:],
                "scheduled_events":copy.deepcopy(s["scheduled_events"]),
                "model":{"name":card["name"],"version":card.get("version"),"status":card["status"],
                    "features":card.get("features",[]),
                    "positions":s["model_used"],"total_positions":135,"training_rows":card.get("training_rows"),
                    "test_wape":card.get("metrics",{}).get("test",{}).get("model_wape_pct"),
                    "runtime":"Fixed trained trees + observation-driven exponential nowcast; complete-day history updates at midnight"},
                "presets":{k:v["label"] for k,v in PRESETS.items()},
                "assumptions":["All operating events, locations, recipes, lab outcomes and quotes are synthetic; no real orders or freight are executed.",
                    "One wall-clock second advances the selected business hours; partial-day totals are never treated as a full training day.",
                    "Contribution is fulfilled bottles × ₹19.20, less incremental transfer, air, co-packer, test, holding and write-off costs. It is not company net profit.",
                    "Scenario cost assumptions: ₹40.80/bottle write-off basis; ₹180/kg passionfruit purchase/disposal; ₹80/kg passionfruit and ₹100/kg dragonfruit incremental air; ₹20,000 lab test; ₹2.5 lakh maintenance; ₹0.10/kg/day excess passionfruit holding.",
                    "The ₹2.5 crore first-year envelope reserves an illustrative ₹1.2 crore for build/run. Buffer working capital and maximum co-packer premium are committed before other decisions.",
                    "Both policies start with identical opening stock and face identical exogenous demand and disruptions. The comparison policy makes no new intervention.",
                    "GT means distributor demand. No outlet-level general-trade observations are generated.",
                    "Opening synthetic raw cover is 14 days passionfruit, 21 days dragonfruit, 30 days other materials. The imported 40% dragonfruit share has a 42-day replenishment lead; domestic supply is modeled separately. All raw batches stay within six-month life during the 112-day season."]}

    def export_events(self):
        with self.lock:
            rows=self.db.execute("SELECT seq,business_day,received_at,kind,payload FROM live_events WHERE run_id=? ORDER BY seq",(self.state["run_id"],)).fetchall()
            return {"run_id":self.state["run_id"],"seed":self.state["seed"],"synthetic":True,
                "events":[{**dict(r),"payload":json.loads(r["payload"])} for r in rows]}
