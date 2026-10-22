"""Score an extractor against the hand-checked audit labels.

Labels come from labels.jsonl (drafted by Claude). Where review.jsonl has a human decision
for a post, the human's version wins. Field accuracy is measured on real job posts only;
the share of sampled posts that aren't job ads is reported separately, because the
extractor has no way to flag them and they are counted as postings.

Usage:
  uv run python evals/score.py                    # print the report
  uv run python evals/score.py --write            # also write results.json / results.md
  uv run python evals/score.py --write-baseline   # accept current scores as the CI floor
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pulse.contracts import Extraction
from pulse.extract import rules

AUDIT = Path(__file__).parent / "audit_v1"
SALARY_TOLERANCE = 0.05  # bounds within 5% count as correct (e.g. "$150k" vs "$150,000+")

Extractor = Callable[[int, str], Extraction]


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def load_labels(audit: Path = AUDIT) -> tuple[list[dict[str, Any]], dict[int, dict[str, Any]]]:
    """Returns (sample rows, final labels by post_id) with human review applied."""
    sample = _jsonl(audit / "sample.jsonl")
    labels = {r["post_id"]: r for r in _jsonl(audit / "labels.jsonl")}
    for review in _jsonl(audit / "review.jsonl"):
        labels[review["post_id"]] = {**labels[review["post_id"]], **review["final"]}
    return sample, labels


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= SALARY_TOLERANCE * max(abs(a), abs(b))


def score(extract: Extractor = rules.extract, audit: Path = AUDIT) -> dict[str, Any]:
    sample, labels = load_labels(audit)
    jobs = [s for s in sample if labels[s["post_id"]]["is_job_post"]]
    n = len(jobs)

    work_ok = sen_ok = roles_exact = 0
    sal_tp = sal_fn = sal_fp = sal_tn = sal_bounds_ok = 0
    role_tp = role_fp = role_fn = 0
    confusion: Counter[str] = Counter()
    errors: list[dict[str, Any]] = []

    for s in jobs:
        gold = labels[s["post_id"]]
        got = extract(s["post_id"], s["text_html"])

        if got.work_mode == gold["work_mode"]:
            work_ok += 1
        else:
            confusion[f"{gold['work_mode']}->{got.work_mode}"] += 1
            errors.append(
                {
                    "post_id": s["post_id"],
                    "field": "work_mode",
                    "expected": gold["work_mode"],
                    "got": got.work_mode,
                }
            )

        if got.seniority == gold["seniority"]:
            sen_ok += 1
        else:
            errors.append(
                {
                    "post_id": s["post_id"],
                    "field": "seniority",
                    "expected": gold["seniority"],
                    "got": got.seniority,
                }
            )

        gold_roles, got_roles = set(gold["role_families"]), set(got.role_families)
        roles_exact += gold_roles == got_roles
        role_tp += len(gold_roles & got_roles)
        role_fp += len(got_roles - gold_roles)
        role_fn += len(gold_roles - got_roles)
        if gold_roles != got_roles:
            errors.append(
                {
                    "post_id": s["post_id"],
                    "field": "role_families",
                    "expected": sorted(gold_roles),
                    "got": sorted(got_roles),
                }
            )

        has_gold, has_got = gold["salary_min"] is not None, got.salary_min is not None
        if has_gold and has_got:
            sal_tp += 1
            assert got.salary_max is not None
            if (
                got.salary_currency == gold["salary_currency"]
                and got.salary_period == gold["salary_period"]
                and _close(got.salary_min, gold["salary_min"])
                and _close(got.salary_max, gold["salary_max"])
            ):
                sal_bounds_ok += 1
            else:
                errors.append(
                    {
                        "post_id": s["post_id"],
                        "field": "salary",
                        "expected": [
                            gold["salary_min"],
                            gold["salary_max"],
                            gold["salary_currency"],
                            gold["salary_period"],
                        ],
                        "got": [
                            got.salary_min,
                            got.salary_max,
                            got.salary_currency,
                            got.salary_period,
                        ],
                    }
                )
        elif has_gold:
            sal_fn += 1
            errors.append(
                {"post_id": s["post_id"], "field": "salary", "expected": "a salary", "got": None}
            )
        elif has_got:
            sal_fp += 1
            errors.append(
                {
                    "post_id": s["post_id"],
                    "field": "salary",
                    "expected": None,
                    "got": [got.salary_min, got.salary_max, got.salary_currency],
                }
            )
        else:
            sal_tn += 1

    def pct(num: int, den: int) -> float:
        return round(num / den, 3) if den else 0.0

    return {
        "sampled_posts": len(sample),
        "job_posts": n,
        "non_job_post_rate": pct(len(sample) - n, len(sample)),
        "work_mode_accuracy": pct(work_ok, n),
        "seniority_accuracy": pct(sen_ok, n),
        "role_families_exact": pct(roles_exact, n),
        "role_families_precision": pct(role_tp, role_tp + role_fp),
        "role_families_recall": pct(role_tp, role_tp + role_fn),
        "salary_detection_accuracy": pct(sal_tp + sal_tn, n),
        "salary_recall": pct(sal_tp, sal_tp + sal_fn),
        "salary_precision": pct(sal_tp, sal_tp + sal_fp),
        "salary_values_correct": pct(sal_bounds_ok, sal_tp + sal_fn),
        "work_mode_confusion": dict(confusion.most_common()),
        "errors": errors,
    }


GATED = [
    "work_mode_accuracy",
    "seniority_accuracy",
    "role_families_exact",
    "salary_detection_accuracy",
    "salary_values_correct",
]


def regressions(
    result: dict[str, Any], baseline: dict[str, float], slack: float = 0.02
) -> list[str]:
    """Metrics that fell more than `slack` below the committed baseline."""
    return [
        f"{m}: {result[m]:.3f} < baseline {baseline[m]:.3f} - {slack}"
        for m in GATED
        if result[m] < baseline[m] - slack
    ]


def markdown(result: dict[str, Any]) -> str:
    rows = [
        ("Work mode (remote / hybrid / onsite / unknown)", result["work_mode_accuracy"]),
        ("Salary found when present, absent when not", result["salary_detection_accuracy"]),
        ("Salary values correct (of posts that state one)", result["salary_values_correct"]),
        ("Role families exactly right", result["role_families_exact"]),
        ("Seniority", result["seniority_accuracy"]),
    ]
    lines = [
        f"Rules extractor vs {result['job_posts']} hand-checked job posts "
        f"(sample of {result['sampled_posts']}; "
        f"{result['non_job_post_rate']:.0%} of sampled posts were not job ads).",
        "",
        "| Field | Accuracy |",
        "|---|---|",
        *[f"| {name} | {value:.0%} |" for name, value in rows],
    ]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--write-baseline", action="store_true")
    args = ap.parse_args()
    result = score()
    print(markdown(result))
    print("\nwork_mode confusion:", result["work_mode_confusion"])
    print(f"errors: {len(result['errors'])} (see results.json)")
    if args.write or args.write_baseline:
        (AUDIT / "results.json").write_text(json.dumps(result, indent=2) + "\n")
        (AUDIT / "results.md").write_text(markdown(result) + "\n")
    if args.write_baseline:
        baseline = {m: result[m] for m in GATED}
        (AUDIT / "baseline.json").write_text(json.dumps(baseline, indent=2) + "\n")
        print("baseline written")


if __name__ == "__main__":
    main()
