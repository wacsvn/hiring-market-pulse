"""Hacker News "Ask HN: Who is hiring?" threads via the public Algolia API.

Docs: https://hn.algolia.com/api
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime

import httpx
from pydantic import ValidationError

from pulse import http as retrying
from pulse.batch import Batch, reject
from pulse.contracts import HiringThread, RawPost

BASE_URL = "https://hn.algolia.com/api/v1"
THREAD_TITLE = re.compile(r"^Ask HN: Who is hiring\? \(([A-Z][a-z]+) (\d{4})\)$")
MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ],
        start=1,
    )
}


def parse_thread_month(title: str) -> date | None:
    """'Ask HN: Who is hiring? (October 2026)' -> date(2026, 10, 1). None if not a hiring thread."""
    m = THREAD_TITLE.match(title.strip())
    if not m or m.group(1) not in MONTHS:
        return None
    return date(int(m.group(2)), MONTHS[m.group(1)], 1)


class HNClient:
    def __init__(self, http: httpx.Client | None = None, retry_delay: float = 2.0) -> None:
        self.http = http or httpx.Client(base_url=BASE_URL, timeout=30)
        self.retry_delay = retry_delay

    def find_threads(self, since: date) -> Batch[HiringThread]:
        """All 'Who is hiring?' threads covering months >= `since`."""
        out: Batch[HiringThread] = Batch()
        since_ts = int(datetime(since.year, since.month, 1, tzinfo=UTC).timestamp()) - 7 * 86400
        page = 0
        while True:
            resp = retrying.request(
                self.http,
                "GET",
                "/search_by_date",
                base_delay=self.retry_delay,
                params={
                    "tags": "story,author_whoishiring",
                    "numericFilters": f"created_at_i>{since_ts}",
                    "hitsPerPage": 100,
                    "page": page,
                },
            )
            body = resp.json()
            for hit in body["hits"]:
                title = hit.get("title") or ""
                # The same account posts "Who wants to be hired?" and "Freelancer?" threads.
                if not title.startswith("Ask HN: Who is hiring?"):
                    continue
                month = parse_thread_month(title)
                if month is None:
                    out.rejected.append(
                        reject("hn_threads", hit.get("objectID"), "unparseable thread title", hit)
                    )
                    continue
                if month < since:
                    continue
                try:
                    out.accepted.append(
                        HiringThread(
                            thread_id=int(hit["objectID"]),
                            title=title,
                            thread_month=month,
                            posted_at=datetime.fromtimestamp(hit["created_at_i"], UTC),
                        )
                    )
                except (KeyError, ValueError, ValidationError) as e:
                    out.rejected.append(reject("hn_threads", hit.get("objectID"), str(e), hit))
            page += 1
            if page >= body.get("nbPages", 0):
                break
        out.accepted.sort(key=lambda t: t.thread_month)
        return out

    def fetch_posts(self, thread: HiringThread) -> Batch[RawPost]:
        """Top-level comments of a thread. Each top-level comment is one job post."""
        resp = retrying.request(
            self.http, "GET", f"/items/{thread.thread_id}", base_delay=self.retry_delay
        )
        out: Batch[RawPost] = Batch()
        for child in resp.json().get("children", []):
            if child.get("type") != "comment":
                continue
            if not child.get("text"):
                # Deleted/flagged comments come back with null text.
                out.rejected.append(reject("hn_posts", child.get("id"), "empty or deleted", child))
                continue
            try:
                out.accepted.append(
                    RawPost(
                        post_id=child["id"],
                        thread_id=thread.thread_id,
                        thread_month=thread.thread_month,
                        posted_at=datetime.fromtimestamp(child["created_at_i"], UTC),
                        author=child.get("author"),
                        text_html=child["text"],
                    )
                )
            except (KeyError, ValueError, ValidationError) as e:
                out.rejected.append(
                    reject(
                        "hn_posts",
                        child.get("id"),
                        str(e),
                        {k: v for k, v in child.items() if k != "children"},
                    )
                )
        return out
