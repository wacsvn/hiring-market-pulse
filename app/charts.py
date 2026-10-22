"""Plotly chart builders.

Palette and mark specs follow a validated reference palette: categorical hues in a
fixed order (never cycled), one y-axis per chart, thin 2px lines, recessive grid,
direct labels at line ends, and text in ink colors rather than series colors.
"""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd
import plotly.graph_objects as go

SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]  # validated: first 4 categorical slots
DIVERGING_UP, DIVERGING_DOWN = "#2a78d6", "#e34948"
SURFACE = "#ffffff"  # charts sit on white cards
INK, INK_2, MUTED = "#0b0b0b", "#52514e", "#898781"
GRID, AXIS = "#e1e0d9", "#c3c2b7"
FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'


def _base(fig: go.Figure, *, y_title: str, y_format: str | None = None, height: int = 340) -> None:
    fig.update_layout(
        height=height,
        margin={"l": 8, "r": 150, "t": 8, "b": 8},  # right margin leaves room for end labels
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        font={"family": FONT, "color": INK_2, "size": 13},
        hovermode="x unified",
        hoverlabel={"bgcolor": "white", "font": {"color": INK}},
        legend={"orientation": "h", "y": 1.08, "x": 0, "font": {"color": INK_2}},
        showlegend=True,
    )
    fig.update_xaxes(showgrid=False, linecolor=AXIS, tickfont={"color": MUTED})
    fig.update_yaxes(
        title={"text": y_title, "font": {"color": MUTED, "size": 12}},
        gridcolor=GRID,
        zeroline=False,
        tickfont={"color": MUTED},
        tickformat=y_format,
        rangemode="tozero",
    )


def lines(
    df: pd.DataFrame,
    x: str,
    series: dict[str, str],
    *,
    y_title: str,
    y_format: str | None = None,
    hover_format: str = ",.0f",
    label: Callable[[float], str] = lambda v: f"{v:,.0f}",
    colors: dict[str, str] | None = None,
) -> go.Figure:
    """One line per column in `series` ({column: label}), each labelled at its last point."""
    fig = go.Figure()
    for i, (col, name) in enumerate(series.items()):
        color = (colors or {}).get(col, SERIES[i])
        d = df[[x, col]].dropna()
        fig.add_trace(
            go.Scatter(
                x=d[x],
                y=d[col],
                name=name,
                mode="lines",
                line={"color": color, "width": 2},
                hovertemplate=f"{name}: %{{y:{hover_format}}}<extra></extra>",
            )
        )
        if not d.empty:
            last = d.iloc[-1]
            fig.add_annotation(
                x=last[x],
                y=last[col],
                text=f"{name} {label(float(last[col]))}",
                showarrow=False,
                xanchor="left",
                xshift=6,
                font={"color": INK_2, "size": 12},
            )
    _base(fig, y_title=y_title, y_format=y_format)
    fig.update_layout(showlegend=len(series) >= 2)
    if not df.empty:  # don't let autorange pad the time axis past the data
        fig.update_xaxes(range=[df[x].min(), df[x].max()])
    return fig


def diverging_bars(df: pd.DataFrame, label: str, value: str, *, x_title: str) -> go.Figure:
    """Horizontal bars for a signed change; blue = up, red = down, gray zero line."""
    d = df.sort_values(value)
    colors = [DIVERGING_UP if v >= 0 else DIVERGING_DOWN for v in d[value]]
    fig = go.Figure(
        go.Bar(
            x=d[value],
            y=d[label],
            orientation="h",
            marker={"color": colors},
            hovertemplate="%{y}: %{x:+.1f} pts<extra></extra>",
            text=[f"{v:+.1f}" for v in d[value]],
            textposition="outside",
            textfont={"color": INK_2},
        )
    )
    _base(fig, y_title="", height=max(260, 26 * len(d)))
    fig.update_layout(showlegend=False, hovermode="closest", bargap=0.35)
    fig.update_xaxes(
        title={"text": x_title, "font": {"color": MUTED, "size": 12}},
        zeroline=True,
        zerolinecolor=AXIS,
        showgrid=True,
        gridcolor=GRID,
    )
    fig.update_yaxes(gridcolor="rgba(0,0,0,0)", rangemode=None)
    return fig


def salary_ranges(df: pd.DataFrame) -> go.Figure:
    """Interquartile range (bar) with a median marker per group, single hue."""
    d = df.sort_values("median_usd")
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            y=d["group"],
            x=d["p75_usd"] - d["p25_usd"],
            base=d["p25_usd"],
            orientation="h",
            marker={"color": "#b7d3f6"},
            name="Middle 50% of posts",
            customdata=d[["p25_usd", "p75_usd", "sample_size"]],
            hovertemplate=(
                "%{y}<br>25th–75th: $%{customdata[0]:,.0f}–$%{customdata[1]:,.0f}"
                "<br>posts with salary: %{customdata[2]}<extra></extra>"
            ),
        )
    )
    fig.add_trace(
        go.Scatter(
            y=d["group"],
            x=d["median_usd"],
            mode="markers",
            name="Median",
            marker={"color": SERIES[0], "size": 10, "line": {"color": SURFACE, "width": 2}},
            hovertemplate="median $%{x:,.0f}<extra></extra>",
        )
    )
    _base(fig, y_title="", height=max(260, 34 * len(d)))
    fig.update_layout(hovermode="closest", bargap=0.45)
    fig.update_xaxes(tickprefix="$", tickformat="~s", showgrid=True, gridcolor=GRID)
    fig.update_yaxes(gridcolor="rgba(0,0,0,0)", rangemode=None)
    return fig


def mark_months(fig: go.Figure, months: list[pd.Timestamp], note: str) -> None:
    """Thin muted verticals for flagged months (e.g. divergence), named in the legend."""
    for m in months:
        fig.add_vline(x=m, line={"color": MUTED, "width": 1, "dash": "dot"})
    if months:
        fig.add_trace(
            go.Scatter(
                x=[None],
                y=[None],
                mode="lines",
                name=note,
                line={"color": MUTED, "width": 1, "dash": "dot"},
            )
        )
