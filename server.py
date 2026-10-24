#!/usr/bin/env python3
"""Local operational API and web workbench. Uses Python standard library only.

Run: py -3 server.py --db output/control_tower.sqlite --demo
For shared deployment provide authenticated reverse proxy and production-grade
database/worker infrastructure. This server refuses non-loopback binding without
CONTROL_TOWER_TOKEN and never executes freight or stock dispatches.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from engine.external import poll_all
from engine.operations import KINDS, Store, demo_records, iso_day, local_today, plan, seed_demo
from engine.replay import replay
from engine.live import LiveEngine


ROOT = Path(__file__).resolve().parent
ASSETS = {"/": ("live.html", "text/html; charset=utf-8"),
          "/live": ("live.html", "text/html; charset=utf-8"),
          "/operations": ("operations.html", "text/html; charset=utf-8"),
          "/live.js": ("live.js", "application/javascript; charset=utf-8"),
          "/live.css": ("live.css", "text/css; charset=utf-8"),
          "/operations.js": ("operations.js", "application/javascript; charset=utf-8"),
          "/operations.css": ("operations.css", "text/css; charset=utf-8"),
          "/operations-v2.js": ("operations-v2.js", "application/javascript; charset=utf-8"),
          "/operations-v2.css": ("operations-v2.css", "text/css; charset=utf-8")}


class AppServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def __init__(self, address, db_path):
        super().__init__(address, Handler)
        self.store = Store(db_path)
        self.lock = threading.RLock()
        self.replay_cache = None
        self.token = os.getenv("CONTROL_TOWER_TOKEN", "")
        self.stop_polling = threading.Event()
        self.live = LiveEngine(db_path)
        self.live.start_worker()

    def start_polling(self):
        if not (os.getenv("TOMTOM_API_KEY") and os.getenv("PULP_ROUTE_BBOX")
                or os.getenv("YOUTUBE_API_KEY") and os.getenv("PULP_YOUTUBE_VIDEO_IDS")):
            return
        def loop():
            while not self.stop_polling.is_set():
                observations = poll_all(local_today())
                with self.lock:
                    for source, observation in observations.items():
                        self.store.record_external(source, observation)
                self.stop_polling.wait(900)
        threading.Thread(target=loop, name="external-poller", daemon=True).start()

    def server_close(self):
        self.stop_polling.set()
        super().server_close()
        self.live.close()
        self.store.close()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"{self.address_string()} - {fmt % args}")

    def _send(self, payload, code=200):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(raw)

    def _authorized(self):
        if not self.server.token:
            return True
        supplied = self.headers.get("Authorization", "")
        import hmac
        return hmac.compare_digest(supplied, "Bearer " + self.server.token)

    def _body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 5_000_000:
            raise ValueError("JSON body must be between 1 byte and 5 MB")
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            raise ValueError("Content-Type must be application/json")
        body = json.loads(self.rfile.read(length))
        if not isinstance(body, dict):
            raise ValueError("JSON body must be an object")
        return body

    def _handle_error(self, exc):
        if isinstance(exc, (ValueError, json.JSONDecodeError)):
            self._send({"error": str(exc)}, 400)
        elif isinstance(exc, KeyError):
            self._send({"error": f"missing field: {exc}"}, 400)
        else:
            self._send({"error": "internal error; inspect server log"}, 500)
            raise exc

    def _live_stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        live = self.server.live
        last = None
        self.connection.settimeout(30)
        try:
            while not live.stop.is_set():
                with live.changed:
                    current = (live.state["run_id"], live.state["revision"])
                    if current == last:
                        live.changed.wait(timeout=15)
                    if live.stop.is_set():
                        break
                    current = (live.state["run_id"], live.state["revision"])
                    snapshot = live.snapshot() if current != last else None
                if snapshot:
                    payload = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
                    self.wfile.write(f"id: {current[0]}:{current[1]}\nevent: snapshot\ndata: {payload}\n\n".encode("utf-8"))
                    last = current
                else:
                    self.wfile.write(b": keep-alive\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
            pass

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ASSETS:
            name, mime = ASSETS[path]
            raw = (ROOT / "web" / name).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'")
            self.end_headers()
            self.wfile.write(raw)
            return
        if not path.startswith("/api/"):
            self._send({"error": "not found"}, 404)
            return
        if not self._authorized():
            self._send({"error": "unauthorized"}, 401)
            return
        try:
            args = parse_qs(urlparse(self.path).query)
            if path == "/api/live/stream":
                self._live_stream()
                return
            if path == "/api/live/state":
                self._send(self.server.live.snapshot())
                return
            if path == "/api/live/events":
                self._send(self.server.live.export_events())
                return
            if path == "/api/live/benchmarks":
                report=ROOT/"data/forecast_benchmark.json"
                result=json.loads(report.read_text(encoding="utf-8")) if report.exists() else {"summary":[],"status":"NOT_RUN"}
                result["current_source"]=bool(result.get("source_sha256")) and all(
                    (ROOT/name).is_file() and hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==sha
                    for name,sha in result.get("source_sha256",{}).items())
                self._send(result)
                return
            with self.server.lock:
                if path == "/api/health":
                    result = {"status": "ok", "date": local_today().isoformat(),
                              "records": {k: len(self.server.store.records(k)) for k in sorted(KINDS)}}
                elif path == "/api/plan":
                    day = iso_day(args["date"][0]) if "date" in args else local_today()
                    result = plan(self.server.store, day)
                elif path == "/api/replay":
                    if self.server.replay_cache is None:
                        self.server.replay_cache = replay()
                    result = self.server.replay_cache
                elif path == "/api/audit":
                    result = self.server.store.audit(100)
                elif path == "/api/records":
                    kind = args.get("kind", [""])[0]
                    result = self.server.store.records(kind)[-2000:]
                elif path == "/api/catalog":
                    result = self.server.store.catalog(local_today())
                elif path == "/api/external":
                    result = self.server.store.external_latest()
                elif path == "/api/process-mining":
                    result = self.server.store.process_mining_summary()
                elif path == "/api/config":
                    result = {"kinds": sorted(KINDS), "token_required": bool(self.server.token),
                              "external_configured": {"road": bool(os.getenv("TOMTOM_API_KEY") and os.getenv("PULP_ROUTE_BBOX")),
                                                      "attention": bool(os.getenv("YOUTUBE_API_KEY") and os.getenv("PULP_YOUTUBE_VIDEO_IDS"))}}
                elif path == "/api/template":
                    kind = args.get("kind", ["order"])[0]
                    if kind not in KINDS:
                        raise ValueError("unknown record kind")
                    result = demo_records(local_today())[kind]
                    if not kind.endswith("_master"):
                        result = result[:2]
                else:
                    self._send({"error": "not found"}, 404)
                    return
            self._send(result)
        except Exception as exc:
            self._handle_error(exc)

    def do_POST(self):
        path = urlparse(self.path).path
        if not self._authorized():
            self._send({"error": "unauthorized"}, 401)
            return
        try:
            body = self._body()
            if path.startswith("/api/live/"):
                live = self.server.live
                if path == "/api/live/control":
                    result = live.control(body)
                elif path == "/api/live/inputs":
                    result = live.inputs(body.get("changes",body),step_if_paused=body.get("step_if_paused",False) if "changes" in body else False,lifecycle=body.get("lifecycle"))
                elif path == "/api/live/inject":
                    result = live.inject(body.get("preset"),step_if_paused=body.get("step_if_paused",False),lifecycle=body.get("lifecycle"))
                elif path == "/api/live/review/open":
                    result = live.begin_review(body)
                elif path == "/api/live/review/close":
                    result = live.end_review(body)
                elif path == "/api/live/decide":
                    result = live.decide(body)
                elif path == "/api/live/compare":
                    result = live.compare(body)
                else:
                    self._send({"error": "not found"}, 404)
                    return
                self._send(result)
                return
            with self.server.lock:
                if path in {"/api/ingest", "/api/validate"}:
                    result = self.server.store.ingest(body["kind"], body["records"], body.get("source", "api"), dry_run=path == "/api/validate")
                elif path == "/api/seed-demo":
                    result = seed_demo(self.server.store, iso_day(body["date"]) if body.get("date") else local_today())
                elif path == "/api/decide":
                    current = plan(self.server.store)
                    action = next((a for a in current["actions"] if a["id"] == body.get("id")
                                   and a["version"] == body.get("version")), None)
                    if not action:
                        self._send({"error": "recommendation changed; reload and review current version"}, 409)
                        return
                    result = self.server.store.decide(action, body["status"], body["actor"], body["role"], body["reason"])
                elif path == "/api/external/refresh":
                    # Network calls may take seconds; only a configured source is queried.
                    result = poll_all(local_today())
                    for source, observation in result.items():
                        result[source] = self.server.store.record_external(source, observation)
                else:
                    self._send({"error": "not found"}, 404)
                    return
            self._send(result)
        except Exception as exc:
            self._handle_error(exc)


def main():
    p = argparse.ArgumentParser(description="Pulp Riot operational control tower")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--db", default="output/control_tower.sqlite")
    p.add_argument("--demo", action="store_true", help="seed an empty database with labelled synthetic case records")
    args = p.parse_args()
    if args.host not in {"127.0.0.1", "localhost", "::1"} and not os.getenv("CONTROL_TOWER_TOKEN"):
        p.error("non-loopback binding requires CONTROL_TOWER_TOKEN")
    path = Path(args.db)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    app = AppServer((args.host, args.port), path)
    if args.demo:
        with app.lock:
            seed_demo(app.store)
    app.start_polling()
    print(f"Pulp Riot control tower: http://{args.host}:{app.server_port}", flush=True)
    print(f"Database: {path} | sample data: {'enabled' if args.demo else 'unchanged'}", flush=True)
    try:
        app.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.server_close()


if __name__ == "__main__":
    main()
