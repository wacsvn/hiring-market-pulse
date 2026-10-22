"""Retries for flaky APIs, and a refresh that survives a BLS outage.

Found in production: BLS returned 503 for hours and the whole daily refresh failed.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import httpx
import pytest

from pulse import http, pipeline
from pulse.sources.bls_jolts import BLSClient
from pulse.sources.hn_algolia import BASE_URL, HNClient
from tests.conftest import hn_transport


def _flaky(statuses: list[int]) -> tuple[httpx.Client, list[int]]:
    """A client whose responses follow `statuses`, then 200 forever. Returns (client, calls)."""
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        status = statuses[len(calls)] if len(calls) < len(statuses) else 200
        calls.append(status)
        return httpx.Response(status, json={"ok": status == 200})

    return httpx.Client(base_url="https://api.test", transport=httpx.MockTransport(handler)), calls


def test_retries_temporary_errors_with_backoff() -> None:
    client, calls = _flaky([503, 502])
    waits: list[float] = []
    resp = http.request(client, "GET", "/x", base_delay=2.0, sleep=waits.append)
    assert resp.status_code == 200
    assert calls == [503, 502, 200]
    assert waits == [2.0, 4.0]


def test_gives_up_after_the_last_attempt() -> None:
    client, calls = _flaky([503] * 10)
    with pytest.raises(httpx.HTTPStatusError, match="503"):
        http.request(client, "GET", "/x", attempts=3, sleep=lambda _: None)
    assert len(calls) == 3


def test_does_not_retry_a_bad_request() -> None:
    client, calls = _flaky([404])
    with pytest.raises(httpx.HTTPStatusError, match="404"):
        http.request(client, "GET", "/x", sleep=lambda _: None)
    assert calls == [404]


def test_retries_connection_errors() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(200)

    client = httpx.Client(base_url="https://api.test", transport=httpx.MockTransport(handler))
    assert http.request(client, "GET", "/x", sleep=lambda _: None).status_code == 200
    assert attempts == 3


def test_refresh_continues_when_bls_is_down(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HN data is still refreshed; the last JOLTS file is left exactly as it was."""
    monkeypatch.setenv("PULSE_DATA_DIR", str(tmp_path))
    previous = tmp_path / "raw" / "bls_jolts.parquet"
    previous.parent.mkdir(parents=True)
    previous.write_bytes(b"last good JOLTS data")

    down = httpx.MockTransport(lambda request: httpx.Response(503, text="Service Unavailable"))
    bls = BLSClient(httpx.Client(base_url="https://api.bls.gov", transport=down), "", 0.0)
    hn = HNClient(httpx.Client(base_url=BASE_URL, transport=hn_transport()), 0.0)
    logs: list[str] = []

    summary = pipeline.ingest(hn, bls, date(2000, 1, 1), date(2000, 1, 1), log=logs.append)

    assert summary.jolts_error is not None and "503" in summary.jolts_error
    assert summary.posts > 0
    assert any(p.suffix == ".parquet" for p in (tmp_path / "raw" / "hn_posts").iterdir())
    assert previous.read_bytes() == b"last good JOLTS data"
    assert any("BLS JOLTS unavailable" in line for line in logs)
