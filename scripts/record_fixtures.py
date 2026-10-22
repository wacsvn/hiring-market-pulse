"""Record trimmed real API responses into tests/fixtures/ for offline tests and CI.

Run occasionally (`uv run python scripts/record_fixtures.py`) to refresh fixtures when
upstream formats change. The edge cases appended below are synthetic and labelled as such.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
POSTS_PER_THREAD = 40
THREADS = 3


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    hn = httpx.Client(base_url="https://hn.algolia.com/api/v1", timeout=30)

    search = hn.get(
        "/search_by_date",
        params={
            "tags": "story,author_whoishiring",
            "hitsPerPage": 12,
            "page": 0,
        },
    ).json()
    hiring = [h for h in search["hits"] if h["title"].startswith("Ask HN: Who is hiring?")]
    others = [h for h in search["hits"] if not h["title"].startswith("Ask HN: Who is hiring?")]
    keep = hiring[:THREADS]
    # Synthetic edge case: a hiring thread whose title doesn't match the expected format.
    malformed = dict(keep[0], objectID="1", title="Ask HN: Who is hiring? (Sometime soon)")
    search["hits"] = [*keep, others[0], malformed]
    search["nbPages"] = 1
    search["nbHits"] = len(search["hits"])
    (OUT / "hn_search.json").write_text(json.dumps(search, indent=1))

    for hit in keep:
        item = hn.get(f"/items/{hit['objectID']}").json()
        kids = [c for c in item["children"] if c.get("text")][:POSTS_PER_THREAD]
        for c in kids:
            c["children"] = []  # replies are not job posts; drop them to keep fixtures small
        # Synthetic edge case: a deleted comment (null text), as the API returns them.
        kids.append(
            {
                "id": 2,
                "created_at_i": kids[-1]["created_at_i"],
                "author": None,
                "parent_id": item["id"],
                "type": "comment",
                "text": None,
                "children": [],
            }
        )
        item["children"] = kids
        (OUT / f"hn_item_{hit['objectID']}.json").write_text(json.dumps(item, indent=1))

    bls = httpx.post(
        "https://api.bls.gov/publicAPI/v1/timeseries/data/",
        json={
            "seriesid": ["JTS510000000000000JOL", "JTS510000000000000HIL", "JTS510000000000000QUL"],
            "startyear": "2024",
            "endyear": "2026",
        },
        timeout=30,
    ).json()
    (OUT / "bls_jolts.json").write_text(json.dumps(bls, indent=1))
    print(f"recorded fixtures to {OUT}")


if __name__ == "__main__":
    main()
