"""HTTP + JSON serve — the read-only shell over the API (ADR-0004, serve Phase 1).

Starts a real server on an ephemeral port in a background thread and drives it
over HTTP, so routing, JSON encoding, status codes, and CORS are all exercised
end-to-end (not just the ``route`` function).
"""

import json
import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from typing import Any
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from wikimem import MemoryStore
from wikimem.serve import build_server


def _run(httpd: ThreadingHTTPServer) -> threading.Thread:
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return thread


def _get(port: int, path: str) -> tuple[int, Any, dict[str, str]]:
    with urlopen(f"http://127.0.0.1:{port}{path}") as resp:
        body = json.loads(resp.read().decode("utf-8"))
        return resp.status, body, dict(resp.headers)


@pytest.fixture()
def port(tmp_path) -> Iterator[int]:
    store = MemoryStore(tmp_path / "memory")
    store.diary.append(
        "去了海边。[[daily_life:beach]]",
        date="2026-07-20",
        time="14:30",
        owner="user:xnne",
        source_conv="conv_1",
    )
    store.diary.append("睡前担心新工作。", date="2026-07-21", time="22:10")
    httpd = build_server(store, port=0)
    thread = _run(httpd)
    try:
        yield httpd.server_address[1]
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)


def test_version(port: int):
    status, body, _ = _get(port, "/version")
    assert status == 200
    assert body["name"] == "wikimem" and body["version"]


def test_diary_dates(port: int):
    _, body, _ = _get(port, "/diary/dates")
    assert body == ["2026-07-20", "2026-07-21"]


def test_diary_day(port: int):
    _, body, _ = _get(port, "/diary/day/2026-07-20")
    assert len(body) == 1
    entry = body[0]
    assert entry["date"] == "2026-07-20"
    assert entry["time"] == "14:30"
    assert entry["content"].startswith("去了海边")
    assert entry["owner"] == "user:xnne"
    assert entry["ts"].endswith("+00:00")


def test_unknown_endpoint_is_404(port: int):
    with pytest.raises(HTTPError) as exc:
        _get(port, "/nope")
    assert exc.value.code == 404


def test_bad_date_is_400(port: int):
    with pytest.raises(HTTPError) as exc:
        _get(port, "/diary/day/not-a-date")
    assert exc.value.code == 400


def test_cors_is_off_by_default(port: int):
    _, _, headers = _get(port, "/version")
    assert "Access-Control-Allow-Origin" not in headers


def test_cors_opt_in(tmp_path):
    httpd = build_server(MemoryStore(tmp_path / "memory"), port=0, cors="http://localhost:5173")
    thread = _run(httpd)
    try:
        _, _, headers = _get(httpd.server_address[1], "/diary/dates")
        assert headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)
