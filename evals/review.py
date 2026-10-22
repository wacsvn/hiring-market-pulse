"""Human spot-check of the drafted audit labels (about 30 minutes for 20 posts).

Shows each post and the label drafted for it. Press Enter if every field is right, or
`e` to correct fields one by one. Progress is saved after every post, so you can quit
(`q`) and resume later. Your corrections override the drafted labels when scoring.

Usage: uv run python -m evals.review     # 20 random posts from the audit sample
"""

from __future__ import annotations

import json
import random
import textwrap
from datetime import UTC, datetime
from typing import Any

from evals.score import AUDIT, _jsonl

N_REVIEW = 20
SEED = 7
FIELDS: dict[str, str] = {
    "is_job_post": "true / false (an active hiring ad?)",
    "work_mode": "remote / hybrid / onsite / unknown (remote = any role allows remote)",
    "salary_min": "number or blank (first salary range stated)",
    "salary_max": "number or blank",
    "salary_currency": "USD / EUR / GBP / CAD / INR ... or blank",
    "salary_period": "year / hour or blank",
    "role_families": "comma list: engineering, data_ml, product, design, sales_marketing, "
    "operations, other",
    "seniority": "intern / junior / mid / senior / staff_plus / lead_manager / unknown "
    "(level of the first role named)",
}


def _parse(field: str, raw: str, current: Any) -> Any:
    raw = raw.strip()
    if raw == "":
        return current
    if raw == "-":
        return None
    if field == "is_job_post":
        return raw.lower() in {"true", "t", "yes", "y", "1"}
    if field in {"salary_min", "salary_max"}:
        return int(float(raw.replace(",", "").replace("k", "e3")))
    if field == "role_families":
        return sorted(r.strip() for r in raw.split(",") if r.strip())
    return raw


def main() -> None:
    sample = {r["post_id"]: r for r in _jsonl(AUDIT / "sample.jsonl")}
    labels = {r["post_id"]: r for r in _jsonl(AUDIT / "labels.jsonl")}
    review_path = AUDIT / "review.jsonl"
    done = {r["post_id"] for r in _jsonl(review_path)}
    picks = random.Random(SEED).sample(sorted(sample), N_REVIEW)
    todo = [p for p in picks if p not in done]
    print(f"{len(done & set(picks))}/{N_REVIEW} reviewed so far, {len(todo)} to go.\n")

    for i, pid in enumerate(todo, start=len(done & set(picks)) + 1):
        post, label = sample[pid], labels[pid]
        print("=" * 88)
        print(f"Post {i}/{N_REVIEW}  (id {pid}, {post['thread_month']})\n")
        for para in post["text"].split("\n"):
            print(textwrap.fill(para, 88))
        print("\nDrafted label:")
        for f in FIELDS:
            print(f"  {f:<16} {label[f]}")
        if label.get("note"):
            print(f"  (note: {label['note']})")
        choice = input("\n[Enter] all correct   [e] edit   [q] quit > ").strip().lower()
        if choice == "q":
            break
        final: dict[str, Any] = {}
        if choice == "e":
            print("For each field: Enter keeps the value, '-' clears it.")
            for f, hint in FIELDS.items():
                raw = input(f"  {f} [{label[f]}]  ({hint}) > ")
                try:
                    value = _parse(f, raw, label[f])
                except ValueError:
                    print("    couldn't read that; keeping the drafted value")
                    value = label[f]
                if value != label[f]:
                    final[f] = value
        row = {
            "post_id": pid,
            "agreed": not final,
            "final": final,
            "reviewed_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        with review_path.open("a") as fh:
            fh.write(json.dumps(row) + "\n")

    reviews = [r for r in _jsonl(review_path) if r["post_id"] in picks]
    if reviews:
        agreed = sum(r["agreed"] for r in reviews)
        fields_changed = sum(len(r["final"]) for r in reviews)
        print(
            f"\nAgreement: {agreed}/{len(reviews)} posts fully agreed "
            f"({fields_changed} field corrections). Saved to {review_path}."
        )


if __name__ == "__main__":
    main()
