"""Build a full raw + extracted dataset from the recorded API fixtures (no network).

CI uses this to run dbt and the dashboard on known data, through the same pipeline code
as production. Output goes to $PULSE_DATA_DIR (default ./data).
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import httpx

from pulse import pipeline
from pulse.sources.bls_jolts import BLSClient
from pulse.sources.hn_algolia import BASE_URL, HNClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # reuse the test suite's fakes
from tests.conftest import bls_transport, hn_transport


def main() -> None:
    hn = HNClient(httpx.Client(base_url=BASE_URL, transport=hn_transport()))
    bls = BLSClient(httpx.Client(base_url="https://api.bls.gov", transport=bls_transport()), "")
    s = pipeline.ingest(hn, bls, since=date(2000, 1, 1), refetch_from=date(2000, 1, 1))
    n, bad = pipeline.extract_rules()
    print(f"fixture data: posts={s.posts} jolts={s.jolts_rows} extracted={n} quarantined={bad}")


if __name__ == "__main__":
    main()
