"""Draw the audit sample: 50 recent posts, stratified so salary and remote cases all appear.

Strata (fixed seed): 20 posts containing a currency amount, 15 mentioning "remote" but no
amount, 15 with neither. Reads raw posts from $PULSE_DATA_DIR (default ./data).

Usage: uv run python evals/sample.py evals/audit_v1/sample.jsonl
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

from pulse import load
from pulse.extract.text import html_to_text

SEED = 42
SINCE = pd.Timestamp("2025-10-01").date()


def main(out: Path) -> None:
    posts = load.read_posts()
    posts = posts[posts["thread_month"] >= SINCE].reset_index(drop=True)
    posts["text"] = posts["text_html"].map(html_to_text)
    has_salary = posts["text"].str.contains(r"[$€£]\s?\d", regex=True)
    mentions_remote = posts["text"].str.contains(r"\bremote\b", case=False, regex=True)

    salary = posts[has_salary].sample(20, random_state=SEED)
    remote = posts[mentions_remote & ~has_salary].sample(15, random_state=SEED)
    other = posts[~mentions_remote & ~has_salary].sample(15, random_state=SEED)
    sample = pd.concat([salary, remote, other]).sample(frac=1, random_state=SEED)

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as f:
        for r in sample.itertuples():
            row = {
                "post_id": int(r.post_id),
                "thread_month": str(r.thread_month),
                "text": r.text,  # readable, for review
                "text_html": r.text_html,  # what the extractor actually sees
            }
            f.write(json.dumps(row) + "\n")
    print(f"wrote {len(sample)} posts to {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
