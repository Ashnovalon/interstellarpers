"""Run independent disruption cases with a transparent scripted decision policy.

This is an offline regression experiment, never an auto-approver in the live app.
"""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from engine.live import LiveEngine, MATERIALS

CASES={"normal":[],"viral":[(1,"viral")],"false_hype":[(1,"rumor")],
    "road_closure":[(2,"closure")],"plant_outage":[(2,"outage")],
    "traffic":[(1,"viral"),(3,"traffic")],"import_delay":[(1,"imports")],
    "quality":[(2,"quality")],"feed_loss":[(1,"viral"),(2,"feed")],
    "compound":[(1,"viral"),(4,"closure"),(7,"outage"),(9,"quality")]}

def run_case(name,events,days):
    engine=LiveEngine()
    try:
        engine.control({"action":"reset","scenario":"sandbox","seed":101})
        done=set();checks=0;acted=[]
        for tick in range(days*4):
            day=engine.state["day"]
            for index,(at,preset) in enumerate(events):
                if index not in done and day>=at:
                    engine.inject(preset);done.add(index)
            # A named test planner approves free allocation and evidence actions.
            # Transfers are taken only if a current conditional comparison favors one.
            if tick%4==0:
                actions=engine.snapshot()["actions"]
                comparisons=0
                for action in actions[:12]:
                    current=engine.state["offers"].get(action["id"])
                    if not current or current["status"]!="PENDING" or current["version"]!=action["version"]:
                        continue
                    choose=action["kind"] in {"REPLAN","RESTORE_FEED","LAB_TEST","RELEASE_QA","REPAIR_PLANT"}
                    fraction=1
                    if action["kind"] in {"TRANSFER","GT_TRANSFER","AIR","AIR_DRAGON"}:
                        if comparisons>=1:continue
                        comparisons+=1
                        result=engine.compare({"id":action["id"],"version":action["version"]})
                        eligible=[x for x in result["branches"] if x["id"] in {"full","half"} and not x["issue"]]
                        best=max(eligible,key=lambda x:x["contribution_vs_wait"],default=None)
                        choose=best is not None and best["contribution_vs_wait"]>1000
                        fraction=.5 if best and best["id"]=="half" else 1
                    if choose:
                        try:
                            engine.decide({"id":action["id"],"version":action["version"],"status":"APPROVED",
                                "actor":"Offline test planner","reason":"Scripted regression policy; not a live approval",
                                "checks_confirmed":True,"fraction":fraction})
                            acted.append(action["kind"])
                        except ValueError:
                            pass # Earlier approvals can invalidate the remaining proposals.
            engine.control({"action":"step"})
            state=engine.snapshot()
            if state["metrics"]["bottle_conservation_error"]!=0:raise RuntimeError(f"Stock imbalance in {name}")
            world=engine.state["world"];m=world["metrics"]
            for material in MATERIALS:
                total=world["raw"][material]+(world["held_raw"] if material=="passionfruit" else 0)
                expected=m["raw_initial"][material]+m["raw_received"][material]-m["raw_consumed"][material]-m["raw_disposed"][material]
                if abs(total-expected)>.001:raise RuntimeError(f"Raw imbalance: {name}/{material}")
            checks+=1
        state=engine.snapshot()
        return {"case":name,"days":days,"ticks_checked":checks,"inputs":events,"approved_test_actions":acted,
            "metrics":state["metrics"],"model_daily_scores":state["market"],"event_count":len(engine.export_events()["events"])}
    finally:engine.close()

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--days",type=int,default=28)
    parser.add_argument("--cases",default=",".join(CASES));parser.add_argument("--out",default="output/live_evaluation.json")
    args=parser.parse_args()
    if not 1<=args.days<=112:parser.error("days must be 1..112")
    results=[]
    for name in args.cases.split(","):
        if name not in CASES:parser.error(f"Unknown case {name}")
        row=run_case(name,CASES[name],args.days);results.append(row)
        print(f"{name}: {row['ticks_checked']} balanced ticks; contribution lift {row['metrics']['contribution_lift']:,}; service {row['metrics']['service_pct']}%",flush=True)
    output={"synthetic":True,"policy":"Named offline test planner, free/evidence actions plus positive conditional contribution branches; no claim of optimality or guaranteed savings.","cases":results}
    path=Path(args.out);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(output,indent=2),encoding="utf-8")

if __name__=='__main__':main()
