"""Retries for flaky APIs, a refresh that survives a BLS outage, and waking the warehouse.

Found in production: BLS returned 503 for hours and the whole daily refresh failed; later,
the Databricks warehouse refused to auto-start on connect for three days running.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import httpx
import pytest

from pulse import http, pipeline, warehouse
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


def _warehouse(states: list[str], start_status: int = 200) -> tuple[httpx.Client, list[str]]:
    """A warehouse API reporting `states` in turn (the last repeats). Returns (client, starts)."""
    seen = 0
    starts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen
        if request.method == "POST":
            starts.append(request.url.path)
            return httpx.Response(start_status, text="Cannot create the resource")
        state = states[min(seen, len(states) - 1)]
        seen += 1
        return httpx.Response(200, json={"state": state})

    return httpx.Client(base_url="https://dbx.test", transport=httpx.MockTransport(handler)), starts


@pytest.fixture
def warehouse_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABRICKS_HTTP_PATH", "/sql/1.0/warehouses/abc123")


@pytest.mark.usefixtures("warehouse_env")
def test_wake_starts_a_stopped_warehouse_and_waits() -> None:
    client, starts = _warehouse(["STOPPED", "STARTING", "RUNNING"])
    waits: list[float] = []
    warehouse.wake(client, poll=15, log=lambda _: None, sleep=waits.append, clock=lambda: 0)
    assert starts == ["/api/2.0/sql/warehouses/abc123/start"]
    assert waits == [15, 15]


@pytest.mark.usefixtures("warehouse_env")
def test_wake_does_nothing_when_already_running() -> None:
    client, starts = _warehouse(["RUNNING"])
    warehouse.wake(client, log=lambda _: None, sleep=lambda _: None)
    assert starts == []


@pytest.mark.usefixtures("warehouse_env")
def test_wake_gives_up_with_the_refusal_reason() -> None:
    client, starts = _warehouse(["STOPPED"], start_status=400)
    now = iter(range(0, 10_000, 15))
    with pytest.raises(warehouse.WarehouseUnavailable, match="Cannot create the resource"):
        warehouse.wake(
            client,
            timeout=60,
            poll=15,
            log=lambda _: None,
            sleep=lambda _: None,
            clock=lambda: next(now),
        )
    assert len(starts) == 4  # tried again on every poll until the deadline
