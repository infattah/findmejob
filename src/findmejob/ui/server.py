"""Local web UI: a second client of the same persistent main agent.

Stdlib only. Binds to 127.0.0.1 by default. No auth - it is meant for
localhost use by one person. Serves the chat interface, tracker, pending
questions, evidence files and the event feed, all backed by the same
SQLite database the CLI uses.
"""
from __future__ import annotations

import json
import mimetypes
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from ..agent.main_agent import MainAgent
from ..config import Config
from ..tracker import Tracker


class State:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.tracker = Tracker(cfg.db_path)
        self.agent = MainAgent(cfg, self.tracker)


def make_handler(state: State):
    static_dir = Path(__file__).parent / "static"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # quiet
            pass

        def _send(self, code: int, body: bytes, ctype: str = "text/html; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200):
            self._send(code, json.dumps(obj).encode(), "application/json")

        def do_GET(self):
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                self._send(200, (static_dir / "index.html").read_bytes())
            elif path == "/api/state":
                from ..runtimes import select_runtime
                self._json({
                    "runtime": select_runtime(state.cfg.llm.get("provider", "")).name,
                    "counts": state.tracker.counts(),
                    "jobs": state.tracker.list_jobs()[:100],
                    "pending": [dict(id=r["id"], job_id=r["job_id"], question=r["question"],
                                     asked=r["asked"]) for r in state.tracker.pending()],
                    "events": [dict(ts=r["ts"], kind=r["kind"], detail=r["detail"], job_id=r["job_id"])
                               for r in state.tracker.events(40)],
                    "tasks": [dict(id=r["id"], kind=r["kind"], status=r["status"],
                                   result=r["result"], attempts=r["attempts"])
                              for r in state.tracker.list_tasks(limit=20)],
                    "messages": [dict(ts=r["ts"], role=r["role"], text=r["text"])
                                 for r in reversed(state.tracker.conversation(100))],
                    "files": self._files(),
                })
            elif path.startswith("/files/"):
                self._download(path[len("/files/"):])
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self):
            path = urlparse(self.path).path
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b"{}"
            try:
                data = json.loads(body or b"{}")
            except json.JSONDecodeError:
                return self._json({"error": "bad json"}, 400)
            if path == "/api/chat":
                reply = state.agent.handle(str(data.get("message", "")))
                self._json({"reply": reply, "ts": time.time()})
            elif path == "/api/tick":
                self._json({"summaries": state.agent.tick()})
            else:
                self._send(404, b"not found", "text/plain")

        def _files(self):
            out = state.cfg.output_dir
            files = []
            if out.exists():
                for p in sorted(out.rglob("*")):
                    if p.is_file():
                        rel = p.relative_to(out)
                        files.append({"name": str(rel), "size": p.stat().st_size,
                                      "url": "/files/" + str(rel)})
            return files[-200:]

        def _download(self, rel: str):
            out = state.cfg.output_dir.resolve()
            target = (out / rel).resolve()
            if not str(target).startswith(str(out)) or not target.is_file():
                return self._send(404, b"not found", "text/plain")
            ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            self._send(200, target.read_bytes(), ctype)

    return Handler


def serve(cfg: Config, host: str = "127.0.0.1", port: int = 8787) -> None:
    state = State(cfg)
    server = ThreadingHTTPServer((host, port), make_handler(state))
    print(f"findmejob UI on http://{host}:{port}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        state.tracker.close()
