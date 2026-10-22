"""Hiring Market Pulse dashboard. Run: uv run streamlit run app/streamlit_app.py"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))
import charts
import data
from pulse import analysis

st.set_page_config(page_title="Hiring Market Pulse", page_icon="📈", layout="wide")

ROLE_LABELS = {
    "engineering": "Software engineering",
    "data_ml": "Data & ML",
    "product": "Product",
    "design": "Design",
    "sales_marketing": "Sales & marketing",
    "operations": "Operations",
    "other": "Other / unclear",
}
SENIORITY_LABELS = {
    "intern": "Intern",
    "junior": "Junior",
    "mid": "Mid",
    "senior": "Senior",
    "staff_plus": "Staff+",
    "lead_manager": "Lead / manager",
    "unknown": "Level not stated",
}
MIN_SALARY_SAMPLE = 20

# Cards are keyed containers ("card-…", "kpi-…"); Streamlit gives each a st-key-<key> class.
st.markdown(
    """
    <style>
      .block-container { padding-top: 2rem; max-width: 1280px; }
      .st-key-hero {
        background: linear-gradient(135deg, #10233f 0%, #1c3d6e 100%);
        border-radius: 16px; padding: 28px 32px 18px;
      }
      .st-key-hero h1 { color: #ffffff; margin-bottom: 0; }
      .st-key-hero p, .st-key-hero label, .st-key-hero [data-testid="stSliderThumbValue"] p,
      .st-key-hero [data-testid="stSliderTickBar"] p { color: #d8e2f0 !important; }
      .st-key-trust-banner p { color: #ffffff !important; font-size: 0.95rem; }
      [class*="st-key-card-"], [class*="st-key-kpi-"]:not(.st-key-kpi-notes) {
        background: #ffffff; border: 1px solid #e3e7ee; border-radius: 12px;
        padding: 16px 20px; box-shadow: 0 1px 2px rgba(16, 35, 63, 0.05);
      }
      [data-testid="stMetricValue"] { font-weight: 600; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(ttl=3600, show_spinner="Loading data…")
def load() -> data.Marts:
    return data.load()


def pct(v: float | None) -> str:
    return "–" if v is None else f"{v:.0%}"


def usd(v: float | None) -> str:
    return "–" if v is None else f"${v:,.0f}"


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def show_data(df: pd.DataFrame, key: str, label: str = "Show data") -> None:
    with st.expander(label), st.container(key=f"table-{key}"):
        st.dataframe(df, hide_index=True, width="stretch")


marts = load()

with st.container(key="hero"):
    st.title("Hiring Market Pulse")
    st.markdown(
        "Monthly hiring trends from Hacker News' *“Who is hiring?”* thread, next to official "
        "U.S. job-openings data. Most posts come from startups and engineering teams in U.S. "
        "tech hubs, so read this as a view of that corner of the market."
    )
    if marts.is_empty:
        monthly = pd.DataFrame()
    else:
        monthly = marts["mart_monthly_summary"].sort_values("thread_month")
        dbt_meta = marts.metadata.get("dbt", {})
        with st.container(key="trust-banner"):
            if dbt_meta:
                icon = "✅" if dbt_meta.get("tests_failed", 0) == 0 else "⚠️"
                warned = dbt_meta.get("tests_warned", 0)
                st.markdown(
                    f"{icon} **{dbt_meta.get('tests_passed', 0)} of "
                    f"{dbt_meta.get('tests_total', 0)}** data checks passed on the last "
                    "refresh" + (f" · {warned} flagged for review" if warned else "") + " · "
                    f"updated {str(marts.metadata.get('exported_at', ''))[:10]}"
                )
        months = list(monthly["thread_month"].dt.to_pydatetime())
        start, end = st.select_slider(
            "Months shown",
            options=months,
            value=(months[0], months[-1]),
            format_func=lambda d: d.strftime("%b %Y"),
            key="month-range",
        )

if marts.is_empty:
    with st.container(key="empty-state"):
        if marts.error:
            st.warning(
                f"Couldn't load the published data from `{marts.source}`. "
                f"Try again in a few minutes.\n\n`{marts.error}`"
            )
        else:
            st.info(
                "No data has been published yet. Run the refresh pipeline "
                "(`pulse ingest → extract → load-warehouse → dbt build → export-marts`) "
                "and reload."
            )
    st.stop()

in_range = monthly[(monthly["thread_month"] >= start) & (monthly["thread_month"] <= end)]


def clip(df: pd.DataFrame, col: str = "thread_month") -> pd.DataFrame:
    return df[(df[col] >= start) & (df[col] <= end)]


tab_overview, tab_skills, tab_salary, tab_benchmark, tab_quality = st.tabs(
    ["Overview", "Skills & roles", "Salaries", "HN vs official data", "Data quality"]
)

# ---- overview -----------------------------------------------------------------
with tab_overview:
    result = analysis.headline_kpis(monthly, start, end)
    if result is None:
        st.info("The selected range has no complete month yet. Widen the range.", icon="ℹ️")
    else:
        since = f"{result.compared_with:%b %Y}" if result.compared_with is not None else None
        with st.container(key="overview-heading"):
            st.subheader(f"{result.month:%B %Y}")
            st.caption(
                (
                    f"Changes are measured from {since}, the first month in your range. "
                    if since
                    else "Pick a wider range to see changes over time. "
                )
                + "Counts are company posts; one post can cover several jobs."
            )
        row = monthly[monthly["thread_month"] == result.month].iloc[0]
        salary_n = int(row.get("salary_sample_size", 0) or 0)
        kpi_help = {
            "Job posts": "Top-level replies in the month's thread, one per company.",
            "Remote-friendly": "Posts where at least one role can be done remotely, including "
            "remote limited to certain countries (e.g. 'Remote, US only').",
            "List a salary": "Posts that state a salary or hourly rate.",
            "Median posted salary (USD)": "Middle value of the posted USD annual ranges "
            "(midpoint of each range). Ranges are most often posted in states that require "
            "them (CA, NY, WA, CO), which pay above average.",
        }
        # label -> (test key, value format, change format)
        kpi_formats = {
            "Job posts": ("posts", lambda v: f"{v:,.0f}", lambda d: f"{d:+,.0f}"),
            "Remote-friendly": ("remote", pct, lambda d: f"{100 * d:+.0f} pts"),
            "List a salary": ("salary-share", pct, lambda d: f"{100 * d:+.0f} pts"),
            "Median posted salary (USD)": ("median-salary", usd, lambda d: f"{d:+,.0f} USD"),
        }
        cols = st.columns(len(result.kpis))
        for col, k in zip(cols, result.kpis, strict=True):
            key, value_fmt, delta_fmt = kpi_formats[k.label]
            with col, st.container(key=f"kpi-{key}"):
                delta = None if k.delta is None else f"{delta_fmt(k.delta)} since {since}"
                # Neutral color: more remote work or fewer posts isn't inherently good or bad.
                st.metric(
                    k.label, value_fmt(k.value), delta, delta_color="off", help=kpi_help[k.label]
                )
        with st.container(key="kpi-notes"):
            st.caption(
                f"Median salary is based on {plural(salary_n, 'post')} with a USD annual "
                "salary. “Remote-friendly” means at least one role in the post allows remote "
                "work."
            )
            if salary_n < MIN_SALARY_SAMPLE:
                st.warning(
                    f"Only {plural(salary_n, 'post')} listed a USD annual salary in "
                    f"{result.month:%B}, too few for a reliable median.",
                    icon="⚠️",
                )

    left, right = st.columns(2)
    with left, st.container(key="card-postings"):
        st.markdown("**Job posts per month**")
        st.caption("The current month is left out until its thread closes.")
        done_in_range = in_range[in_range["is_complete_month"]]
        st.plotly_chart(
            charts.lines(done_in_range, "thread_month", {"postings": "Posts"}, y_title="posts"),
            width="stretch",
            key="chart-postings",
        )
        show_data(in_range[["thread_month", "postings", "is_complete_month"]], "postings")
    with right, st.container(key="card-work-mode"):
        st.markdown("**Remote, hybrid or onsite**")
        st.caption("Posts that don't say are left out, so the three can add up to under 100%.")
        st.plotly_chart(
            charts.lines(
                in_range,
                "thread_month",
                {"share_remote": "Remote", "share_hybrid": "Hybrid", "share_onsite": "Onsite"},
                y_title="share of posts",
                y_format=".0%",
                hover_format=".0%",
                label=pct,
            ),
            width="stretch",
            key="chart-work-mode",
        )
        show_data(
            in_range[["thread_month", "share_remote", "share_hybrid", "share_onsite"]], "work-mode"
        )

    left, right = st.columns(2)
    with left, st.container(key="card-salary-share"):
        st.markdown("**Posts that list a salary**")
        st.caption("Share of posts with a salary or hourly rate.")
        st.plotly_chart(
            charts.lines(
                in_range,
                "thread_month",
                {"share_with_salary": "With salary"},
                y_title="share of posts",
                y_format=".0%",
                hover_format=".0%",
                label=pct,
            ),
            width="stretch",
            key="chart-salary-share",
        )
    with right, st.container(key="card-median-salary"):
        st.markdown("**Median posted salary (USD, annual)**")
        st.caption("Midpoint of each posted range; posts without a USD annual salary are skipped.")
        st.plotly_chart(
            charts.lines(
                in_range,
                "thread_month",
                {"median_salary_usd": "Median"},
                y_title="USD",
                y_format="$~s",
                hover_format="$,.0f",
                label=usd,
            ),
            width="stretch",
            key="chart-median-salary",
        )

# ---- skills & roles -----------------------------------------------------------
with tab_skills:
    tech = clip(marts["mart_tech_trends"])
    window = analysis.movers_window(tech["thread_month"].nunique())
    with st.container(key="card-tech-movers"):
        st.markdown("**Which technologies are mentioned more, or less**")
        if window == 0:
            st.info("Pick a range of at least two months to compare.", icon="ℹ️")
        else:
            movers = analysis.tech_movers(tech, months=window)
            first, last = tech["thread_month"].min(), tech["thread_month"].max()
            st.caption(
                f"Share of posts mentioning each technology in the last "
                f"{plural(window, 'month')} of your range, minus the first "
                f"{plural(window, 'month')} ({first:%b %Y} → {last:%b %Y}). In percentage points."
            )
            shown = pd.concat([movers.head(8), movers.tail(6)]).drop_duplicates("tech")
            st.plotly_chart(
                charts.diverging_bars(
                    shown, "tech", "change_pts", x_title="change (percentage points)"
                ),
                width="stretch",
                key="chart-tech-movers",
            )
            show_data(movers, "tech-movers")

    with st.container(key="card-tech-compare"):
        st.markdown("**Compare technologies over time**")
        # Colors follow the technology, not its position, so removing one never repaints the rest.
        options = sorted(tech["tech"].unique())
        default_order = (
            analysis.tech_movers(tech, months=window)["tech"]
            if window
            else pd.Series(options, dtype=str)
        )
        default = [t for t in default_order.head(3) if t in options]
        picked = st.multiselect(
            "Up to 4 technologies",
            options,
            default=default,
            max_selections=4,
            key="tech-picker",
        )
        slots: dict[str, str] = st.session_state.setdefault("tech_colors", {})
        for t in list(slots):
            if t not in picked:
                del slots[t]
        for t in picked:
            if t not in slots:
                slots[t] = next(c for c in charts.SERIES if c not in slots.values())
        if picked:
            wide = (
                tech[tech["tech"].isin(picked)]
                .pivot_table(
                    index="thread_month", columns="tech", values="share_of_postings", fill_value=0.0
                )
                .reset_index()
            )
            st.plotly_chart(
                charts.lines(
                    wide,
                    "thread_month",
                    {t: t for t in picked},
                    y_title="share of posts",
                    y_format=".0%",
                    hover_format=".1%",
                    label=pct,
                    colors=slots,
                ),
                width="stretch",
                key="chart-tech-compare",
            )

    roles = clip(marts["mart_role_mix"])
    with st.container(key="card-roles"):
        st.markdown("**Kinds of roles posted**")
        st.caption("Average share of posts mentioning each kind of role. Posts often list several.")
        role_avg = (
            roles.groupby("role_family", as_index=False)["share_of_postings"]
            .mean()
            .assign(role=lambda d: d["role_family"].map(ROLE_LABELS))
            .sort_values("share_of_postings", ascending=False)
        )
        # Tables don't get an st-key class themselves, so a keyed container gives tests a handle.
        with st.container(key="table-roles"):
            st.dataframe(
                role_avg[["role", "share_of_postings"]],
                column_config={
                    "role": "Role",
                    "share_of_postings": st.column_config.ProgressColumn(
                        "Share of posts", format="percent", min_value=0, max_value=1
                    ),
                },
                hide_index=True,
                width="stretch",
            )

# ---- salaries -----------------------------------------------------------------
with tab_salary, st.container(key="card-salary-bands"):
    bands = marts["mart_salary_bands"].copy()
    st.markdown("**Posted salary ranges by role and level, last 12 months (USD, annual)**")
    st.caption(
        "Bar: middle half of posted salaries. Dot: median. Many posts don't state a level, so "
        "“Level not stated” is often the largest group. This view always covers the latest 12 "
        "months, whatever range is selected above."
    )
    only_reliable = st.toggle(
        "Only groups with at least 20 posts", value=True, key="reliable-toggle"
    )
    if only_reliable:
        bands = bands[bands["is_reliable"]]
    bands["group"] = (
        bands["primary_role_family"].map(ROLE_LABELS)
        + " · "
        + bands["seniority"].map(SENIORITY_LABELS)
    )
    if bands.empty:
        st.info("No group has enough posts with a salary yet.", icon="ℹ️")
    else:
        st.plotly_chart(charts.salary_ranges(bands), width="stretch", key="chart-salary-bands")
        show_data(
            bands[["group", "sample_size", "p25_usd", "median_usd", "p75_usd"]], "salary-bands"
        )

# ---- benchmark ----------------------------------------------------------------
with tab_benchmark, st.container(key="card-benchmark"):
    bench = clip(marts["mart_hn_vs_jolts"], "month").sort_values("month")
    st.markdown("**HN job posts vs official job openings (Information sector)**")
    st.caption(
        "Both lines start at 100 in the first month of your range. Official figures come from "
        "the Bureau of Labor Statistics (JOLTS), arrive about two months late, and the newest "
        "month is preliminary."
    )
    if len(bench) < 2:
        st.info("Not enough months with both sources in this range.", icon="ℹ️")
    else:
        base = bench.iloc[0]
        bench = bench.assign(
            hn_index=100 * bench["hn_postings"] / base["hn_postings"],
            jolts_index=100 * bench["jolts_openings_k"] / base["jolts_openings_k"],
        )
        fig = charts.lines(
            bench,
            "month",
            {"hn_index": "HN posts", "jolts_index": "JOLTS openings"},
            y_title="index (first month = 100)",
        )
        charts.mark_months(
            fig,
            list(bench.loc[bench["is_divergent"], "month"]),
            "Months the two moved very differently",
        )
        st.plotly_chart(fig, width="stretch", key="chart-benchmark")
        lags = analysis.lead_lag_correlation(bench)
        # Rank by strength in either direction; a strong negative link is still a link.
        valid = lags.dropna()
        best = valid.loc[valid["correlation"].abs().sort_values(ascending=False).index].head(1)
        with st.container(key="lead-lag"):
            if best.empty:
                st.caption("Not enough months to check whether one series leads the other.")
            else:
                b = best.iloc[0]
                lag = int(b["lag_months"])
                timing = (
                    f"HN {plural(lag, 'month')} ahead"
                    if lag > 0
                    else f"official data {plural(-lag, 'month')} ahead"
                    if lag < 0
                    else "same month"
                )
                weak = abs(b["correlation"]) < 0.5
                summary = (
                    "Month to month, the two don't move in step"
                    if weak
                    else "Month to month, the two are moderately related"
                )
                takeaway = (
                    ", so HN volume is a poor stand-in for official openings."
                    if weak
                    else ". Treat it as a hint, not a forecast."
                )
                st.markdown(
                    f"{summary}. The strongest correlation is **{b['correlation']:.2f}** "
                    f"({timing}, over {int(b['n'])} months){takeaway}"
                )
        show_data(lags, "lead-lag", "Show correlation by lag")
        show_data(bench, "benchmark", "Show monthly data")

# ---- data quality -------------------------------------------------------------
with tab_quality:
    dbt_meta = marts.metadata.get("dbt", {})
    with st.container(key="card-checks"):
        st.markdown("**Checks on every refresh**")
        st.caption(
            "Nothing is published unless the hard checks pass. If one fails, this page keeps "
            "the last good data and an issue is opened for review."
        )
        if dbt_meta:
            c1, c2, c3 = st.columns(3)
            c1.metric("Passed", dbt_meta.get("tests_passed", 0))
            c2.metric("Flagged for review", dbt_meta.get("tests_warned", 0))
            c3.metric("Failed", dbt_meta.get("tests_failed", 0))
            if dbt_meta.get("not_passing"):
                st.caption("Not passing: " + ", ".join(dbt_meta["not_passing"]))

    accuracy = marts.metadata.get("extractor_accuracy")
    if accuracy:
        with st.container(key="extractor-accuracy"), st.container(key="card-accuracy"):
            st.markdown("**How well the text is read**")
            st.caption(
                f"Fields like remote work and salary are read from free text by rules. Those "
                f"rules were checked against {accuracy['job_posts_checked']} job posts labeled "
                f"by hand. {accuracy['non_job_post_rate']:.0%} of sampled posts weren't job ads "
                "(replies, links) and are still counted."
            )
            st.dataframe(
                pd.DataFrame(
                    {
                        "Field": list(accuracy["fields"]),
                        "Accuracy": list(accuracy["fields"].values()),
                    }
                ),
                column_config={
                    "Accuracy": st.column_config.ProgressColumn(
                        format="percent", min_value=0, max_value=1
                    )
                },
                hide_index=True,
                width="stretch",
            )

    q = marts["stg_quarantine"]
    with st.container(key="card-quarantine"):
        st.markdown("**Records set aside**")
        st.caption("Records that failed an input check, such as deleted posts, with the reason.")
        if q.empty:
            st.write("None.")
        else:
            with st.container(key="table-quarantine"):
                st.dataframe(
                    q.groupby(["dataset", "reason"], as_index=False)
                    .size()
                    .rename(columns={"size": "rows"}),
                    hide_index=True,
                    width="stretch",
                )
    st.caption(
        "Salaries are posted ranges, not offers, and only USD annual ranges count toward "
        "medians. Every table and column is described in the "
        "[data docs](https://wacsvn.github.io/hiring-market-pulse/); the code and tests are on "
        "[GitHub](https://github.com/wacsvn/hiring-market-pulse)."
    )
