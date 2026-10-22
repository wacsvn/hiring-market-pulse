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


@st.cache_data(ttl=3600, show_spinner="Loading data…")
def load() -> data.Marts:
    return data.load()


def pct(v: float | None) -> str:
    return "–" if v is None else f"{v:.0%}"


def usd(v: float | None) -> str:
    return "–" if v is None else f"${v:,.0f}"


def show_data(df: pd.DataFrame, key: str, label: str = "Show data") -> None:
    with st.expander(label), st.container(key=f"table-{key}"):
        st.dataframe(df, hide_index=True, width="stretch")


marts = load()

st.title("Hiring Market Pulse")
st.caption(
    "Trends in the companies that post in Hacker News' monthly *“Who is hiring?”* thread "
    "(mostly startups and engineering-heavy, concentrated in U.S. tech hubs), compared with "
    "official U.S. job-openings data (BLS JOLTS). This is a slice of the tech market, not "
    "all of it."
)
MIN_SALARY_SAMPLE = 20

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

monthly = marts["mart_monthly_summary"].sort_values("thread_month")
dbt_meta = marts.metadata.get("dbt", {})

# ---- trust banner + filter row ------------------------------------------------
with st.container(key="trust-banner"):
    if dbt_meta:
        failed = dbt_meta.get("tests_failed", 0)
        icon = "✅" if failed == 0 else "⚠️"
        st.markdown(
            f"{icon} **{dbt_meta.get('tests_passed', 0)} of {dbt_meta.get('tests_total', 0)}** "
            f"data-quality checks passed on the last refresh"
            + (
                f" · {dbt_meta.get('tests_warned', 0)} flagged for review"
                if dbt_meta.get("tests_warned")
                else ""
            )
            + f" · data as of {str(marts.metadata.get('exported_at', ''))[:10]}"
        )

months = list(monthly["thread_month"].dt.to_pydatetime())
start, end = st.select_slider(
    "Months shown",
    options=months,
    value=(months[0], months[-1]),
    format_func=lambda d: d.strftime("%b %Y"),
    key="month-range",
)
in_range = monthly[(monthly["thread_month"] >= start) & (monthly["thread_month"] <= end)]


def clip(df: pd.DataFrame, col: str = "thread_month") -> pd.DataFrame:
    return df[(df[col] >= start) & (df[col] <= end)]


tab_overview, tab_skills, tab_salary, tab_benchmark, tab_quality = st.tabs(
    ["Overview", "Skills & roles", "Salaries", "HN vs official data", "Data quality"]
)

# ---- overview -----------------------------------------------------------------
with tab_overview:
    kpis = analysis.headline_kpis(monthly)
    latest = analysis.complete_months(monthly).iloc[-1]["thread_month"]
    st.subheader(f"Latest complete month: {latest:%B %Y}")
    st.caption(
        "Each number counts company posts, not individual openings. The same kind of "
        "company posts every month, so changes over time are more meaningful than the levels."
    )
    latest_row = analysis.complete_months(monthly).iloc[-1]
    salary_n = int(latest_row.get("salary_sample_size", 0) or 0)
    salary_posts = f"{salary_n} post{'' if salary_n == 1 else 's'}"
    kpi_help = {
        "Job posts": "Top-level replies in the month's thread. One post often covers several "
        "roles.",
        "Remote-friendly": "Share of posts where at least one role allows remote work, "
        "including country-restricted remote (e.g. 'Remote, US only').",
        "List a salary": "Share of posts stating a salary or hourly rate.",
        "Median posted salary (USD)": f"Median of the midpoints of posted USD annual ranges, "
        f"from the {salary_posts} that listed one. Posts with salaries skew toward states "
        "with pay-transparency laws (CA, NY, WA, CO), which are high-pay markets.",
    }
    # label -> (test key, value format, year-over-year change format)
    kpi_formats = {
        "Job posts": ("posts", lambda v: f"{v:,.0f}", lambda d: f"{d:+,.0f}"),
        "Remote-friendly": ("remote", pct, lambda d: f"{100 * d:+.0f} pts"),
        "List a salary": ("salary-share", pct, lambda d: f"{100 * d:+.0f} pts"),
        "Median posted salary (USD)": ("median-salary", usd, lambda d: f"{d:+,.0f} USD"),
    }
    cols = st.columns(len(kpis))
    for col, k in zip(cols, kpis, strict=True):
        key, value_fmt, delta_fmt = kpi_formats[k.label]
        with col, st.container(key=f"kpi-{key}"):
            delta = None if k.delta is None else f"{delta_fmt(k.delta)} vs a year ago"
            # Neutral color: more remote work or fewer posts isn't inherently "good" or "bad".
            st.metric(k.label, value_fmt(k.value), delta, delta_color="off", help=kpi_help[k.label])
    with st.container(key="kpi-notes"):
        st.caption(
            f"Median salary is based on {salary_posts} with a USD annual salary. "
            "“Remote-friendly” means at least one role in the post allows remote work."
        )
        if salary_n < MIN_SALARY_SAMPLE:
            st.warning(
                f"Only {salary_posts} listed a USD annual salary this month, too few for a "
                "reliable median.",
                icon="⚠️",
            )

    left, right = st.columns(2)
    with left:
        st.markdown("**Job posts per month**")
        st.caption(
            "Top-level replies to each month's thread; each is one company's post. "
            "The current month is left out until it ends."
        )
        done_in_range = in_range[in_range["is_complete_month"]]
        st.plotly_chart(
            charts.lines(done_in_range, "thread_month", {"postings": "Posts"}, y_title="posts"),
            width="stretch",
            key="chart-postings",
        )
        show_data(in_range[["thread_month", "postings", "is_complete_month"]], "postings")
    with right:
        st.markdown("**How the work happens**")
        st.caption(
            "Share of posts by work arrangement. “Remote” = at least one role allows remote "
            "work. Posts that don't say are left out, so shares can add up to under 100%."
        )
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
    with left:
        st.markdown("**Pay transparency**")
        st.caption("Share of posts that state a salary or hourly rate.")
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
    with right:
        st.markdown("**Median posted salary (USD, annual)**")
        st.caption("Midpoint of posted USD annual ranges. Posts without a salary are excluded.")
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
    movers = analysis.tech_movers(tech, months=6)
    st.markdown("**Biggest movers in technology mentions**")
    st.caption(
        "Change in the share of posts mentioning each technology between the first and last "
        "6 months of the selected range, in percentage points."
    )
    shown = pd.concat([movers.head(8), movers.tail(6)]).drop_duplicates("tech")
    st.plotly_chart(
        charts.diverging_bars(shown, "tech", "change_pts", x_title="change (percentage points)"),
        width="stretch",
        key="chart-tech-movers",
    )
    show_data(movers, "tech-movers")

    # Colors follow the technology, not its position, so removing one never repaints the rest.
    options = sorted(tech["tech"].unique())
    default = [t for t in movers["tech"].head(3) if t in options]
    picked = st.multiselect(
        "Compare technologies (up to 4)",
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
    st.markdown("**Who is being hired**")
    st.caption("Share of posts mentioning each kind of role (a post can list several).")
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
                "share_of_postings": st.column_config.ProgressColumn(
                    "Average share of posts", format="percent", min_value=0, max_value=1
                )
            },
            hide_index=True,
            width="stretch",
        )

