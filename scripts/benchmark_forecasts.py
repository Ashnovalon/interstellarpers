"""Paired offline forecast experiments; never executes against a saved live run.

Same seeds, speed, exogenous events and deterministic approval rule for every
forecast. Actions may differ because forecasts differ: this is the policy effect
we measure. No method receives future hidden orders. Synthetic evidence only.
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from engine.live import LiveEngine, FORECAST_MODES
from engine.allocation import allocate

CASES={"normal":[],"viral":[(1,"viral")],"compound":[(1,"viral"),(4,"closure"),(7,"outage"),(9,"heatwave")]}


def run(mode,seed,days,events):
    engine=LiveEngine()
    try:
        engine.control({"action":"reset","scenario":"sandbox","seed":seed,"forecast_mode":mode})
        done=set();actions=0;demand_hash=hashlib.sha256();scored=[];day_prediction=dict(engine.state["forecast_rates"]);daily={}
        for tick in range(days*4):
            day=engine.state["day"]
            for index,(at,preset) in enumerate(events):
                if index not in done and day>=at:
                    engine.inject(preset);done.add(index)
            if tick%4==0:
                day_prediction=dict(engine.state["forecast_rates"]);daily={}
                # Same daily approval rule for every forecaster. No branch optimizer,
                # human judgment, hidden truth or differing action caps per method.
                used_transfer=False
                for offer in engine.snapshot()["actions"]:
                    kind=offer["kind"]
                    choose=kind in {"REPLAN","REPAIR_PLANT","RESTORE_FEED","LAB_TEST","RELEASE_QA"}
                    if kind in {"TRANSFER","GT_TRANSFER"} and not used_transfer:
                        choose=True;used_transfer=True
                    if choose:
                        try:
                            engine.decide({"id":offer["id"],"version":offer["version"],"choice":"full",
                                "actor":"Offline benchmark policy","reason":"Identical deterministic daily policy",
                                "checks_confirmed":True},capture_outcomes=False)
                            actions+=1
                        except ValueError:pass  # A prior approval may invalidate an offer.
            engine.control({"action":"step"})
            for row in engine.state["latest_inputs"]["rows"]:
                daily[row["series"]]=daily.get(row["series"],0)+row["requested"]
                demand_hash.update(f"{row['series']}:{row['requested']};".encode())
            if tick%4==3:
                scored.extend((qty,day_prediction[k]) for k,qty in daily.items())
            if engine.snapshot()["metrics"]["bottle_conservation_error"]:
                raise RuntimeError("Benchmark violated stock conservation")
        metrics=engine.snapshot()["metrics"]
        return {"mode":mode,"seed":seed,"days":days,"demand_sha256":demand_hash.hexdigest(),"approved_actions":actions,
            "absolute_error":sum(abs(a-p) for a,p in scored),"scored_requested":sum(a for a,p in scored),
            "daily_series_wape":round(100*sum(abs(a-p) for a,p in scored)/max(1,sum(a for a,p in scored)),3),
            **{k:metrics[k] for k in ("requested","fulfilled","unfulfilled","service_pct","writeoffs","contribution","incremental_cost")}}
    finally:engine.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days",type=int,default=28)
    parser.add_argument("--seeds",default="101,202")
    parser.add_argument("--cases",default="normal,viral,compound")
    parser.add_argument("--out",default="data/forecast_benchmark.json")
    args=parser.parse_args()
    if not 1<=args.days<=112:parser.error("days must be 1..112")
    seeds=[int(s) for s in args.seeds.split(',')];cases=args.cases.split(',')
    if any(c not in CASES for c in cases):parser.error("Unknown scenario")
    paths=["engine/live.py","engine/allocation.py","engine/forecast.py","engine/operations.py","scripts/benchmark_forecasts.py","data/models/demand_model.json"]
    provenance={p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths}
    rows=[]
    for case in cases:
        for seed in seeds:
            paired=[]
            for mode in FORECAST_MODES:
                row=run(mode,seed,args.days,CASES[case]);row["case"]=case;rows.append(row);paired.append(row)
                print(f"{case} / {seed} / {mode}: WAPE {row['daily_series_wape']}%; contribution {row['contribution']}",flush=True)
            if len({r["demand_sha256"] for r in paired})!=1:raise RuntimeError("Forecast methods did not face identical requests")
    summary=[]
    for mode in FORECAST_MODES:
        group=[r for r in rows if r["mode"]==mode]
        requested=sum(r["requested"] for r in group);fulfilled=sum(r["fulfilled"] for r in group)
        summary.append({"mode":mode,"runs":len(group),"wape":round(100*sum(r["absolute_error"] for r in group)/max(1,sum(r["scored_requested"] for r in group)),3),
            "service_pct":round(100*fulfilled/max(1,requested),3),"contribution":sum(r["contribution"] for r in group),
            "unfulfilled":requested-fulfilled,"writeoffs":sum(r["writeoffs"] for r in group),"cost":sum(r["incremental_cost"] for r in group)})
    diagnostic=allocate({"blocked":100,"open":100},{"blocked":1,"open":1},100,{"a":0,"b":100},{"blocked":{"a":1},"open":{"b":1}})
    report={"synthetic":True,"generated_at":datetime.now(timezone.utc).isoformat(),"days":args.days,"seeds":seeds,
        "cases":{c:CASES[c] for c in cases},"step_days":.25,"summary":summary,"runs":rows,"source_sha256":provenance,
        "policy":"Once per business day: approve feasible allocation/evidence/maintenance and at most one transfer in deadline order. No air, buffer, or co-packer approvals. Same rule for all methods; no future observations.",
        "limitations":["Synthetic paired experiment; not company performance or proof of optimality.","Results depend on the declared decision policy and scenario set.","WAPE uses 135 daily series forecasts saved before each day; no within-day nowcast is scored as a day-start forecast.","No statistically calibrated significance or uncertainty claim is made."],
        "allocation_diagnostic":{"case":"One product has no ingredient; another can use all plant capacity","legacy_produced":50,"progressive_produced":sum(diagnostic.values()),"allocation":diagnostic}}
    out=Path(args.out);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,indent=2),encoding="utf-8")


if __name__=="__main__":main()
