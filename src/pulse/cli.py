from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated

import typer

from pulse import pipeline, quality
from pulse.sources.bls_jolts import BLSClient
from pulse.sources.hn_algolia import HNClient

app = typer.Typer(help="Hiring Market Pulse pipeline.", no_args_is_help=True)


def _months_ago(n: int, today: date | None = None) -> date:
    today = today or datetime.now(UTC).date()
    idx = today.year * 12 + (today.month - 1) - n
    return date(idx // 12, idx % 12 + 1, 1)


@app.command()
def ingest(
    months: Annotated[int, typer.Option(help="How many months of threads to cover.")] = 36,
    refresh_open: Annotated[int, typer.Option(help="Re-fetch the newest N months.")] = 2,
) -> None:
    """Fetch HN hiring threads and BLS JOLTS into data/raw (incremental)."""
    s = pipeline.ingest(
        HNClient(),
        BLSClient(),
        since=_months_ago(months - 1),
        refetch_from=_months_ago(refresh_open - 1),
        log=typer.echo,
    )
    typer.echo(
        f"threads={s.threads} months_fetched={s.months_fetched} posts={s.posts} "
        f"jolts_rows={s.jolts_rows} quarantined={s.quarantined}"
    )


@app.command()
def extract(
    provider: Annotated[str, typer.Option(help="rules (default) or an LLM provider.")] = "rules",
) -> None:
    """Extract structured fields from every raw post into data/extracted."""
    if provider != "rules":
        raise typer.BadParameter("LLM providers arrive in Phase 2; use --provider rules")
    try:
        n, bad = pipeline.extract_rules()
    except RuntimeError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from e
    typer.echo(f"extracted={n} quarantined={bad}")


@app.command("load-warehouse")
def load_warehouse(
    raw_schema: Annotated[str, typer.Option(help="Databricks raw schema.")] = "pulse_raw",
) -> None:
    """Upload raw parquet to Databricks and (re)create the raw tables."""
    from pulse import warehouse

    warehouse.load_raw(raw_schema, log=typer.echo)


@app.command("export-marts")
def export_marts(
    schema: Annotated[str, typer.Option(help="Databricks schema dbt built into.")] = "pulse",
    out: Annotated[Path, typer.Option(help="Output directory.")] = Path("data/marts"),
    dbt_results: Annotated[
        Path | None, typer.Option(help="dbt run_results.json to summarise for the app.")
    ] = None,
) -> None:
    """Export the marts (and a data-quality summary) as parquet/JSON for the dashboard."""
    from pulse import warehouse

    warehouse.export_marts(schema, out, log=typer.echo)
    meta: dict[str, object] = {"exported_at": datetime.now(UTC).isoformat(), "schema": schema}
    if dbt_results and dbt_results.exists():
        meta["dbt"] = quality.summarise_run_results(json.loads(dbt_results.read_text()))
    (out / "metadata.json").write_text(json.dumps(meta, indent=2))
    typer.echo(f"wrote {out / 'metadata.json'}")


@app.command("drop-schemas")
def drop_schemas(schemas: list[str]) -> None:
    """Drop Databricks schemas (used to clean up per-PR CI schemas)."""
    from pulse import warehouse

    warehouse.drop_schemas(*schemas)
    typer.echo(f"dropped: {', '.join(schemas)}")


if __name__ == "__main__":
    app()
