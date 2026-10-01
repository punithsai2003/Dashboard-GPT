"""Step 4: turn a validated spec into numbers (pandas) and a chart (Plotly).

aggregate() is the only place chart numbers are computed. The AI never does maths.
"""
from __future__ import annotations

import math
import re

import pandas as pd
import plotly.express as px

from formatting import fmt_full, fmt_num
from spec import value_label

# Glass-blue palette: blues first, with a few contrasting accents for pies.
# Forest palette: lime first, then greens, teal, cyan and warm accents for pies.
PALETTE = ["#A3E635", "#34D399", "#22D3EE", "#FACC15", "#4ADE80",
           "#2DD4BF", "#BEF264", "#FB923C", "#60A5FA", "#94A3B8"]
FREQ = {"day": "D", "week": "W", "month": "M", "quarter": "Q", "year": "Y"}


def auto_bucket(dates: pd.Series) -> str:
    d = dates.dropna()
    if d.empty:
        return "month"
    span = (d.max() - d.min()).days
    if span <= 45:
        return "day"
    if span <= 180:
        return "week"
    if span <= 1100:
        return "month"
    if span <= 2200:
        return "quarter"
    return "year"


def _date_label(ts: pd.Timestamp, bucket: str) -> str:
    if bucket == "day":
        return ts.strftime("%d %b %Y")
    if bucket == "week":
        return ts.strftime("%d %b %Y")
    if bucket == "month":
        return ts.strftime("%b %Y")
    if bucket == "quarter":
        return f"Q{ts.quarter} {ts.year}"
    return str(ts.year)


def _plain_label(v) -> str:
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _grouped(df: pd.DataFrame, key: pd.Series, spec: dict) -> pd.Series:
    y, agg = spec.get("y"), spec["agg"]
    g = df.groupby(key, dropna=True)
    if agg == "count" or not y:
        return g.size()
    if agg == "nunique":
        return g[y].nunique()
    return g[y].agg(agg)


def _single_value(sub: pd.DataFrame, spec: dict) -> float:
    y, agg = spec.get("y"), spec["agg"]
    if agg == "count" or not y:
        return float(len(sub))
    if agg == "nunique":
        return float(sub[y].nunique())
    return float(sub[y].agg(agg))


MONTHS = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"], 1)}


def _as_list(v):
    return v if isinstance(v, list) else [v]


def _cast(v, ctype):
    if ctype == "numeric":
        return float(str(v).replace(",", ""))
    if ctype == "date":
        text = str(v).strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}", text):  # ISO dates: year first
            return pd.to_datetime(text)
        return pd.to_datetime(text, dayfirst=True)
    return str(v).strip().lower()


def _month_number(v) -> int:
    s = str(v).strip().lower()
    if s.isdigit():
        return int(s)
    for name, n in MONTHS.items():
        if name.startswith(s[:3]):
            return n
    raise ValueError(f"unknown month “{v}”")


def apply_filters(df: pd.DataFrame, filters, profile) -> pd.DataFrame:
    """Keep only rows matching every filter (plain pandas, exact)."""
    for f in filters or []:
        col, op, value = f["column"], f["op"], f["value"]
        ctype = profile["columns"][col]["type"]
        s = df[col]
        if op == "year":
            mask = s.dt.year.isin([int(float(v)) for v in _as_list(value)])
        elif op == "month":
            mask = s.dt.month.isin([_month_number(v) for v in _as_list(value)])
        else:
            base = s if ctype in ("numeric", "date") else s.astype(str).str.strip().str.lower()
            if op in ("eq", "in", "neq", "not_in"):
                mask = base.isin([_cast(v, ctype) for v in _as_list(value)])
                if op in ("neq", "not_in"):
                    mask = ~mask & s.notna()
            elif op == "between":
                lo, hi = (_cast(v, ctype) for v in value)
                mask = base.between(lo, hi)
            else:
                v = _cast(value, ctype)
                mask = {"gt": base > v, "gte": base >= v, "lt": base < v, "lte": base <= v}[op]
        df = df[mask.fillna(False)]
    return df


