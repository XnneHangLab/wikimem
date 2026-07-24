"""HTTP + JSON serve: a thin, read-only shell over the Python API (ADR-0004).

For **out-of-process** consumers — a memory browser, another frontend — that
want the data over the wire rather than a Python import. Endpoints mirror API
methods 1:1; the shell only routes, converts params, and JSON-encodes — **no
business logic** (no retrieval rules, no fusion defaults), so a serve response
can never diverge from the equivalent API call.

Transport is plain HTTP + JSON on stdlib :mod:`http.server` — zero dependencies,
same as the CLI; no framework, no custom protocol.

Security posture (ADR-0004 §3): bound to ``127.0.0.1`` with **no auth**, for
*local* consumers only. CORS is **off by default** (same-origin only) so a
random web page cannot read your memory via a ``fetch`` to localhost; pass
``cors=`` your frontend's exact origin to opt in. Never expose this on a public
interface.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast
from urllib.parse import unquote, urlparse

from .store import MemoryStore


class _NotFound(Exception):
    """Route or resource missing → 404 (distinct from a 400 bad request)."""


def route(store: MemoryStore, path: str) -> Any:
    """Map a GET path to one API call and return its JSON-able result.

    Routing + param conversion only — the shell rule (ADR-0004 §2): call the API
    and hand back what it returns, nothing more. A ``ValueError`` from the API
    (e.g. a bad date) surfaces as 400; :class:`_NotFound` as 404.
    """
    parts = [unquote(p) for p in path.split("/") if p]

    if parts == ["version"]:
        from . import __version__

        return {"name": "wikimem", "version": __version__}

    if parts == ["diary", "dates"]:
        return store.diary.dates()

    if len(parts) == 3 and parts[0] == "diary" and parts[1] == "day":
        return [asdict(e) for e in store.diary.day(parts[2])]

    raise _NotFound(f"no such endpoint: /{'/'.join(parts)}")


class _Server(ThreadingHTTPServer):
    """An HTTP server carrying the store and CORS policy for its handlers."""

    def __init__(self, address: tuple[str, int], store: MemoryStore, cors: str | None) -> None:
        super().__init__(address, _Handler)
        self.store = store
        self.cors = cors


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    @property
    def _srv(self) -> _Server:
        return cast("_Server", self.server)

    def do_GET(self) -> None:
        try:
            payload = route(self._srv.store, urlparse(self.path).path)
        except _NotFound as exc:
            self._json(404, {"error": str(exc)})
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
        else:
            self._json(200, payload)

    def do_OPTIONS(self) -> None:  # CORS preflight
        self._json(204, None)

    def _json(self, status: int, payload: Any) -> None:
        body = b"" if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if self._srv.cors:
            self.send_header("Access-Control-Allow-Origin", self._srv.cors)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        pass  # quiet by default — the host owns logging


def build_server(
    store: MemoryStore,
    *,
    host: str = "127.0.0.1",
    port: int = 8787,
    cors: str | None = None,
) -> ThreadingHTTPServer:
    """Build (but do not start) the server. ``serve()`` builds and runs it;
    tests build it on ``port=0`` and run ``serve_forever()`` in a thread."""
    return _Server((host, port), store, cors)


def serve(
    store: MemoryStore,
    *,
    host: str = "127.0.0.1",
    port: int = 8787,
    cors: str | None = None,
) -> None:
    """Serve ``store`` over read-only HTTP + JSON until interrupted (blocking).

    ``cors`` is the exact ``Access-Control-Allow-Origin`` to send (e.g.
    ``"http://localhost:5173"``) for a cross-origin frontend, or ``None``
    (default) to send none. Keep ``host`` at ``127.0.0.1`` unless you understand
    the exposure — there is no authentication.
    """
    httpd = build_server(store, host=host, port=port, cors=cors)
    bound_host, bound_port = httpd.server_address[:2]
    print(f"wikimem serve → http://{bound_host!s}:{bound_port} (read-only; Ctrl-C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
