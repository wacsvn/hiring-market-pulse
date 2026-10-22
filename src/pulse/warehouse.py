"""Load local raw parquet into Databricks.

Files go to a Unity Catalog volume (<catalog>.<raw_schema>.landing) via the Files API,
then each dataset becomes a Delta table with CREATE OR REPLACE ... read_files(). Raw
tables are a full snapshot of the parquet, so loads are idempotent and easy to rerun.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from pulse import load

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
    http = httpx.Client(
        base_url=f"https://{host()}",
        headers={"Authorization": f"Bearer {_env('DATABRICKS_TOKEN')}"},
        timeout=120,
    )
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


def drop_schemas(*schemas: str) -> None:
    with connect() as conn, conn.cursor() as cur:
        for s in schemas:
            cur.execute(f"DROP SCHEMA IF EXISTS {CATALOG}.{_check_ident(s)} CASCADE")
