from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from pulse import analysis


def _monthly(n: int, last_complete: bool = False) -> pd.DataFrame:
    months = pd.date_range("2024-01-01", periods=n, freq="MS")
    return pd.DataFrame(
        {
            "thread_month": months,
            "is_complete_month": [True] * (n - 1) + [last_complete],
            "postings": np.arange(100, 100 + n),
            "share_remote": np.linspace(0.6, 0.5, n),
            "share_with_salary": np.linspace(0.1, 0.3, n),
            "median_salary_usd": np.linspace(150_000, 180_000, n),
        }
    )


def _posts(result: analysis.KpiSet | None) -> analysis.Kpi:
    assert result is not None
    return next(k for k in result.kpis if k.label == "Job posts")


def test_headline_kpis_compare_latest_complete_month_with_first_month() -> None:
    result = analysis.headline_kpis(_monthly(15))
    # 15 months, the last is incomplete -> latest complete is index 13; first is index 0.
    assert result is not None
    assert result.month == pd.Timestamp("2025-02-01")
    assert result.compared_with == pd.Timestamp("2024-01-01")
    posts = _posts(result)
    assert (posts.value, posts.previous, posts.delta) == (113, 100, 13)


def test_headline_kpis_follow_the_selected_range() -> None:
    """Found in review: the KPIs ignored the date filter."""
    df = _monthly(15)
    result = analysis.headline_kpis(
        df, start=pd.Timestamp("2024-03-01"), end=pd.Timestamp("2024-08-01")
    )
    assert result is not None
    assert result.month == pd.Timestamp("2024-08-01")
    assert result.compared_with == pd.Timestamp("2024-03-01")
    assert (_posts(result).value, _posts(result).previous) == (107, 102)


def test_headline_kpis_single_month_has_no_comparison() -> None:
    result = analysis.headline_kpis(
        _monthly(6), start=pd.Timestamp("2024-02-01"), end=pd.Timestamp("2024-02-01")
    )
    assert result is not None
    assert result.compared_with is None
    assert all(k.delta is None for k in result.kpis)


def test_headline_kpis_none_when_no_complete_month() -> None:
    assert analysis.headline_kpis(_monthly(1)) is None


@pytest.mark.parametrize(("n", "expected"), [(1, 0), (2, 1), (5, 2), (12, 6), (36, 6)])
def test_movers_window(n: int, expected: int) -> None:
    assert analysis.movers_window(n) == expected


def test_tech_movers_short_window_splits_in_half() -> None:
    months = pd.date_range("2024-01-01", periods=4, freq="MS")
    rows = [
        {"thread_month": m, "tech": "go", "share_of_postings": v}
        for m, v in zip(months, [0.1, 0.1, 0.3, 0.3], strict=True)
    ]
    out = analysis.tech_movers(pd.DataFrame(rows), months=6)
    assert out.loc[0, "change_pts"] == pytest.approx(20.0)


def test_tech_movers_counts_absent_months_as_zero() -> None:
    months = pd.date_range("2024-01-01", periods=18, freq="MS")
    rows = [{"thread_month": m, "tech": "python", "share_of_postings": 0.2} for m in months]
    # 'rust' only appears in the last 6 months at 10% -> +10 points, not NaN.
    rows += [{"thread_month": m, "tech": "rust", "share_of_postings": 0.1} for m in months[-6:]]
    out = analysis.tech_movers(pd.DataFrame(rows), months=6).set_index("tech")
    assert out.loc["rust", "change_pts"] == pytest.approx(10.0)
    assert out.loc["python", "change_pts"] == pytest.approx(0.0)
    assert out.index[0] == "rust"


def test_lead_lag_detects_a_known_lead() -> None:
    """Negative-control style check: build JOLTS as HN shifted by 2 months; lag +2 must win."""
    rng = np.random.default_rng(0)
    hn = 300 * np.cumprod(1 + rng.normal(0, 0.1, 40))
    jolts = np.roll(hn, 2)
    df = pd.DataFrame(
        {
            "month": pd.date_range("2023-01-01", periods=40, freq="MS"),
            "hn_postings": hn,
            "jolts_openings_k": jolts,
        }
    ).iloc[2:]
    out = analysis.lead_lag_correlation(df, max_lag=3).set_index("lag_months")
    assert out["correlation"].idxmax() == 2
    assert out.loc[2, "correlation"] == pytest.approx(1.0)


def test_lead_lag_needs_enough_points() -> None:
    df = pd.DataFrame(
        {
            "month": pd.date_range("2024-01-01", periods=4, freq="MS"),
            "hn_postings": [1, 2, 3, 4],
            "jolts_openings_k": [4, 3, 2, 1],
        }
    )
    out = analysis.lead_lag_correlation(df, max_lag=1)
    assert all(math.isnan(c) for c in out["correlation"])
