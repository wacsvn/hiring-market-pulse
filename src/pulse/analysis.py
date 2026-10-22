"""Calculations behind the dashboard, kept out of the UI so they can be unit-tested."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Kpi:
    label: str
    value: float | None
    previous: float | None  # same measure in the comparison month, if there is one

    @property
    def delta(self) -> float | None:
        if self.value is None or self.previous is None:
            return None
        return self.value - self.previous


@dataclass(frozen=True)
class KpiSet:
    month: pd.Timestamp  # latest complete month in the selected range
    compared_with: pd.Timestamp | None  # first complete month in the range, if different
    kpis: list[Kpi]


def complete_months(monthly: pd.DataFrame) -> pd.DataFrame:
    return monthly[monthly["is_complete_month"]].sort_values("thread_month")


def headline_kpis(
    monthly: pd.DataFrame, start: pd.Timestamp | None = None, end: pd.Timestamp | None = None
) -> KpiSet | None:
    """KPIs for the latest complete month in [start, end], compared with the first month.

    Following the reader's date range means the change shown is the change across the
    months they chose. None if the range holds no complete month.
    """
    done = complete_months(monthly)
    if start is not None:
        done = done[done["thread_month"] >= start]
    if end is not None:
        done = done[done["thread_month"] <= end]
    if done.empty:
        return None
    latest, first = done.iloc[-1], done.iloc[0]
    prev = first if len(done) > 1 else None

    def pick(col: str) -> tuple[float | None, float | None]:
        v = latest[col]
        p = prev[col] if prev is not None else None
        return (None if pd.isna(v) else float(v), None if p is None or pd.isna(p) else float(p))

    return KpiSet(
        month=latest["thread_month"],
        compared_with=first["thread_month"] if prev is not None else None,
        kpis=[
            Kpi("Job posts", *pick("postings")),
            Kpi("Remote-friendly", *pick("share_remote")),
            Kpi("List a salary", *pick("share_with_salary")),
            Kpi("Median posted salary (USD)", *pick("median_salary_usd")),
        ],
    )


def movers_window(n_months: int, months: int = 6) -> int:
    """Months averaged at each end of the range: up to `months`, at most half the range.

    0 means the range is too short (under 2 months) to compare a start with an end.
    """
    return min(months, n_months // 2)


def tech_movers(tech: pd.DataFrame, months: int = 6) -> pd.DataFrame:
    """Change in share of posts mentioning each tech between the start and end of the data.

    Compares the average of the first `window` months with the last `window` months, where
    window = movers_window(...). Callers pass the months the reader selected. Returns tech,
    earlier_share, recent_share, change_pts (percentage points), sorted by change.
    """
    cols = ["tech", "earlier_share", "recent_share", "change_pts"]
    if tech.empty:
        return pd.DataFrame(columns=cols)
    all_months = sorted(tech["thread_month"].unique())
    window = movers_window(len(all_months), months)
    if window == 0:
        return pd.DataFrame(columns=cols)
    earlier, recent = all_months[:window], all_months[-window:]

    # Months where a tech isn't mentioned count as 0%, not as missing.
    grid = tech.pivot_table(
        index="thread_month", columns="tech", values="share_of_postings", fill_value=0.0
    ).reindex(all_months, fill_value=0.0)
    out = pd.DataFrame(
        {
            "earlier_share": grid.loc[earlier].mean(),
            "recent_share": grid.loc[recent].mean(),
        }
    )
    out["change_pts"] = 100 * (out["recent_share"] - out["earlier_share"])
    return out.reset_index().sort_values("change_pts", ascending=False, ignore_index=True)


def lead_lag_correlation(hn_vs_jolts: pd.DataFrame, max_lag: int = 3) -> pd.DataFrame:
    """Correlation of month-over-month changes at each lag.

    Positive lag k = HN leads JOLTS by k months (HN at t vs JOLTS at t+k).
    """
    df = hn_vs_jolts.sort_values("month")
    hn = df["hn_postings"].astype(float).pct_change()
    jolts = df["jolts_openings_k"].astype(float).pct_change()
    rows = []
    for k in range(-max_lag, max_lag + 1):
        pair = pd.concat([hn, jolts.shift(-k)], axis=1).dropna()
        corr = pair.iloc[:, 0].corr(pair.iloc[:, 1]) if len(pair) >= 6 else float("nan")
        rows.append({"lag_months": k, "correlation": corr, "n": len(pair)})
    return pd.DataFrame(rows)
