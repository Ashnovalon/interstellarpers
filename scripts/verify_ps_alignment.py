"""Read-only PS audit probes; uses isolated memory stores, never the company DB.

Prints observed behavior, including known gaps. This is diagnostic evidence, not
a passing acceptance suite. Run from the repository root with Python 3.11+.
"""
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine.operations import Store, plan, baseline_daily
from engine.live import LiveEngine, raw_daily


def main():
    today = date(2026, 10, 25)
    daily = sum(baseline_daily("Dragon Passion", "D1", c) for c in ("GT", "MT", "QC"))

    def lot(ident, quantity, observed_days_ago, age):
        return {"id": ident, "date": (today-timedelta(days=observed_days_ago)).isoformat(),
                "sku": "Dragon Passion", "depot": "D1", "quantity": quantity,
                "manufactured": (today-timedelta(days=age)).isoformat(),
                "expires": (today+timedelta(days=90-age)).isoformat()}

    results = {}
    for name, rows in (
        ("channel_ineligible_stock", [lot("old", round(daily*21), 0, 40)]),
        ("mixed_report_freshness", [lot("stale-large", 100000, 7, 10), lot("fresh-tiny", 1, 0, 0)]),
    ):
        store = Store(":memory:")
        try:
            store.ingest("lot", rows)
            result = plan(store, today, use_model=False)
            results[name] = next(p for p in result["positions"]
                                 if p["sku"] == "Dragon Passion" and p["depot"] == "D1")
        finally:
            store.close()
    engine = LiveEngine(":memory:")
    try:
        state = engine.state
        results["buffer_funding"] = {
            "synthetic_baseline_passion_kg_per_day": raw_daily()["passionfruit"],
            "ten_extra_days_at_synthetic_180_rupees_per_kg": raw_daily()["passionfruit"]*10*180,
            "live_action_cash_after_build_run_reserve": state["budget"]-state["rollout_reserved"],
        }
    finally:
        engine.close()
    report = json.loads((ROOT/"data/forecast_benchmark.json").read_text(encoding="utf-8"))
    results["stored_benchmark"] = {
        "mismatched_sources": [name for name, digest in report.get("source_sha256", {}).items()
                               if not (ROOT/name).exists() or hashlib.sha256((ROOT/name).read_bytes()).hexdigest() != digest],
        "summary": report["summary"],
    }
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
