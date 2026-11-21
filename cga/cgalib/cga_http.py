"""Shared HTTP + HTML fragment helpers for the Python cga* programs.

Every cga* server serves small, read-only HTML *fragments* (not full pages);
the composite page in cga/web/ fetches them by URL and drops them into the
layout grid. Because the composite page and each cga* server live on different
ports, every response carries permissive CORS headers.

This module is intentionally dependency-free (standard library only), matching
the rest of the cga skeleton.
"""

from __future__ import annotations

import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Dict


def esc(text: object) -> str:
    """HTML-escape a value for safe inclusion in a fragment."""
    return html.escape(str(text), quote=True)


def hover(text: str, tip: str) -> str:
    """Render text with a hover tooltip (title=), used throughout the cga UI."""
    return f'<span class="cga-hover" title="{esc(tip)}">{esc(text)}</span>'


def fragment(component: str, title: str, body_html: str, tip: str = "") -> str:
    """Wrap body_html in the standard cga fragment envelope.

    The composite page's CSS styles `.cga-frag` / `.cga-frag-title`, so all
    fragments look uniform regardless of which cga* server produced them.
    """
    title_html = hover(title, tip) if tip else esc(title)
    return (
        f'<div class="cga-frag" data-component="{esc(component)}">'
        f'<div class="cga-frag-title">{title_html}</div>'
        f'<div class="cga-frag-body">{body_html}</div>'
        f"</div>"
    )


def kv_table(rows: list[tuple[str, str]]) -> str:
    """Render a simple key/value table for overview/detail fragments."""
    trs = "".join(
        f'<tr><th>{esc(k)}</th><td>{esc(v)}</td></tr>' for k, v in rows
    )
    return f'<table class="cga-kv">{trs}</table>'


def serve(component: str, port: int, routes: Dict[str, Callable[[], str]]) -> None:
    """Start a threaded HTTP server exposing the given fragment routes.

    `routes` maps a path (e.g. "/overview") to a zero-arg function returning an
    HTML fragment string. A "/healthz" route is always added for the launcher's
    readiness probe, and "/" returns a small JSON index of available routes.
    """

    def handler_for(path: str):
        return routes.get(path)

    class Handler(BaseHTTPRequestHandler):
        server_version = f"cga-{component}"

        def log_message(self, *_args):  # keep the skeleton quiet
            pass

        def _send(self, code: int, body: str, ctype: str) -> None:
            payload = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):  # noqa: N802 (stdlib naming)
            path = self.path.split("?", 1)[0].rstrip("/") or "/"
            if path == "/healthz":
                self._send(200, "ok", "text/plain; charset=utf-8")
                return
            if path == "/":
                index = {
                    "component": component,
                    "routes": sorted(routes.keys()),
                }
                self._send(200, json.dumps(index), "application/json")
                return
            fn = handler_for(path)
            if fn is None:
                self._send(
                    404,
                    fragment(component, "not found", esc(f"no route {path}")),
                    "text/html; charset=utf-8",
                )
                return
            self._send(200, fn(), "text/html; charset=utf-8")

    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"{component}: serving fragments on http://127.0.0.1:{port} "
          f"(routes: {', '.join(sorted(routes.keys()))})", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
