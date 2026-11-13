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


@pytest.mark.usefixtures("warehouse_env")
def test_wake_fails_fast_when_the_workspace_is_blocked() -> None:
    """Databricks' gatekeeper blocks inactive workspaces; retrying for 10 minutes can't help."""
    blocked = {
        "error_code": "BAD_REQUEST",
        "details": [
            {
                "reason": "DENY_NEW_AND_EXISTING_RESOURCES",
                "domain": "resource-gatekeeper",
                "metadata": {"denyReason": "INACTIVE"},
            }
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(400, json=blocked)
        return httpx.Response(200, json={"state": "STOPPED"})

    client = httpx.Client(base_url="https://dbx.test", transport=httpx.MockTransport(handler))
    waits: list[float] = []
    with pytest.raises(warehouse.WarehouseUnavailable, match=r"INACTIVE.*Log in"):
        warehouse.wake(client, log=lambda _: None, sleep=waits.append)
    assert waits == []


def test_fallback_switches_the_job_to_duckdb(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Databricks blocked: the step passes with a warning and later steps use DuckDB."""
    from typer.testing import CliRunner

    from pulse.cli import app

    def blocked(**_: object) -> None:
        raise warehouse.WarehouseUnavailable("blocked (INACTIVE)")

    monkeypatch.setattr(warehouse, "wake", blocked)
    data = tmp_path / "data"  # not created: a fresh CI runner has no data/ folder yet
    monkeypatch.setenv("PULSE_DATA_DIR", str(data))
    github_env = tmp_path / "github_env"
    monkeypatch.setenv("GITHUB_ENV", str(github_env))

    result = CliRunner().invoke(app, ["wake-warehouse", "--fallback"])

    assert result.exit_code == 0
    assert "::warning title=Built on DuckDB" in result.output
    lines = github_env.read_text().splitlines()
    assert "PULSE_ENGINE=duckdb" in lines and "DBT_TARGET=duckdb" in lines
    assert f"PULSE_DUCKDB_PATH={data.resolve() / 'workspace.duckdb'}" in lines
    assert data.is_dir()


def test_without_fallback_an_unavailable_warehouse_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from pulse.cli import app

    def blocked(**_: object) -> None:
        raise warehouse.WarehouseUnavailable("blocked (INACTIVE)")

    monkeypatch.setattr(warehouse, "wake", blocked)
    result = CliRunner().invoke(app, ["wake-warehouse"])
    assert result.exit_code == 1
    assert "::error" in result.output


def test_duckdb_load_matches_the_databricks_table_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same table names and extra columns (_rescued_data, _loaded_at) as read_files gives."""
    import duckdb
    import pandas as pd

    monkeypatch.setenv("PULSE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PULSE_ENGINE", "duckdb")
    monkeypatch.delenv("PULSE_DUCKDB_PATH", raising=False)
    posts = tmp_path / "raw" / "hn_posts"
    posts.mkdir(parents=True)
    pd.DataFrame({"post_id": [1, 2]}).to_parquet(posts / "2026-01.parquet")
    pd.DataFrame({"post_id": [3]}).to_parquet(posts / "2026-02.parquet")

    counts = warehouse.load_raw("pulse_raw", log=lambda _: None)

    assert counts == {"hn_posts": 3}
    with duckdb.connect(str(tmp_path / "workspace.duckdb")) as conn:
        cols = [r[0] for r in conn.execute("DESCRIBE workspace.pulse_raw.hn_posts").fetchall()]
    assert cols == ["post_id", "_rescued_data", "_loaded_at"]
