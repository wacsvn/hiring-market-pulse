"""Summaries of data-quality results for the dashboard's "Can I trust this?" panel."""

from __future__ import annotations

from collections import Counter
from typing import Any


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
