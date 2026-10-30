"""Open (or comment on) a GitHub issue when the scheduled refresh fails.

Summarises dbt's run_results.json if the run got that far, links the workflow run, and
keeps one open issue per incident: repeated failures add comments instead of new issues.
Needs the `gh` CLI with GH_TOKEN, plus GITHUB_REPOSITORY / GITHUB_RUN_ID from Actions.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

LABEL = "data-quality"
RUN_RESULTS = Path("dbt/target/run_results.json")


def gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def summary() -> str:
    run_url = (
        f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/"
        f"{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
    )
    lines = [f"Scheduled refresh failed: {run_url}", ""]
    if os.environ.get("WAREHOUSE_OUTCOME") == "failure":
        lines.append(
            "The Databricks SQL warehouse would not start, so nothing ran. Start it by hand "
            "(Databricks > SQL Warehouses > Start), then re-run this workflow. If Start fails "
            "too, the UI shows why (quota, billing, or capacity)."
        )
        return "\n".join(lines)
    if not RUN_RESULTS.exists():
        lines.append("dbt did not run; the failure happened earlier (ingest, extract, or load).")
        return "\n".join(lines)
    results = json.loads(RUN_RESULTS.read_text())["results"]
    bad = [r for r in results if r["status"] in {"fail", "error"}]
    lines.append(
        f"{len(bad)} dbt node(s) failed. Nothing was published; the dashboard keeps "
        "showing the last good data."
    )
    lines.append("")
    lines.append("| node | status | failing rows | message |")
    lines.append("|---|---|---|---|")
    for r in bad:
        name = r["unique_id"].split(".")[2]
        msg = (r.get("message") or "").replace("\n", " ")[:160]
        lines.append(f"| `{name}` | {r['status']} | {r.get('failures') or ''} | {msg} |")
    return "\n".join(lines)


def main() -> None:
    body = summary()
    gh(
        "label",
        "create",
        LABEL,
        "--color",
        "d03b3b",
        "--force",
        "--description",
        "Refresh pipeline data-quality failure",
    )
    open_issues = json.loads(
        gh("issue", "list", "--label", LABEL, "--state", "open", "--json", "number", "--limit", "1")
    )
    if open_issues:
        gh("issue", "comment", str(open_issues[0]["number"]), "--body", body)
    else:
        gh("issue", "create", "--title", "Data refresh failed", "--label", LABEL, "--body", body)
    print(body)


if __name__ == "__main__":
    main()