# ---- salaries -----------------------------------------------------------------
with tab_salary:
    bands = marts["mart_salary_bands"].copy()
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
    st.markdown("**Posted salary ranges, last 12 months (USD, annual)**")
    st.caption(
        "Bar = middle 50% of posted salary midpoints; dot = median. Only posts with a USD "
        "annual salary count, and those skew toward high-pay states with pay-transparency "
        "laws. Seniority is often not stated, so many posts land in “Level not stated”."
    )
    if bands.empty:
        st.info("No group has enough posts with a salary yet.", icon="ℹ️")
    else:
        st.plotly_chart(charts.salary_ranges(bands), width="stretch", key="chart-salary-bands")
        show_data(
            bands[["group", "sample_size", "p25_usd", "median_usd", "p75_usd"]], "salary-bands"
        )

# ---- benchmark ----------------------------------------------------------------
with tab_benchmark:
    bench = clip(marts["mart_hn_vs_jolts"], "month").sort_values("month")
    st.markdown("**HN job posts vs official job openings (Information sector)**")
    st.caption(
        "Both series indexed to 100 at the first month shown by both. JOLTS is the Bureau of "
        "Labor Statistics' monthly survey of job openings; it is published with a ~2 month "
        "lag, and its latest month is preliminary."
    )
    if len(bench) < 2:
        st.info("Not enough overlapping months to compare yet.", icon="ℹ️")
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
                st.caption("Not enough months to estimate whether one series leads the other.")
            else:
                b = best.iloc[0]
                lag = int(b["lag_months"])
                direction = (
                    "HN posts lead official openings"
                    if lag > 0
                    else "official openings lead HN posts"
                    if lag < 0
                    else "the two move in the same month"
                )
                strength = "weak" if abs(b["correlation"]) < 0.5 else "moderate"
                st.markdown(
                    f"Strongest month-over-month correlation: **{b['correlation']:.2f}** at a "
                    f"lag of **{lag:+d} months** ({direction}), over {int(b['n'])} months. "
                    f"That is a {strength} link: month-to-month, HN volume is not a reliable "
                    "stand-in for official openings. HN is a self-selected slice of the market."
                )
        show_data(lags, "lead-lag", "Show correlation by lag")
        show_data(bench, "benchmark", "Show monthly data")

# ---- data quality -------------------------------------------------------------
with tab_quality:
    st.markdown("**Can I trust these numbers?**")
    st.write(
        "Every refresh runs automated checks before anything is published. If a hard check "
        "fails, the dashboard keeps showing the last good data and an issue is opened."
    )
    if dbt_meta:
        c1, c2, c3 = st.columns(3)
        c1.metric("Checks passed", dbt_meta.get("tests_passed", 0))
        c2.metric("Flagged for review", dbt_meta.get("tests_warned", 0))
        c3.metric("Failed", dbt_meta.get("tests_failed", 0))
        if dbt_meta.get("not_passing"):
            st.caption("Not passing: " + ", ".join(dbt_meta["not_passing"]))
    q = marts["stg_quarantine"]
    st.markdown("**Rows set aside by the input checks**")
    st.caption(
        "Records that failed a data contract (e.g. deleted posts) are kept here with "
        "the reason instead of silently disappearing."
    )
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
    st.markdown(
        "**Method notes.** Fields are extracted from free text by a rules-based extractor, so "
        "some posts are misread (seniority especially). Salaries are posted ranges, not "
        "offers. HN skews toward startups and software roles."
    )
