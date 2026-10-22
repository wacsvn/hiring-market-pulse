"""Mutation check for the data tests: prove each dbt test can actually fail.

For every mutation, a copy of the raw schema is corrupted in one specific way, the
models upstream of the target test are rebuilt, and the run must report that test
as FAILED. A test that still passes on corrupted data is a test that can't fail.

Usage: uv run python scripts/dbt_mutation_check.py --source-schema pulse_dev_raw
Needs DATABRICKS_* env vars. Leaves no schemas behind.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from pulse.warehouse import CATALOG, DATASETS, connect, drop_schemas

DBT_DIR = Path(__file__).resolve().parents[1] / "dbt"


@dataclass(frozen=True)
class Mutation:
    name: str
    test: str  # dbt test that must fail
    tables: tuple[str, ...]  # raw tables this mutation modifies
    sql: tuple[str, ...]  # statements; {s} is the mutant schema


MUTATIONS = [
    Mutation(
        "duplicate post",
        "source_unique_raw_hn_posts_post_id",
        ("hn_posts",),
        ("INSERT INTO {s}.hn_posts SELECT * FROM {s}.hn_posts LIMIT 1",),
    ),
    Mutation(
        "inverted salary range",
        "salary_min_not_above_max",
        ("extractions_rules",),
        (
            "UPDATE {s}.extractions_rules SET salary_min = salary_max + 1000 "
            "WHERE post_id = (SELECT min(post_id) FROM {s}.extractions_rules "
            "WHERE salary_min IS NOT NULL)",
        ),
    ),
    Mutation(
        "only one salary bound",
        "salary_bounds_set_together",
        ("extractions_rules",),
        (
            "UPDATE {s}.extractions_rules SET salary_max = NULL "
            "WHERE post_id = (SELECT min(post_id) FROM {s}.extractions_rules "
            "WHERE salary_min IS NOT NULL)",
        ),
    ),
    Mutation(
        "unknown work mode label",
        "accepted_values_stg_extractions_work_mode__remote__hybrid__onsite__unknown",
        ("extractions_rules",),
        (
            "UPDATE {s}.extractions_rules SET work_mode = 'sometimes' "
            "WHERE post_id = (SELECT min(post_id) FROM {s}.extractions_rules)",
        ),
    ),
    Mutation(
        "gap in JOLTS series",
        "assert_no_missing_jolts_months",
        ("bls_jolts",),
        (
            "DELETE FROM {s}.bls_jolts WHERE measure = 'openings' AND month = "
            "(SELECT add_months(min(month), 3) FROM {s}.bls_jolts)",
        ),
    ),
    Mutation(
        "negative JOLTS value",
        "dbt_utils_source_accepted_range_raw_bls_jolts_value_thousands__0",
        ("bls_jolts",),
        (
            "UPDATE {s}.bls_jolts SET value_thousands = -1 "
            "WHERE month = (SELECT min(month) FROM {s}.bls_jolts)",
        ),
    ),
    Mutation(
        "post older than its thread",
        "assert_posts_not_before_thread",
        ("hn_posts",),
        (
            "UPDATE {s}.hn_posts SET posted_at = posted_at - INTERVAL 30 DAYS "
            "WHERE post_id = (SELECT min(post_id) FROM {s}.hn_posts)",
        ),
    ),
    Mutation(
        "schema drift (rescued data)",
        "dbt_utils_source_expression_is_true_raw_hn_posts__rescued_data__is_null",
        ("hn_posts",),
        (
            'UPDATE {s}.hn_posts SET _rescued_data = \'{{"salary": "n/a"}}\' '
            "WHERE post_id = (SELECT min(post_id) FROM {s}.hn_posts)",
        ),
    ),
    Mutation(
        "missing month of threads",
        "assert_no_missing_hn_months",
        ("hn_threads", "hn_posts"),
        (
            "DELETE FROM {s}.hn_posts WHERE thread_month = "
            "(SELECT min(thread_month) + INTERVAL 1 MONTH FROM {s}.hn_threads)",
            "DELETE FROM {s}.hn_threads WHERE thread_month = "
            "(SELECT min(thread_month) + INTERVAL 1 MONTH FROM {s}.hn_threads)",
        ),
    ),
    Mutation(
        "collapsed fetch (too few posts)",
        "assert_posts_per_complete_month_in_range",
        ("hn_posts",),
        (
            "DELETE FROM {s}.hn_posts WHERE thread_month = (SELECT min(thread_month) "
            "FROM {s}.hn_posts) AND post_id % 10 != 0",
        ),
    ),
    Mutation(
        "quarantine spike",
        "assert_quarantine_rate_below_5pct",
        ("quarantine",),
        (
            "INSERT INTO {s}.quarantine SELECT 'hn_posts', CAST(id AS STRING), 'synthetic', "
            "'', current_timestamp(), NULL, current_timestamp() FROM range(50)",
        ),
    ),
]


def copy_tables(cur: object, src: str, dst: str, tables: tuple[str, ...] | list[str]) -> None:
    for t in tables:
        cur.execute(  # type: ignore[attr-defined]
            f"CREATE OR REPLACE TABLE {CATALOG}.{dst}.{t} AS SELECT * FROM {CATALOG}.{src}.{t}"
        )


def run_dbt(test: str, raw_schema: str, dbt_schema: str) -> str:
    """Build the test's upstream models, then run only that test; returns its status.

    Models and the test run separately so a different upstream test failing first can't
    mark the target test as skipped and hide whether it would have caught the mutation.
    """
    env = {**os.environ, "PULSE_RAW_SCHEMA": raw_schema, "DBT_SCHEMA": dbt_schema}
    for cmd in ("run", "test"):
        selector = f"+{test}" if cmd == "run" else test
        subprocess.run(
            ["dbt", cmd, "--profiles-dir", ".", "--select", selector, "--quiet"],
            cwd=DBT_DIR,
            env=env,
            check=False,
            capture_output=True,
        )
    results = json.loads((DBT_DIR / "target" / "run_results.json").read_text())
    for r in results["results"]:
        if r["unique_id"].split(".")[2] == test or r["unique_id"].endswith(f".{test}"):
            return str(r["status"])
    return "not run"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-schema", default="pulse_dev_raw")
    args = ap.parse_args()
    src = args.source_schema
    mut, mut_dbt = f"{src}_mut", f"{src}_mut_dbt"

    tables = list(DATASETS)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{mut}")
        copy_tables(cur, src, mut, tables)

    survivors = []
    try:
        for m in MUTATIONS:
            with connect() as conn, conn.cursor() as cur:
                for stmt in m.sql:
                    cur.execute(stmt.format(s=f"{CATALOG}.{mut}"))
            status = run_dbt(m.test, mut, mut_dbt)
            caught = status in {"fail", "error"}
            print(f"{'CAUGHT ' if caught else 'MISSED '} {m.name:<34} -> {m.test} [{status}]")
            if not caught:
                survivors.append(m.name)
            with connect() as conn, conn.cursor() as cur:  # restore for the next mutation
                copy_tables(cur, src, mut, m.tables)
    finally:
        drop_schemas(mut, mut_dbt)

    print(f"\n{len(MUTATIONS) - len(survivors)}/{len(MUTATIONS)} mutations caught")
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
