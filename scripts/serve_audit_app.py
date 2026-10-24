"""Isolated in-memory HTTP app for UI audit tests. No company DB or external feeds."""
import json
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
for name in ("CONTROL_TOWER_TOKEN","TOMTOM_API_KEY","YOUTUBE_API_KEY"):
    os.environ.pop(name,None)
from server import AppServer,Handler
from engine.operations import seed_demo

if __name__=="__main__":
    Handler.log_message=lambda *args:None
    app=AppServer(("127.0.0.1",0),":memory:")
    seed_demo(app.store)
    print(json.dumps({"port":app.server_port}),flush=True)
    try:app.serve_forever()
    finally:app.server_close()
