#!/usr/bin/env python3
"""Read-only smoke test of a running control tower instance."""
from __future__ import annotations

import argparse
import json
from urllib.request import Request, urlopen


def get(root, path):
    with urlopen(Request(root+path), timeout=20) as response:
        return response.read(), response.status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--replay", action="store_true", help="also compute the two daily scenario policies")
    args = parser.parse_args()
    root = args.url.rstrip("/")
    health = json.loads(get(root, "/api/health")[0])
    assert health["status"] == "ok"
    html = get(root, "/operations")[0].decode("utf-8")
    assert "Demand forecast" in html and "Preview and validate" in html
    for asset in ("/operations.js", "/operations-v2.js", "/operations.css", "/operations-v2.css"):
        assert get(root, asset)[1] == 200
    plan = json.loads(get(root, "/api/plan")[0])
    assert plan["forecast"]["series"] and len(plan["forecast"]["series"][0]["points"]) == 14
    assert plan["metrics"]["daily_demand_bottles"] >= 0
    print(json.dumps({"status":"PASS", "mode":plan["mode"], "as_of":plan["as_of"],
        "orders":plan["quality"]["record_counts"]["order"], "actions":len(plan["actions"]),
        "critical_positions":plan["metrics"]["critical_positions"],
        "model_status":plan["forecast"]["card"]["status"],
        "model_positions":plan["forecast"]["model_positions"]}, indent=2))
    if args.replay:
        result = json.loads(get(root, "/api/replay")[0])
        assert result["last_summer_planning"]["requested_bottles"] == result["approved_proposals"]["requested_bottles"]
        print(json.dumps({"replay":"PASS", "difference":result["difference"]}, indent=2))


if __name__ == "__main__":
    main()
