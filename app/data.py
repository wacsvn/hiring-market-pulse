"""Loads the exported marts. Source: PULSE_MARTS_DIR (local) or PULSE_MARTS_URL (release)."""

from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

MARTS = [
    "mart_monthly_summary",
    "mart_role_mix",
    "mart_tech_trends",
    "mart_salary_bands",
    "mart_hn_vs_jolts",
    "stg_quarantine",
]
DATE_COLUMNS = {"thread_month", "month"}


@dataclass
class Marts:
    frames: dict[str, pd.DataFrame]
    metadata: dict[str, Any] = field(default_factory=dict)
    source: str = ""

    def __getitem__(self, name: str) -> pd.DataFrame:
        return self.frames[name]

    @property
    def is_empty(self) -> bool:
        return self.frames["mart_monthly_summary"].empty


def _source() -> str:
    url = os.environ.get("PULSE_MARTS_URL")
    if url:
        return url.rstrip("/")
    return os.environ.get("PULSE_MARTS_DIR", "data/marts")


def _read(source: str, name: str) -> pd.DataFrame:
    path = f"{source}/{name}.parquet"
    if not source.startswith("http") and not Path(path).exists():
        return pd.DataFrame()
    df = pd.read_parquet(path)
    for col in DATE_COLUMNS & set(df.columns):
        df[col] = pd.to_datetime(df[col])
    return df


def _read_metadata(source: str) -> dict[str, Any]:
    try:
        if source.startswith("http"):
            with urllib.request.urlopen(f"{source}/metadata.json", timeout=20) as r:
                return dict(json.load(r))
        return dict(json.loads(Path(f"{source}/metadata.json").read_text()))
    except (OSError, ValueError):
        return {}


def load() -> Marts:
    source = _source()
    frames = {name: _read(source, name) for name in MARTS}
    if frames["mart_monthly_summary"].empty:
        frames["mart_monthly_summary"] = pd.DataFrame(
            columns=["thread_month", "is_complete_month", "postings"]
        )
    return Marts(frames, _read_metadata(source), source)
