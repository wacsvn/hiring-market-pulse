"""BLS JOLTS (Job Openings and Labor Turnover Survey) for the Information sector.

Uses the BLS Public Data API. v2 with BLS_API_KEY if set, otherwise keyless v1
(25 requests/day, 10 years per request), which is plenty for a monthly refresh.
Docs: https://www.bls.gov/developers/
"""

from __future__ import annotations

import os
from datetime import date

import httpx
from pydantic import ValidationError

from pulse import http as retrying
from pulse.batch import Batch, reject
from pulse.contracts import JoltsMeasure, JoltsObservation

# JT + S(easonally adjusted) + industry 510000 (Information) + all areas/sizes + element + Level
SERIES: dict[str, JoltsMeasure] = {
    "JTS510000000000000JOL": "openings",
    "JTS510000000000000HIL": "hires",
    "JTS510000000000000QUL": "quits",
}


class BLSClient:
    def __init__(
        self, http: httpx.Client | None = None, api_key: str | None = None, retry_delay: float = 2.0
    ) -> None:
        self.retry_delay = retry_delay
        self.api_key = api_key if api_key is not None else os.environ.get("BLS_API_KEY")
        version = "v2" if self.api_key else "v1"
        self.http = http or httpx.Client(
            base_url=f"https://api.bls.gov/publicAPI/{version}", timeout=30
        )

    def fetch(self, start_year: int, end_year: int) -> Batch[JoltsObservation]:
        payload: dict[str, object] = {
            "seriesid": list(SERIES),
            "startyear": str(start_year),
            "endyear": str(end_year),
        }
        if self.api_key:
            payload["registrationkey"] = self.api_key
        resp = retrying.request(
            self.http, "POST", "/timeseries/data/", json=payload, base_delay=self.retry_delay
        )
        body = resp.json()
        if body.get("status") != "REQUEST_SUCCEEDED":
            raise RuntimeError(f"BLS request failed: {body.get('message')}")

        out: Batch[JoltsObservation] = Batch()
        for series in body["Results"]["series"]:
            sid = series["seriesID"]
            for row in series["data"]:
                key = f"{sid}:{row.get('year')}{row.get('period')}"
                period = row.get("period", "")
                if not period.startswith("M") or period == "M13":  # M13 = annual average
                    continue
                try:
                    out.accepted.append(
                        JoltsObservation(
                            series_id=sid,
                            measure=SERIES[sid],
                            month=date(int(row["year"]), int(period[1:]), 1),
                            value_thousands=float(row["value"]),
                            is_preliminary=any(
                                f.get("code") == "P" for f in row.get("footnotes", [])
                            ),
                        )
                    )
                except (KeyError, ValueError, ValidationError) as e:
                    out.rejected.append(reject("bls_jolts", key, str(e), row))
        return out
