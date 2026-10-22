"""Local parquet storage. This is the hand-off point between Python and the warehouse.

Layout under DATA_DIR (default ./data):
  raw/hn_threads.parquet
  raw/hn_posts/<YYYY-MM>.parquet     one file per thread month (rewritten while the month is open)
  raw/bls_jolts.parquet
  extracted/<extractor>.parquet      one file per extractor, so evals can compare them
  quarantine/<dataset>.parquet       rows that failed a contract, with reasons
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
from pydantic import BaseModel

from pulse.contracts import Rejected


def data_dir() -> Path:
    return Path(os.environ.get("PULSE_DATA_DIR", "data"))


def to_frame(rows: Iterable[BaseModel]) -> pd.DataFrame:
    return pd.DataFrame([r.model_dump() for r in rows])


def write(df: pd.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return path


def posts_path(month: date) -> Path:
    return data_dir() / "raw" / "hn_posts" / f"{month:%Y-%m}.parquet"


def existing_post_months() -> set[date]:
    folder = data_dir() / "raw" / "hn_posts"
    if not folder.exists():
        return set()
    months = set()
    for p in folder.glob("*.parquet"):
        if re.fullmatch(r"\d{4}-\d{2}", p.stem):
            y, m = p.stem.split("-")
            months.add(date(int(y), int(m), 1))
    return months


def read_posts() -> pd.DataFrame:
    files = sorted((data_dir() / "raw" / "hn_posts").glob("*.parquet"))
    if not files:
        return pd.DataFrame()
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)


def append_quarantine(rejected: list[Rejected]) -> None:
    """Quarantine is append-only so repeated upstream problems are visible over time."""
    if not rejected:
        return
    df = to_frame(rejected)
    df["quarantined_at"] = datetime.now(UTC)
    for dataset, group in df.groupby("dataset"):
        path = data_dir() / "quarantine" / f"{dataset}.parquet"
        if path.exists():
            group = pd.concat([pd.read_parquet(path), group], ignore_index=True)
        write(group, path)


def extractor_slug(extractor: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", extractor)
