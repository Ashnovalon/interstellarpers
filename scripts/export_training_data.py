"""Materialize the exact generated history used by the shipped model for inspection."""
import csv
import hashlib
import json
import sys
from datetime import date
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from engine.forecast import model_card
from scripts.train_forecast import synthetic_history

card=model_card()
if not card.get("synthetic"):
    raise SystemExit("The current artifact is not synthetic; no training data will be invented for it")
days=(date.fromisoformat(card["data_end"])-date.fromisoformat(card["data_start"])).days+1
rows=synthetic_history(date.fromisoformat(card["data_end"]),days)
fingerprint=hashlib.sha256(json.dumps(sorted(rows,key=lambda r:r["id"]),sort_keys=True).encode()).hexdigest()
if fingerprint!=card["data_sha256"]:
    raise SystemExit("Generator no longer matches the artifact's data fingerprint; retrain explicitly")
out=Path("data/training");out.mkdir(parents=True,exist_ok=True)
with (out/"synthetic_orders.csv").open("w",newline="",encoding="utf-8") as f:
    writer=csv.DictWriter(f,fieldnames=list(rows[0]))
    writer.writeheader();writer.writerows(rows)
manifest={"synthetic":True,"rows":len(rows),"series":card["series_count"],"data_start":card["data_start"],
    "data_end":card["data_end"],"sha256":fingerprint,"model_version":card["version"],"seed":42,
    "purpose":"Reproducible model training history. Live event batches are stored separately in live_events and exported from the UI.",
    "quality_limits":"Generated daily patterns do not establish real-company accuracy; live stress tests use independent scenarios."}
(out/"manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
print(json.dumps(manifest,indent=2))
