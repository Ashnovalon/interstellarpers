"""Direct 1–14 day forecasts. Safe JSON trees; no ML dependency at serving time."""
from __future__ import annotations

import json
import math
import statistics
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

MODEL_PATH = Path(__file__).resolve().parents[1] / "data/models/demand_model.json"
FEATURES = ["lag_1", "lag_2", "lag_3", "lag_7", "lag_14", "mean_3", "mean_7",
            "volatility_7", "recent_vs_week", "target_weekday_sin", "target_weekday_cos", "horizon"]


def aggregate_orders(rows):
    """Sum distinct transaction IDs into daily series; missing days stay missing."""
    grouped = {}
    for row in rows:
        key = (row["sku"], row["depot"], row["channel"])
        daily = grouped.setdefault(key, {})
        value = daily.setdefault(row["date"], {"requested": 0, "fulfilled": 0, "in_stock": True})
        value["requested"] += row["requested"]
        value["fulfilled"] += row["fulfilled"]
        value["in_stock"] = value["in_stock"] and row["in_stock"]
    return grouped


def features(values, target, horizon):
    """Only the 14 days available at the forecast origin are used as features."""
    scale = max(statistics.mean(values), 1)
    normalized = [v / scale for v in values]
    x = [normalized[-1], normalized[-2], normalized[-3], normalized[-7], normalized[-14],
         statistics.mean(normalized[-3:]), statistics.mean(normalized[-7:]),
         statistics.pstdev(normalized[-7:]),
         statistics.mean(values[-2:]) / max(statistics.mean(values[:7]), 1),
         math.sin(2 * math.pi * target.weekday() / 7),
         math.cos(2 * math.pi * target.weekday() / 7), horizon / 14]
    return x, scale


@lru_cache(maxsize=2)
def _load(path, stamp):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_model():
    if not MODEL_PATH.exists():
        return None
    return _load(str(MODEL_PATH), MODEL_PATH.stat().st_mtime_ns)


def model_card():
    model = load_model()
    return model["card"] if model else {"status": "NOT_TRAINED", "name": "Observed-order baseline",
        "limitations": ["Run scripts/train_forecast.py to train and evaluate a model."]}


def predict_tree_model(model, x):
    value = model["initial"]
    for tree in model["trees"]:
        i = 0
        while tree["left"][i] != -1:
            i = tree["left"][i] if x[tree["feature"][i]] <= tree["threshold"][i] else tree["right"][i]
        value += model["learning_rate"] * tree["value"][i]
    return max(0, value)


def forecast_position(history, as_of, fallback, spike=False, sample=False, enabled=True):
    model = load_model() if enabled else None
    dates = [(as_of - timedelta(days=d)).isoformat() for d in range(13, -1, -1)]
    complete = all(d in history for d in dates)
    reason = "14 consecutive daily observations required"
    eligible = False
    if model and complete:
        card = model["card"]
        if card["status"] != "VALIDATED":
            reason = "Model did not beat both validation baselines; baseline retained"
        elif card["synthetic"] != sample:
            reason = "Model provenance does not match these inputs; retrain on real history"
        elif as_of.isoformat() < card["data_end"]:
            reason = "Model uses later data than this planning date; baseline retained"
        else:
            eligible = True
    elif not model:
        reason = "No trained model enabled"
    values = [history[d]["requested"] for d in dates] if complete else []
    points = []
    for horizon in range(1, 15):
        target = as_of + timedelta(days=horizon)
        estimate, low, high = fallback, None, None
        if eligible:
            x, scale = features(values, target, horizon)
            estimate = predict_tree_model(model, x) * scale
            # Keep observed viral pressure until the planner has reviewed its decline.
            estimate = max(estimate, fallback) if spike else estimate
            radius = model["residual_radius"][str(horizon)] * scale
            low, high = max(0, estimate - radius), estimate + radius
        points.append({"date": target.isoformat(), "prediction": round(estimate),
                       "low": round(low) if low is not None else None,
                       "high": round(high) if high is not None else None})
    return {"points": points, "daily": statistics.mean(p["prediction"] for p in points[:7]),
            "source": "MODEL_WITH_SPIKE_FLOOR" if eligible and spike else "MODEL" if eligible else "BASELINE",
            "explanation": "Trained lag + weekday forecast; observed spike floor applied" if eligible and spike
                else "Trained lag + weekday forecast" if eligible else reason}


def dashboard_forecast(orders, as_of, demand_rows, enabled=True):
    grouped = aggregate_orders(orders)
    has_sample = any(r.get("sample") for r in orders)
    synthetic = None if has_sample and not all(r.get("sample") for r in orders) else has_sample
    series = []
    for r in demand_rows:
        key = (r["sku"], r["depot"], r["channel"])
        result = forecast_position(grouped.get(key, {}), as_of, r["forecast_per_day"],
                                   r["reason"].startswith("two observed"), synthetic, enabled)
        series.append({"sku": key[0], "depot": key[1], "channel": key[2], **result})
    history = []
    for ago in range(13, -1, -1):
        day = (as_of - timedelta(days=ago)).isoformat()
        available = [h[day] for h in grouped.values() if day in h]
        history.append({"date": day, "requested": sum(r["requested"] for r in available) if available else None,
                        "series_count": len(available)})
    return {"card": model_card(), "series": series, "history": history,
            "model_positions": sum(r["source"] != "BASELINE" for r in series),
            "interval_note": "Ranges use the 90th percentile of absolute validation errors by horizon. They are empirical ranges, not guaranteed coverage; pooled ranges are not a joint confidence interval."}
