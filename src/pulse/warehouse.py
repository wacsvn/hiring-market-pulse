"""Load local raw parquet into Databricks.

Files go to a Unity Catalog volume (<catalog>.<raw_schema>.landing) via the Files API,
then each dataset becomes a Delta table with CREATE OR REPLACE ... read_files(). Raw
tables are a full snapshot of the parquet, so loads are idempotent and easy to rerun.
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from pulse import load
from pulse.http import request

CATALOG = "workspace"
# dataset -> path under DATA_DIR (file or directory of parquet files)
DATASETS = {
    "hn_threads": "raw/hn_threads.parquet",
    "hn_posts": "raw/hn_posts",
    "bls_jolts": "raw/bls_jolts.parquet",
    "extractions_rules": "extracted/rules.parquet",
    "quarantine": "quarantine",
}
_IDENT = re.compile(r"^[a-z][a-z0-9_]*$")


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set")
    return value


def host() -> str:
    return _env("DATABRICKS_HOST").removeprefix("https://").rstrip("/")


def api() -> httpx.Client:
    return httpx.Client(
        base_url=f"https://{host()}",
        headers={"Authorization": f"Bearer {_env('DATABRICKS_TOKEN')}"},
        timeout=120,
    )


class WarehouseUnavailable(RuntimeError):
    """The SQL warehouse did not reach RUNNING in time."""


def wake(
    http: httpx.Client | None = None,
    timeout: float = 600,
    poll: float = 15,
    log: Callable[[str], None] = print,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Start the SQL warehouse through the API and wait until it is RUNNING.

    Connecting starts a stopped warehouse too, but on 2026-10-28..30 that start was refused
    ("Cannot create the resource") on every run, while an explicit start went through at once.
    """
    http = http or api()
    path = f"/api/2.0/sql/warehouses/{_env('DATABRICKS_HTTP_PATH').rstrip('/').rsplit('/', 1)[-1]}"
    deadline = clock() + timeout
    last_error = ""
    while True:
        state = request(http, "GET", path).json()["state"]
        if state == "RUNNING":
            log("warehouse is running")
            return
        if state in {"DELETING", "DELETED"}:
            raise WarehouseUnavailable(f"warehouse is {state}; check DATABRICKS_HTTP_PATH")
        if state == "STOPPED":
            log("warehouse is stopped; starting it")
            try:
                request(http, "POST", f"{path}/start")
            except httpx.HTTPStatusError as e:
                last_error = e.response.text[:300]
                log(f"start refused: {last_error}")
        if clock() >= deadline:
            detail = f" (last error: {last_error})" if last_error else ""
            raise WarehouseUnavailable(f"still {state} after {timeout:.0f}s{detail}")
        sleep(poll)


def connect() -> Any:
    from databricks import sql  # imported lazily: only the warehouse extra installs it

    return sql.connect(
        server_hostname=host(),
        http_path=_env("DATABRICKS_HTTP_PATH"),
        access_token=_env("DATABRICKS_TOKEN"),
        # Fail within minutes instead of the connector's ~15 min default retry window.
        _retry_stop_after_attempts_count=3,
        _retry_stop_after_attempts_duration=120,
        _socket_timeout=120,
    )


def _check_ident(schema: str) -> str:
    if not _IDENT.match(schema):
        raise ValueError(f"unsafe schema name: {schema!r}")
    return schema


def _upload(http: httpx.Client, local: Path, volume_path: str) -> None:
    with local.open("rb") as f:
        resp = http.put(
            f"/api/2.0/fs/files{volume_path}", params={"overwrite": "true"}, content=f.read()
        )
    resp.raise_for_status()


def _delete_stale(http: httpx.Client, folder: str, keep: set[str]) -> None:
    """Remove volume files that no longer exist locally, so the raw table mirrors disk."""
    resp = http.get(f"/api/2.0/fs/directories{folder}")
    resp.raise_for_status()
    for entry in resp.json().get("contents", []):
        if not entry.get("is_directory") and entry["name"] not in keep:
            http.delete(f"/api/2.0/fs/files{entry['path']}").raise_for_status()


def load_raw(raw_schema: str, log: Callable[[str], None] = print) -> dict[str, int]:
    """Upload every dataset present on disk and (re)create its raw table. Returns row counts."""
    schema = _check_ident(raw_schema)
    volume = f"/Volumes/{CATALOG}/{schema}/landing"
    http = api()
    counts: dict[str, int] = {}
    with connect() as conn, conn.cursor() as cur:
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{schema}")
        cur.execute(f"CREATE VOLUME IF NOT EXISTS {CATALOG}.{schema}.landing")
        for dataset, rel in DATASETS.items():
            src = load.data_dir() / rel
            files = sorted(src.glob("*.parquet")) if src.is_dir() else [src]
            files = [f for f in files if f.exists()]
            if not files:
                log(f"skip {dataset}: nothing on disk")
                continue
            for f in files:
                _upload(http, f, f"{volume}/{dataset}/{f.name}")
            _delete_stale(http, f"{volume}/{dataset}", keep={f.name for f in files})
            table = f"{CATALOG}.{schema}.{dataset}"
            cur.execute(
                f"CREATE OR REPLACE TABLE {table} AS "
                f"SELECT *, current_timestamp() AS _loaded_at "
                f"FROM read_files('{volume}/{dataset}/', format => 'parquet')"
            )
            cur.execute(f"SELECT count(*) FROM {table}")
            counts[dataset] = int(cur.fetchone()[0])
            log(f"loaded {table}: {counts[dataset]} rows from {len(files)} file(s)")
    return counts


MARTS = [
    "mart_monthly_summary",
    "mart_role_mix",
    "mart_tech_trends",
    "mart_salary_bands",
    "mart_hn_vs_jolts",
    "stg_quarantine",
]


def export_marts(schema: str, out_dir: Path, log: Callable[[str], None] = print) -> None:
    """Write each mart to <out_dir>/<mart>.parquet for the dashboard."""
    import pandas as pd

    _check_ident(schema)
    out_dir.mkdir(parents=True, exist_ok=True)
    with connect() as conn, conn.cursor() as cur:
        for mart in MARTS:
            cur.execute(f"SELECT * FROM {CATALOG}.{schema}.{mart}")
            cols = [d[0] for d in cur.description]
            df = pd.DataFrame([tuple(r) for r in cur.fetchall()], columns=cols)
            # Databricks returns DECIMAL as Python Decimal; the app wants plain floats.
            for c in df.columns:
                if df[c].map(lambda v: type(v).__name__ == "Decimal").any():
                    df[c] = df[c].astype(float)
            load.write(df, out_dir / f"{mart}.parquet")
            log(f"exported {mart}: {len(df)} rows")


def drop_schemas(*schemas: str) -> None:
    with connect() as conn, conn.cursor() as cur:
        for s in schemas:
            cur.execute(f"DROP SCHEMA IF EXISTS {CATALOG}.{_check_ident(s)} CASCADE")
