from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated

import typer
from pydantic import ValidationError

from pulse import load
from pulse.contracts import Extraction, Rejected
from pulse.extract import rules
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
    since = _months_ago(months - 1)
    hn = HNClient()
    threads = hn.find_threads(since)
    load.write(load.to_frame(threads.accepted), load.data_dir() / "raw" / "hn_threads.parquet")
    load.append_quarantine(threads.rejected)

    have = load.existing_post_months()
    open_cutoff = _months_ago(refresh_open - 1)
    fetched = 0
    for t in threads.accepted:
        if t.thread_month in have and t.thread_month < open_cutoff:
            continue
        posts = hn.fetch_posts(t)
        load.write(load.to_frame(posts.accepted), load.posts_path(t.thread_month))
        load.append_quarantine(posts.rejected)
        fetched += 1
        typer.echo(
            f"{t.thread_month:%Y-%m}: {len(posts.accepted)} posts, "
            f"{len(posts.rejected)} quarantined"
        )

    jolts = BLSClient().fetch(since.year, datetime.now(UTC).year)
    load.write(load.to_frame(jolts.accepted), load.data_dir() / "raw" / "bls_jolts.parquet")
    load.append_quarantine(jolts.rejected)
    typer.echo(
        f"threads={len(threads.accepted)} fetched={fetched} "
        f"jolts_rows={len(jolts.accepted)} jolts_quarantined={len(jolts.rejected)}"
    )


@app.command()
def extract(
    provider: Annotated[str, typer.Option(help="rules (default) or an LLM provider.")] = "rules",
) -> None:
    """Extract structured fields from every raw post into data/extracted."""
    if provider != "rules":
        raise typer.BadParameter("LLM providers arrive in Phase 2; use --provider rules")
    posts = load.read_posts()
    if posts.empty:
        typer.echo("No raw posts. Run `pulse ingest` first.", err=True)
        raise typer.Exit(1)
    out: list[Extraction] = []
    bad: list[Rejected] = []
    for post_id, text_html in zip(posts["post_id"].astype(int), posts["text_html"], strict=True):
        try:
            out.append(rules.extract(post_id, str(text_html)))
        except ValidationError as e:
            bad.append(
                Rejected(
                    dataset="extractions", record_key=str(post_id), reason=str(e)[:500], payload=""
                )
            )
    path = load.data_dir() / "extracted" / f"{load.extractor_slug('rules')}.parquet"
    load.write(load.to_frame(out), path)
    load.append_quarantine(bad)
    typer.echo(f"extracted={len(out)} quarantined={len(bad)} -> {path}")


if __name__ == "__main__":
    app()
