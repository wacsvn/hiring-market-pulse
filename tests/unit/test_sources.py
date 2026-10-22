from __future__ import annotations

import copy
from datetime import date
from typing import Any

import httpx
import pytest

from pulse.sources.bls_jolts import BLSClient
from pulse.sources.hn_algolia import BASE_URL, HNClient, parse_thread_month
from tests.conftest import bls_transport, hn_transport, load_fixture


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Ask HN: Who is hiring? (October 2026)", date(2026, 10, 1)),
        ("Ask HN: Who is hiring? (January 2024)", date(2024, 1, 1)),
        ("  Ask HN: Who is hiring? (May 2025)  ", date(2025, 5, 1)),
        ("Ask HN: Who wants to be hired? (October 2026)", None),
        ("Ask HN: Who is hiring? (Sometime soon)", None),
        ("Ask HN: Who is hiring? (Octobre 2026)", None),
    ],
)
def test_parse_thread_month(title: str, expected: date | None) -> None:
    assert parse_thread_month(title) == expected


def test_find_threads_keeps_only_hiring_threads(hn_client: HNClient) -> None:
    batch = hn_client.find_threads(since=date(2000, 1, 1))
    months = [t.thread_month for t in batch.accepted]
    assert len(months) == 3
    assert months == sorted(months), "threads must come back in month order"
    assert all(t.title.startswith("Ask HN: Who is hiring?") for t in batch.accepted)


def test_find_threads_quarantines_malformed_titles(hn_client: HNClient) -> None:
    batch = hn_client.find_threads(since=date(2000, 1, 1))
    assert [r.record_key for r in batch.rejected] == ["1"]
    assert batch.rejected[0].reason == "unparseable thread title"


def test_find_threads_respects_since(hn_client: HNClient) -> None:
    all_threads = hn_client.find_threads(since=date(2000, 1, 1)).accepted
    newest = all_threads[-1].thread_month
    assert [t.thread_month for t in hn_client.find_threads(since=newest).accepted] == [newest]


def test_fetch_posts_quarantines_deleted_comments(hn_client: HNClient) -> None:
    thread = hn_client.find_threads(since=date(2000, 1, 1)).accepted[0]
    batch = hn_client.fetch_posts(thread)
    assert len(batch.accepted) == 40
    assert {p.thread_id for p in batch.accepted} == {thread.thread_id}
    assert len({p.post_id for p in batch.accepted}) == 40, "post ids must be unique"
    assert [(r.record_key, r.reason) for r in batch.rejected] == [("2", "empty or deleted")]


def test_fetch_posts_rejects_contract_violations() -> None:
    """Negative test: a corrupt upstream row is quarantined, not loaded."""

    def corrupt(item: dict[str, Any]) -> None:
        item["children"][0]["created_at_i"] = 4_102_444_800  # year 2100: in the future
        del item["children"][1]["created_at_i"]

    client = HNClient(httpx.Client(base_url=BASE_URL, transport=hn_transport(corrupt)))
    thread = client.find_threads(since=date(2000, 1, 1)).accepted[0]
    batch = client.fetch_posts(thread)
    assert len(batch.accepted) == 38
    reasons = " ".join(r.reason for r in batch.rejected)
    assert "future" in reasons
    assert "created_at_i" in reasons


def test_bls_parses_monthly_series(bls_client: BLSClient) -> None:
    batch = bls_client.fetch(2024, 2026)
    assert not batch.rejected
    assert {o.measure for o in batch.accepted} == {"openings", "hires", "quits"}
    keys = [(o.series_id, o.month) for o in batch.accepted]
    assert len(keys) == len(set(keys)), "one row per series per month"
    latest = max(batch.accepted, key=lambda o: o.month)
    assert latest.is_preliminary, "BLS flags the newest month as preliminary"


def test_bls_quarantines_bad_values() -> None:
    body = copy.deepcopy(load_fixture("bls_jolts.json"))
    body["Results"]["series"][0]["data"][0]["value"] = "-"
    body["Results"]["series"][0]["data"][1]["value"] = "-5"
    client = BLSClient(
        httpx.Client(base_url="https://api.bls.gov", transport=bls_transport(body)), api_key=""
    )
    batch = client.fetch(2024, 2026)
    assert len(batch.rejected) == 2


def test_bls_failed_request_raises() -> None:
    body = {"status": "REQUEST_NOT_PROCESSED", "message": ["daily threshold reached"]}
    client = BLSClient(
        httpx.Client(base_url="https://api.bls.gov", transport=bls_transport(body)), api_key=""
    )
    with pytest.raises(RuntimeError, match="threshold"):
        client.fetch(2024, 2026)
