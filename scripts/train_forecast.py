#!/usr/bin/env python3
"""Train/evaluate a pooled gradient-boosted demand model and export safe JSON.

py -3 scripts/train_forecast.py --synthetic
py -3 scripts/train_forecast.py --db output/company.sqlite
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.forecast import FEATURES, MODEL_PATH, aggregate_orders, features, predict_tree_model
from engine.operations import CHANNELS, DEPOTS, SKUS, Store, baseline_daily, local_today, utc_now


def synthetic_history(end, days=300):
    rng = random.Random(42)
    rows = []
    start = end - timedelta(days=days - 1)
    for sku in SKUS:
        for depot in DEPOTS:
            for channel in CHANNELS:
                base = baseline_daily(sku, depot, channel) * rng.uniform(.75, 1.25)
                phase = rng.uniform(-.5, .5)
                shock_start = rng.randint(35, 60)
                shocks = [(shock_start + cycle * 65, rng.randint(7, 18), rng.uniform(1.7, 4.5)) for cycle in range(5)]
                for i in range(days):
                    day = start + timedelta(days=i)
                    weekly = 1 + (.19 if channel == "QC" else .11) * math.sin(2 * math.pi * day.weekday()/7 + phase)
                    seasonal = 1 + .12 * math.sin(i * 2 * math.pi / 180)
                    trend = 1 + i * .0004
                    shock = next((factor for began, duration, factor in shocks if began <= i < began+duration), 1)
                    requested = max(0, round(base * weekly * seasonal * trend * shock * rng.uniform(.94, 1.06)))
                    in_stock = rng.random() > .025
                    rows.append({"id": f"training:{sku}:{depot}:{channel}:{day}", "date": day.isoformat(),
                        "sku": sku, "depot": depot, "channel": channel, "requested": requested,
                        "fulfilled": requested if in_stock else round(requested * .75), "in_stock": in_stock, "sample": True})
    return rows


def wape(actual, predicted):
    return 100 * sum(abs(a-p) for a, p in zip(actual, predicted)) / max(sum(actual), 1)


def train(rows, destination=MODEL_PATH, synthetic=False):
    import numpy as np
    import sklearn
    from sklearn.ensemble import GradientBoostingRegressor
    grouped = aggregate_orders(rows)
    days = sorted({r["date"] for r in rows})
    if len(days) < 120:
        raise ValueError("At least 120 dated days of history are required for temporal training, validation and test.")
    end = date.fromisoformat(days[-1])
    test_start, validation_start = end - timedelta(days=41), end - timedelta(days=69)
    buckets = {"train": [], "validation": [], "test": []}
    fingerprint = hashlib.sha256(json.dumps(sorted(rows, key=lambda r:r["id"]), sort_keys=True).encode()).hexdigest()
    for history in grouped.values():
        for origin_string in sorted(history)[::2]:
            origin = date.fromisoformat(origin_string)
            inputs = [(origin-timedelta(days=d)).isoformat() for d in range(13, -1, -1)]
            if not all(d in history for d in inputs):
                continue
            values = [history[d]["requested"] for d in inputs]
            for horizon in range(1, 15):
                target = origin + timedelta(days=horizon)
                if target.isoformat() not in history:
                    continue
                # Entire origin and target are inside a split; crossing windows are purged.
                split = "train" if target < validation_start else "validation" if origin >= validation_start and target < test_start else "test" if origin >= test_start else None
                if split is None:
                    continue
                x, scale = features(values, target, horizon)
                actual = history[target.isoformat()]["requested"]
                buckets[split].append((x, actual / scale, scale, actual,
                    sum(values[-7:])/7, values[-7 + ((horizon-1) % 7)], target.isoformat(), origin_string, horizon))
    if min(len(b) for b in buckets.values()) < 100:
        raise ValueError("Insufficient consecutive observations in each temporal split (minimum 100 examples).")
    rng = random.Random(17)
    fit_rows = rng.sample(buckets["train"], min(65000, len(buckets["train"])))
    estimator = GradientBoostingRegressor(n_estimators=90, max_depth=3, learning_rate=.07,
        loss="huber", min_samples_leaf=35, subsample=.85, random_state=17)
    estimator.fit(np.array([r[0] for r in fit_rows]), np.array([r[1] for r in fit_rows]))
    artifact = {"initial": float(estimator.init_.constant_[0, 0]), "learning_rate": estimator.learning_rate,
                "trees": [], "residual_radius": {}}
    for item in estimator.estimators_[:, 0]:
        tree = item.tree_
        artifact["trees"].append({"left": tree.children_left.tolist(), "right": tree.children_right.tolist(),
            "feature": tree.feature.tolist(), "threshold": tree.threshold.tolist(), "value": tree.value[:, 0, 0].tolist()})
    metrics = {}
    for split in ("validation", "test"):
        samples = buckets[split]
        normalized = estimator.predict(np.array([r[0] for r in samples]))
        predicted = [max(0, p) * r[2] for p,r in zip(normalized, samples)]
        metrics[split] = {"model_wape_pct": round(wape([r[3] for r in samples], predicted), 3),
            "mean7_wape_pct": round(wape([r[3] for r in samples], [r[4] for r in samples]), 3),
            "seasonal_wape_pct": round(wape([r[3] for r in samples], [r[5] for r in samples]), 3)}
        if split == "validation":
            for horizon in range(1, 15):
                errors = sorted(abs(r[1]-max(0,p)) for r,p in zip(samples, normalized) if r[8] == horizon)
                artifact["residual_radius"][str(horizon)] = errors[min(len(errors)-1, math.ceil(.9*(len(errors)+1))-1)]
        else:
            metrics[split]["interval_coverage_pct"] = round(100 * sum(abs(r[3]-p) <= artifact["residual_radius"][str(r[8])]*r[2] for r,p in zip(samples,predicted))/len(samples), 2)
    val = metrics["validation"]
    eligible = val["model_wape_pct"] < .98 * min(val["mean7_wape_pct"], val["seasonal_wape_pct"])
    probe = fit_rows[:20]
    if not np.allclose([predict_tree_model(artifact,r[0]) for r in probe], np.maximum(0,estimator.predict([r[0] for r in probe])), rtol=1e-7):
        raise RuntimeError("Exported tree prediction did not match training estimator")
    artifact["card"] = {"name": "PulpCast · Gradient boosted trees", "version": fingerprint[:12],
        "status": "VALIDATED" if eligible else "BASELINE_RETAINED", "trained_at": utc_now(), "synthetic": synthetic,
        "data_start": days[0], "data_end": days[-1], "training_rows": len(rows), "series_count": len(grouped),
        "features": FEATURES, "horizons": 14, "sklearn_version": sklearn.__version__, "seed": 42,
        "data_sha256": fingerprint, "metrics": metrics, "fitted_examples": len(fit_rows),
        "splits": {key:{"examples":len(samples),"origin_start":min(r[7] for r in samples),
            "target_end":max(r[6] for r in samples)} for key,samples in buckets.items()},
        "top_features": [{"name": FEATURES[i], "weight": round(float(weight),4)} for i,weight in sorted(enumerate(estimator.feature_importances_), key=lambda x:-x[1])[:6]],
        "limitations": ["Synthetic training and scores demonstrate pipeline behavior, not real-world accuracy." if synthetic else "Validate on new company periods before shared deployment.",
            "Unknown viral events cannot be predicted before evidence arrives; attention alone never changes bottle demand.",
            "Requested orders must include unfulfilled requests; fulfilled-only sales are censored demand.",
            "Missing days cause baseline fallback; spike floors are operating safeguards outside the model backtest.",
            "Ranges assume error behavior similar to validation; shocks and drift can break coverage."]}
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(artifact, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temporary.replace(destination)
    return artifact["card"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--synthetic", action="store_true")
    choice.add_argument("--db")
    parser.add_argument("--end", default=(local_today()-timedelta(days=14)).isoformat())
    parser.add_argument("--out", default=str(MODEL_PATH))
    args = parser.parse_args()
    if args.synthetic:
        rows = synthetic_history(date.fromisoformat(args.end))
    else:
        if not Path(args.db).is_file():
            raise ValueError(f"Database does not exist: {args.db}")
        store = Store(args.db)
        rows = store.records("order")
        store.close()
        if any(r.get("sample") for r in rows):
            raise ValueError("Real-data training refuses sample/mixed records. Use a separate company database.")
    card = train(rows, args.out, args.synthetic)
    print(json.dumps(card, indent=2))


if __name__ == "__main__":
    main()
