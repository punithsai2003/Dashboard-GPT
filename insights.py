"""AI insights: pandas computes the facts, the AI only writes the explanation.

build_facts() turns the current dashboard (with any click filter applied) into
a short, exact fact sheet: KPI values, top items and their shares, trends,
peaks and changes. The AI is told to use only these numbers.
"""
from __future__ import annotations

import pandas as pd

from charts import aggregate, apply_filters, compute_kpi
from formatting import fmt_full
from spec import describe_filters, value_label

SHARE_AGGS = {"sum", "count"}  # shares of a total only make sense for these


def _pct(part: float, whole: float) -> str:
    return f"{part / whole * 100:.1f}%" if whole else "n/a"


def _chart_facts(df, spec, profile) -> list[str]:
    title, t = spec["title"], spec["type"]
    lines = [f"Chart “{title}” ({t}): {value_label(spec)} by {spec['x']}"
             + (f", filtered where {describe_filters(spec['filters'])}" if spec.get("filters") else "")]
    res = aggregate(df, spec, profile)
    if res.empty:
        return lines + ["  - no data after filters"]

    if t == "scatter":
        corr = res[spec["x"]].corr(res[spec["y"]])
        lines.append(f"  - {len(res)} points; correlation between {spec['x']} and {spec['y']}: {corr:.2f}")
        return lines

    vals = res["value"]
    is_time = profile["columns"][spec["x"]]["type"] == "date"
    if is_time:
        series = ", ".join(f"{l}: {fmt_full(v)}" for l, v in zip(res["label"], vals))
        lines.append(f"  - values in time order: {series}")
        peak, low = res.loc[vals.idxmax()], res.loc[vals.idxmin()]
        lines.append(f"  - highest: {peak['label']} ({fmt_full(peak['value'])}); "
                     f"lowest: {low['label']} ({fmt_full(low['value'])})")
        if len(res) >= 2:
            first, prev, last = vals.iloc[0], vals.iloc[-2], vals.iloc[-1]
            if prev:
                lines.append(f"  - latest period {res['label'].iloc[-1]} vs previous: "
                             f"{(last - prev) / abs(prev) * 100:+.1f}%")
            if first:
                lines.append(f"  - first to latest period: {(last - first) / abs(first) * 100:+.1f}%")
            half = len(res) // 2
            if half >= 2:
                a, b = vals.iloc[:half].mean(), vals.iloc[-half:].mean()
                if a:
                    lines.append(f"  - average of later half vs earlier half: {(b - a) / abs(a) * 100:+.1f}%")
        return lines

    total = None
    if spec["agg"] in SHARE_AGGS or not spec.get("y"):
        full_spec = {**spec, "top": None, "others": False}
        total = float(aggregate(df, full_spec, profile)["value"].sum())
        lines.append(f"  - total across all {spec['x']} values: {fmt_full(total)}")
    for _, r in res.head(10).iterrows():
        share = f" ({_pct(r['value'], total)} of total)" if total else ""
        lines.append(f"  - {r['label']}: {fmt_full(r['value'])}{share}")
    if len(res) > 1 and vals.iloc[1]:
        lines.append(f"  - #1 is {vals.iloc[0] / vals.iloc[1]:.1f}x #2")
    return lines


def build_facts(df: pd.DataFrame, profile: dict, dashboard: dict, cross: dict | None = None) -> str:
    """Exact fact sheet for the dashboard as the user currently sees it."""
    out = [f"Dashboard: {dashboard['title']}",
           f"Dataset: {profile['rows']:,} rows, {profile['n_cols']} columns"]
    dates = [(c, i) for c, i in profile["columns"].items() if i["type"] == "date"]
    for c, i in dates:
        out.append(f"Date range of {c}: {i['min']} to {i['max']}")

    view = df
    if cross:
        view = apply_filters(df, [cross["filter"]], profile)
        out.append(f"ACTIVE CLICK FILTER: only rows where {cross['column']} = {cross['label']} "
                   f"({len(view):,} of {len(df):,} rows). Explain the dashboard for this selection.")
        if len(view) < 30:
            out.append("Note: the selection is small, so patterns may not be reliable.")

    if dashboard["kpis"]:
        out.append("KPIs:")
        for k in dashboard["kpis"]:
            try:
                out.append(f"  - {k['label']}: {fmt_full(compute_kpi(view, k, profile))}")
            except Exception:
                pass
    for spec in dashboard["charts"]:
        # The clicked chart itself stays unfiltered (its selection is only highlighted).
        data = df if cross and spec.get("id") == cross.get("source") else view
        try:
            out += _chart_facts(data, spec, profile)
        except Exception as e:
            out.append(f"Chart “{spec.get('title')}”: could not compute ({e})")
    return "\n".join(out)
