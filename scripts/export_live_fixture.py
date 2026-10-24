"""Write a deterministic live-state fixture for the browser DOM integration test."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from engine.live import LiveEngine

engine=LiveEngine()
try:
    engine.control({"action":"reset","scenario":"sandbox","seed":77})
    engine.inject("viral")
    for _ in range(8):engine.control({"action":"step"})
    target=Path("output/live_fixture.json")
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(engine.snapshot(),ensure_ascii=False),encoding="utf-8")
    print(f"Wrote {target}")
finally:engine.close()
