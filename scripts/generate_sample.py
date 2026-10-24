#!/usr/bin/env python3
"""Write reproducible, case-constrained example input files for the live API."""
import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.operations import demo_records, iso_day, validate


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--as-of", default="2026-10-24")
    p.add_argument("--out", default="data/operational_sample")
    args = p.parse_args()
    as_of = iso_day(args.as_of)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    counts = {}
    for kind, rows in demo_records(as_of).items():
        if not rows:
            continue
        rows = [validate(kind, x) for x in rows]
        columns = sorted({key for row in rows for key in row})
        with (out/f"{kind}.csv").open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            for row in rows:
                writer.writerow({key: json.dumps(value, separators=(",", ":")) if isinstance(value, dict) else value
                                 for key, value in row.items()})
        counts[kind] = len(rows)
    manifest = {
        "data_type": "SYNTHETIC CASE-CONSTRAINED EXAMPLE; NOT PULP RIOT ACTUALS",
        "as_of": as_of.isoformat(), "counts": counts,
        "case_facts": ["five flavor shares", "nine depots", "GT 55% / MT 25% / QC 20%",
                       "9.6 crore summer bottles", "fourfold QC order case stress",
                       "14-day opening passionfruit pulp cover and three-week road closure"],
        "synthetic_choices": ["specific depot identities and local weights", "SKU recipe kilograms per bottle",
                              "fourfold QC orders on the final two sample days; the replay uses a 14-day spike",
                              "daily orders, fulfillment, and batch ages", "road report and attention record dates",
                              "four-week model month and 112-day summer"],
        "validation": "Every row passes engine.operations.validate before writing. Scenario outcomes are not measured savings."
    }
    (out/"manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
