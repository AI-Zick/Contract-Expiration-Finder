"""Local web server for the dashboard.

Standard library only -- no Flask, no build step. `pdcontracts serve` opens the
pipeline in a browser and rebuilds it from the database on every request, so a
collection run in another terminal shows up on refresh.

Binds to localhost by default. Contract pipelines are commercially sensitive;
exposing one on 0.0.0.0 should be a deliberate act, not a default.
"""

from __future__ import annotations

import datetime as _dt
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, List, Optional, Tuple
from urllib.parse import urlparse

from .report import Opportunity, to_csv
from .web import build_payload, render_document

# Builder returns (opportunities, focus_categories, today).
Builder = Callable[[], Tuple[List[Opportunity], List[str], _dt.date]]


def make_handler(builder: Builder, quiet: bool = False):
    class Handler(BaseHTTPRequestHandler):
        server_version = "pdcontracts"

        def log_message(self, fmt, *args):  # noqa: A003
            if not quiet:
                print(f"  {self.command} {self.path} -> {args[1] if len(args) > 1 else ''}")

        def _send(self, body: str, content_type: str, status: int = 200):
            raw = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):  # noqa: N802
            path = urlparse(self.path).path
            try:
                if path in ("/", "/index.html"):
                    opps, focus, today = builder()
                    self._send(
                        render_document(build_payload(opps, focus, today)), "text/html"
                    )
                elif path == "/api/opportunities.json":
                    opps, focus, today = builder()
                    self._send(
                        json.dumps(build_payload(opps, focus, today), default=str),
                        "application/json",
                    )
                elif path == "/export.csv":
                    opps, _, _ = builder()
                    self._send(to_csv(opps), "text/csv")
                else:
                    self._send("Not found", "text/plain", 404)
            except Exception as exc:  # noqa: BLE001 - a dead page beats a dead server
                self._send(f"Server error: {exc}", "text/plain", 500)

    return Handler


def serve(
    builder: Builder,
    host: str = "127.0.0.1",
    port: int = 8000,
    open_browser: bool = True,
    quiet: bool = False,
) -> None:
    httpd = ThreadingHTTPServer((host, port), make_handler(builder, quiet))
    url = f"http://{host}:{port}/"
    count = len(builder()[0])
    print(f"pdcontracts dashboard: {url}")
    print(f"  {count} opportunities  ·  CSV at {url}export.csv  ·  Ctrl-C to stop")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()
