"""Calculations behind the dashboard, kept out of the UI so they can be unit-tested."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Kpi:
    label: str
    value: float | None
    previous: float | None  # same month one year earlier, if available

    @property
    def delta(self) -> float | None:
        if self.value is None or self.previous is None:
            return None
        return self.value - self.previous


def complete_months(monthly: pd.DataFrame) -> pd.DataFrame:
    return monthly[monthly["is_complete_month"]].sort_values("thread_month")


def headline_kpis(monthly: pd.DataFrame) -> list[Kpi]:
    """KPIs for the latest complete month, each compared with 12 months earlier."""
    done = complete_months(monthly)
    if done.empty:
        return []
    latest = done.iloc[-1]
    year_ago_month = latest["thread_month"] - pd.DateOffset(years=1)
    prior = done[done["thread_month"] == year_ago_month]
    prev = prior.iloc[0] if not prior.empty else None

    def pick(col: str) -> tuple[float | None, float | None]:
        v = latest[col]
        p = prev[col] if prev is not None else None
        return (None if pd.isna(v) else float(v), None if p is None or pd.isna(p) else float(p))

    return [
        Kpi("Job posts", *pick("postings")),
        Kpi("Remote-friendly", *pick("share_remote")),
        Kpi("List a salary", *pick("share_with_salary")),
        Kpi("Median posted salary (USD)", *pick("median_salary_usd")),
    ]


def tech_movers(tech: pd.DataFrame, months: int = 6) -> pd.DataFrame:
    """Change in share of posts mentioning each tech: last `months` vs first `months` of the data.

    Callers pass the months the reader selected, so "change" means change across that window.
    Returns tech, earlier_share, recent_share, change_pts (percentage points), sorted by change.
    """
    if tech.empty:
        return pd.DataFrame(columns=["tech", "earlier_share", "recent_share", "change_pts"])
    all_months = sorted(tech["thread_month"].unique())
    window = min(months, max(1, len(all_months) // 2))
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