def aggregate(df: pd.DataFrame, spec: dict, profile: dict) -> pd.DataFrame:
    """Return a table with columns 'label' and 'value' (or the raw x/y for scatter)."""
    df = apply_filters(df, spec.get("filters"), profile)
    x = spec["x"]
    if spec["type"] == "scatter":
        d = df[[x, spec["y"]]].dropna()
        return d.sample(5000, random_state=0) if len(d) > 5000 else d

    xtype = profile["columns"][x]["type"]
    bucket = None
    if xtype == "date":
        bucket = spec.get("date_bucket") or auto_bucket(df[x])
        key = df[x].dt.to_period(FREQ[bucket]).dt.start_time
    else:
        key = df[x]
    key = key.rename("__x__")

    res = _grouped(df, key, spec).dropna().reset_index()
    res.columns = ["label", "value"]

    ordered = xtype == "date" or (xtype == "numeric" and spec["type"] in ("line", "area"))
    if ordered:
        res = res.sort_values("label")
    elif spec.get("sort") == "desc":
        res = res.sort_values("value", ascending=False, kind="stable")
    elif spec.get("sort") == "asc":
        res = res.sort_values("value", ascending=True, kind="stable")

    top = spec.get("top")
    if top and xtype != "date" and len(res) > top:
        rest = res.iloc[top:]["label"]
        res = res.iloc[:top]
        others = spec.get("others")
        if others is None:
            others = spec["type"] in ("pie", "donut")
        if others:
            # "Others" is recomputed from the raw rows, so averages stay correct too.
            other_value = _single_value(df[key.isin(rest)], spec)
            res = pd.concat([res, pd.DataFrame({"label": ["Others"], "value": [other_value]})],
                            ignore_index=True)

    # "key" keeps the raw group value (e.g. the month's start date) for click-to-filter.
    res["key"] = [None if lbl == "Others" else lbl for lbl in res["label"]]
    if bucket:
        res["label"] = res["label"].map(lambda t: _date_label(t, bucket))
    else:
        res["label"] = res["label"].map(_plain_label)
    res["value"] = res["value"].astype(float)
    res.attrs["bucket"] = bucket
    return res.reset_index(drop=True)


def click_filter(res: pd.DataFrame, spec: dict, profile: dict, label: str):
    """Turn a clicked label into a filter for the other charts (None if not filterable)."""
    rows = res[res["label"] == str(label)]
    if rows.empty or rows["key"].iloc[0] is None:
        return None
    key, col = rows["key"].iloc[0], spec["x"]
    if profile["columns"][col]["type"] == "date":
        bucket = res.attrs.get("bucket") or "month"
        start = pd.Timestamp(key)
        end = pd.Period(start, freq=FREQ[bucket]).end_time.floor("s")
        return {"column": col, "op": "between", "value": [start.isoformat(), end.isoformat()]}
    return {"column": col, "op": "eq", "value": key if not hasattr(key, "item") else key.item()}


