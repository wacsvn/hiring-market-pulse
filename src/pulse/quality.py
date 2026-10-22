"""Summaries of data-quality results for the dashboard's "Can I trust this?" panel."""

from __future__ import annotations

from collections import Counter
from typing import Any

AUDIT_FIELDS = {
    "work_mode_accuracy": "Work mode (remote / hybrid / onsite)",
    "salary_detection_accuracy": "Salary found when present, absent when not",
    "salary_values_correct": "Salary values correct",
    "seniority_accuracy": "Seniority",
    "role_families_exact": "Role families exactly right",
}


def summarise_audit(results: dict[str, Any]) -> dict[str, Any]:
    """Headline numbers from evals/score.py results, without the per-post error list."""
    return {
        "job_posts_checked": results["job_posts"],
        "sampled_posts": results["sampled_posts"],
        "non_job_post_rate": results["non_job_post_rate"],
        "fields": {label: results[key] for key, label in AUDIT_FIELDS.items()},
    }


def summarise_run_results(run_results: dict[str, Any]) -> dict[str, Any]:
    """Condense a dbt run_results.json into counts plus the names of anything not passing."""
    tests = [r for r in run_results.get("results", []) if r["unique_id"].startswith("test.")]
    statuses = Counter(str(r["status"]) for r in tests)
    return {
        "generated_at": run_results.get("metadata", {}).get("generated_at"),
        "tests_total": len(tests),
        "tests_passed": statuses.get("pass", 0),
        "tests_warned": statuses.get("warn", 0),
        "tests_failed": statuses.get("fail", 0) + statuses.get("error", 0),
        "not_passing": sorted(r["unique_id"].split(".")[2] for r in tests if r["status"] != "pass"),
    }
