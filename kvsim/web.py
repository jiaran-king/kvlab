"""Bounded loopback-only local UI. One CPU simulation worker at a time."""

import copy
import json
import multiprocessing
import threading
import time
from urllib.parse import parse_qs
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from .engine import simulate
from .inputs import compile_scenario


def calculate(body, connection):
    try:
        import resource
        for limit, budget in ((resource.RLIMIT_CPU, 85),):
            _, hard = resource.getrlimit(limit)
            effective = budget if hard == resource.RLIM_INFINITY else min(budget, hard)
            resource.setrlimit(limit, (effective, hard))
        scenario = compile_scenario(body.get("scenario", body.get("settings", {})))
        points = body.get("capacities")
        if points is not None and (not isinstance(points, list) or not 1 <= len(points) <= 8):
            raise ValueError("Use 1..8 capacity points")
        results = []
        for point in points or [None]:
            case = copy.deepcopy(scenario)
            if point is not None:
                case["config"].pop("kv_bytes", None)
                case["config"]["kv_gib"] = float(point)
            results.append(simulate(case))
        connection.send({"results": results})
    except MemoryError as exc:
        connection.send({"error": "CPU worker memory budget reached; reduce the scenario", "status": "resource_limit"})
    except NotImplementedError as exc:
        connection.send({"error": str(exc), "status": "unsupported"})
    except (ValueError, KeyError, TypeError, OverflowError) as exc:
        connection.send({"error": str(exc), "status": "invalid_input"})
    except Exception as exc:
        connection.send({"error": f"Internal simulation error: {type(exc).__name__}: {exc}", "status": "internal_error"})
    finally:
        connection.close()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, data, mime="application/json", code=200):
        if not isinstance(data, bytes):
            data = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.reply(Path(__file__).with_name("KVLab.html").read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/health":
            self.reply({"status": "ready", "owner": "kvsim", "inference": False,
                        "expires_at": self.server.expires_at})
        else:
            self.reply({"error": "not found"}, code=404)

    def do_POST(self):
        if self.path == "/api/export":
            size = int(self.headers.get("Content-Length", 0))
            if not 0 < size <= 48 * 1024 * 1024:
                self.reply({"error": "Export exceeds 48 MiB"}, code=413)
                return
            fields = parse_qs(self.rfile.read(size).decode())
            name = fields.get("name", [""])[0]
            if name not in ("scenario.json", "result.json", "requests.csv", "capacity.svg"):
                self.reply({"error": "Unknown export type"}, code=400)
                return
            data = fields.get("payload", [""])[0].encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", f'attachment; filename="{name}"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if self.path != "/api/simulate":
            self.reply({"error": "not found"}, code=404)
            return
        # JSON-only same-origin local API: no filesystem paths accepted.
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            self.reply({"error": "JSON required"}, code=415)
            return
        size = int(self.headers.get("Content-Length", 0))
        if not 0 < size <= 24 * 1024 * 1024:
            self.reply({"error": "Input must be between 1 byte and 24 MiB"}, code=413)
            return
        try:
            body = json.loads(self.rfile.read(size))
        except ValueError:
            self.reply({"error": "Invalid JSON", "status": "invalid_input"}, code=400)
            return
        context = multiprocessing.get_context("spawn")
        receiving, sending = context.Pipe(duplex=False)
        worker = context.Process(target=calculate, args=(body, sending))
        worker.start()
        sending.close()
        try:
            if receiving.poll(90):
                result = receiving.recv()
            else:
                result = {"error": "CPU run exceeded 90 seconds; reduce the scenario", "status": "resource_limit"}
        except EOFError:
            result = {"error": "CPU worker exited before returning a result", "status": "internal_error"}
        finally:
            receiving.close()
            worker.join(timeout=2)
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=2)
        self.reply(result)


def serve(port=8765, duration=7200):
    if not 1 <= duration <= 43200:
        raise ValueError("Service duration must be 1..43200 seconds")
    server = HTTPServer(("127.0.0.1", port), Handler)
    server.expires_at = time.time() + duration
    timer = threading.Timer(duration, server.shutdown)
    timer.daemon = True
    timer.start()
    print(f"KVSim: http://127.0.0.1:{port} · CPU only · expires in {duration}s · Ctrl-C stops", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        timer.cancel()
        server.server_close()
