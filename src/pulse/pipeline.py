"""Pipeline steps shared by the CLI and by CI's fixture build."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import httpx
from pydantic import ValidationError

from pulse import load
from pulse.contracts import Extraction, Rejected
from pulse.extract import rules
from pulse.sources.bls_jolts import BLSClient
from pulse.sources.hn_algolia import HNClient


@dataclass
class IngestSummary:
    threads: int
    months_fetched: int
    posts: int
    jolts_rows: int
    quarantined: int
    jolts_error: str | None = None  # set when BLS was unavailable and JOLTS was skipped


def ingest(
    hn: HNClient,
    bls: BLSClient,
    since: date,
    refetch_from: date,
    log: Callable[[str], None] = print,
) -> IngestSummary:
    """Fetch threads/posts/JOLTS into raw parquet.

    Months already on disk are skipped unless they are >= `refetch_from` (still collecting posts).
    """
    threads = hn.find_threads(since)
    load.write(load.to_frame(threads.accepted), load.data_dir() / "raw" / "hn_threads.parquet")
    quarantined = len(threads.rejected)
    load.append_quarantine(threads.rejected)

    have = load.existing_post_months()
    fetched = posts = 0
    for t in threads.accepted:
        if t.thread_month in have and t.thread_month < refetch_from:
            continue
        batch = hn.fetch_posts(t)
        if batch.accepted:
            load.write(load.to_frame(batch.accepted), load.posts_path(t.thread_month))
        load.append_quarantine(batch.rejected)
        fetched += 1
        posts += len(batch.accepted)
        quarantined += len(batch.rejected)
        log(
            f"{t.thread_month:%Y-%m}: {len(batch.accepted)} posts, "
            f"{len(batch.rejected)} quarantined"
        )

    years = [t.thread_month.year for t in threads.accepted] or [since.year]
    end_year = max(years)
    # JOLTS updates monthly, so a BLS outage shouldn't block the daily refresh. On failure no
    # JOLTS file is written, the warehouse load skips the dataset, and the last loaded JOLTS
    # data stays in place. dbt's continuity tests still run on it.
    try:
        jolts = bls.fetch(since.year, end_year)
    except (httpx.HTTPError, RuntimeError) as e:
        log(f"WARNING: BLS JOLTS unavailable, keeping the last loaded JOLTS data ({e})")
        return IngestSummary(len(threads.accepted), fetched, posts, 0, quarantined, str(e))
    load.write(load.to_frame(jolts.accepted), load.data_dir() / "raw" / "bls_jolts.parquet")
    load.append_quarantine(jolts.rejected)
    quarantined += len(jolts.rejected)
    return IngestSummary(len(threads.accepted), fetched, posts, len(jolts.accepted), quarantined)


def extract_rules() -> tuple[int, int]:
    """Run the rules extractor over every raw post. Returns (extracted, quarantined)."""
    posts = load.read_posts()
    if posts.empty:
        raise RuntimeError("No raw posts. Run `pulse ingest` first.")
    out: list[Extraction] = []
    bad: list[Rejected] = []
    for post_id, text_html in zip(posts["post_id"].astype(int), posts["text_html"], strict=True):
        try:
            out.append(rules.extract(post_id, str(text_html)))
        except ValidationError as e:
            bad.append(
                Rejected(
                    dataset="extractions", record_key=str(post_id), reason=str(e)[:500], payload=""
                )
            )
    load.write(load.to_frame(out), load.data_dir() / "extracted" / "rules.parquet")
    load.append_quarantine(bad)
    return len(out), len(bad)