def _nice_ticks(vmax: float, n: int = 4):
    """Round tick values (0, 20K, 40K...) labelled in the same K/L/Cr style as the bars."""
    if not vmax or vmax <= 0:
        return None, None
    raw = vmax / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    vals = [i * step for i in range(int(vmax // step) + 1)]
    return vals, [fmt_num(v) for v in vals]


def compute_kpi(df: pd.DataFrame, kpi: dict, profile: dict | None = None):
    if kpi.get("filters") and profile:
        df = apply_filters(df, kpi["filters"], profile)
    col, agg = kpi.get("column"), kpi["agg"]
    if agg == "count":
        return len(df) if not col else int(df[col].notna().sum())
    if agg == "nunique":
        return int(df[col].nunique())
    return float(df[col].agg(agg))


def build_figure(res: pd.DataFrame, spec: dict, show_title: bool = True, highlight: str | None = None):
    """highlight: a label selected by click; other bars/slices are dimmed like in Power BI."""
    t, vl = spec["type"], value_label(spec)
    dim = "#3E5046"

    def colors(labels, base):
        if highlight is None:
            return base
        return [base if str(lbl) == highlight else dim for lbl in labels]

    if t == "scatter":
        fig = px.scatter(res, x=spec["x"], y=spec["y"], opacity=0.6,
                         color_discrete_sequence=PALETTE)
    elif t in ("pie", "donut"):
        fig = px.pie(res, names="label", values="value", hole=0.55 if t == "donut" else 0,
                     color_discrete_sequence=PALETTE)
        cols = [PALETTE[i % len(PALETTE)] for i in range(len(res))]
        if highlight is not None:
            cols = [c if str(lbl) == highlight else dim for c, lbl in zip(cols, res["label"])]
        fig.update_traces(text=res["value"].map(fmt_full), textinfo="percent",
                          textposition="inside", insidetextorientation="horizontal", sort=False,
                          marker=dict(colors=cols, line=dict(color="#16201B", width=2)),
                          pull=[0.06 if str(lbl) == highlight else 0 for lbl in res["label"]],
                          customdata=res[["label"]].to_numpy(),
                          hovertemplate="%{label}<br>" + vl + ": %{text}<extra></extra>")
    else:
        full = res["value"].map(fmt_full)
        short = res["value"].map(fmt_num)
        custom = pd.DataFrame({"l": res["label"], "f": full}).to_numpy()
        if t == "hbar":
            r = res.iloc[::-1]
            fig = px.bar(r, x="value", y="label", orientation="h", text=short.iloc[::-1],
                         color_discrete_sequence=PALETTE)
            fig.update_traces(customdata=custom[::-1], textposition="outside", cliponaxis=False,
                              marker_color=colors(r["label"], PALETTE[0]),
                              hovertemplate="%{y}<br>" + vl + ": %{customdata[1]}<extra></extra>")
            fig.update_yaxes(type="category", title=spec["x"])
            fig.update_xaxes(title=vl)
        else:
            if t == "bar":
                fig = px.bar(res, x="label", y="value", text=short, color_discrete_sequence=PALETTE)
                fig.update_traces(textposition="outside", cliponaxis=False,
                                  marker_color=colors(res["label"], PALETTE[0]))
            elif t == "line":
                fig = px.line(res, x="label", y="value", markers=True, color_discrete_sequence=PALETTE)
                if highlight is not None:
                    fig.update_traces(marker=dict(
                        size=[13 if str(l) == highlight else 6 for l in res["label"]],
                        color=[PALETTE[7] if str(l) == highlight else PALETTE[0] for l in res["label"]]))
            else:
                fig = px.area(res, x="label", y="value", color_discrete_sequence=PALETTE)
            fig.update_traces(customdata=custom,
                              hovertemplate="%{x}<br>" + vl + ": %{customdata[1]}<extra></extra>")
            fig.update_xaxes(type="category", title=spec["x"])
            fig.update_yaxes(title=vl)

    fig.update_layout(
        title=dict(text=spec.get("title", "") if show_title else "", x=0.01, font=dict(size=15)),
        template="plotly_dark", height=380 if show_title else 320,
        showlegend=t in ("pie", "donut"), barcornerradius=4,
        margin=dict(l=8, r=8, t=50 if show_title else 8, b=8),
        font=dict(family="IBM Plex Sans, Segoe UI, sans-serif", size=12, color="#E6EFE0"),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(font=dict(size=11), itemclick=False, itemdoubleclick=False),
        clickmode="event+select", dragmode=False,
        uniformtext=dict(minsize=10, mode="hide"),
        hoverlabel=dict(font_family="IBM Plex Sans, sans-serif", bgcolor="#16201B", bordercolor="#A3E635", font_color="#F0F7EA"),
    )
    axis = dict(gridcolor="rgba(255,255,255,0.08)", zerolinecolor="rgba(255,255,255,0.16)",
                linecolor="rgba(255,255,255,0.12)",
                title_font=dict(size=12, color="#A9BDB0"), tickfont=dict(size=11, color="#A9BDB0"))
    fig.update_xaxes(**axis)
    fig.update_yaxes(**axis)
    if t in ("bar", "hbar", "line", "area"):
        top_value = float(res["value"].max()) * (1.15 if t in ("bar", "hbar") else 1.05)
        vals, texts = _nice_ticks(top_value)
        value_axis = fig.update_xaxes if t == "hbar" else fig.update_yaxes
        if vals:
            value_axis(tickvals=vals, ticktext=texts, range=[min(0, float(res["value"].min()) * 1.1), top_value])
        if t != "hbar":
            longest = max((len(str(l)) for l in res["label"]), default=0)
            crowded = len(res) > 8 or len(res) * longest > 60
            fig.update_xaxes(tickangle=-40 if crowded else 0, automargin=True)
        if not show_title:  # the card header already explains the axes
            fig.update_xaxes(title=None)
            fig.update_yaxes(title=None)
    return fig
