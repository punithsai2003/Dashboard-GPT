"""The chart spec: the single format shared by the AI, the manual editor and the renderer.

Whatever produces a spec (Gemini or the user), it is validated here against
the real columns before anything is drawn. Small problems are fixed
automatically and explained; impossible specs are rejected.
"""
from __future__ import annotations

import re
from typing import Any, List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

CHART_TYPES = ["bar", "hbar", "line", "area", "pie", "donut", "scatter"]
TYPE_LABELS = {"bar": "Bar (vertical)", "hbar": "Bar (horizontal)", "line": "Line", "area": "Area",
               "pie": "Pie", "donut": "Donut", "scatter": "Scatter"}
AGGS = ["sum", "mean", "median", "count", "min", "max", "nunique"]
AGG_LABELS = {"sum": "Sum", "mean": "Average", "median": "Median", "count": "Count of rows",
              "min": "Minimum", "max": "Maximum", "nunique": "Distinct count"}
AGG_WORD = {"sum": "Total", "mean": "Average", "median": "Median", "count": "Count",
            "min": "Minimum", "max": "Maximum", "nunique": "Unique"}
NUMERIC_AGGS = {"sum", "mean", "median", "min", "max"}
POWER_BI_VISUAL = {"bar": "Clustered column chart", "hbar": "Clustered bar chart", "line": "Line chart",
                   "area": "Area chart", "pie": "Pie chart", "donut": "Donut chart", "scatter": "Scatter chart"}

_TYPE_ALIASES = {"column": "bar", "vertical bar": "bar", "bar chart": "bar", "column chart": "bar",
                 "horizontal bar": "hbar", "h-bar": "hbar", "barh": "hbar", "horizontal": "hbar",
                 "line chart": "line", "area chart": "area", "pie chart": "pie", "doughnut": "donut",
                 "donut chart": "donut", "doughnut chart": "donut", "scatter plot": "scatter",
                 "scatterplot": "scatter"}
_AGG_ALIASES = {"avg": "mean", "average": "mean", "total": "sum", "distinct": "nunique",
                "count_distinct": "nunique", "distinct count": "nunique", "unique": "nunique",
                "minimum": "min", "maximum": "max"}
_NO_Y = {"", "null", "none", "count", "rows", "count of rows", "(count of rows)"}


def _norm(v) -> str:
    return re.sub(r"\s+", " ", str(v)).strip().lower()


def _agg(v):
    if v is None or _norm(v) == "":
        return "sum"
    v = _norm(v)
    return _AGG_ALIASES.get(v, v)


FILTER_OPS = ["eq", "neq", "in", "not_in", "gt", "gte", "lt", "lte", "between", "year", "month"]
_OP_ALIASES = {"=": "eq", "==": "eq", "equals": "eq", "is": "eq", "!=": "neq", "<>": "neq", "not": "neq",
               ">": "gt", ">=": "gte", "<": "lt", "<=": "lte", "not in": "not_in", "notin": "not_in",
               "range": "between"}


class FilterSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    column: str
    op: Literal["eq", "neq", "in", "not_in", "gt", "gte", "lt", "lte", "between", "year", "month"] = "eq"
    value: Any = None

    @field_validator("op", mode="before")
    @classmethod
    def _op(cls, v):
        v = _norm(v or "eq")
        return _OP_ALIASES.get(v, v)


class ChartSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: uuid4().hex[:8])
    title: str = ""
    type: Literal["bar", "hbar", "line", "area", "pie", "donut", "scatter"] = "bar"
    x: str
    y: Optional[str] = None  # None = count rows
    agg: Literal["sum", "mean", "median", "count", "min", "max", "nunique"] = "sum"
    top: Optional[int] = None
    sort: Literal["desc", "asc", "none"] = "desc"
    date_bucket: Optional[Literal["day", "week", "month", "quarter", "year"]] = None
    others: Optional[bool] = None  # group the rest as "Others" (default: pie/donut only)
    filters: List[FilterSpec] = []

    @field_validator("id", mode="before")
    @classmethod
    def _id(cls, v):
        return str(v) if v else uuid4().hex[:8]

    @field_validator("title", mode="before")
    @classmethod
    def _title(cls, v):
        return "" if v is None else str(v).strip()[:100]

    @field_validator("type", mode="before")
    @classmethod
    def _type(cls, v):
        v = _norm(v or "bar")
        return _TYPE_ALIASES.get(v, v)

    @field_validator("agg", mode="before")
    @classmethod
    def _agg_v(cls, v):
        return _agg(v)

    @field_validator("y", mode="before")
    @classmethod
    def _y(cls, v):
        return None if v is None or _norm(v) in _NO_Y else str(v)

    @field_validator("top", mode="before")
    @classmethod
    def _top(cls, v):
        if v is None or (isinstance(v, str) and _norm(v) in ("", "all", "none", "null")):
            return None
        try:
            v = int(float(v))
        except (TypeError, ValueError):
            return None
        return min(v, 50) if v > 0 else None

    @field_validator("sort", mode="before")
    @classmethod
    def _sort(cls, v):
        v = _norm(v or "desc")
        return {"descending": "desc", "ascending": "asc"}.get(v, v)

    @field_validator("filters", mode="before")
    @classmethod
    def _filters(cls, v):
        return v if isinstance(v, list) else []

    @field_validator("date_bucket", mode="before")
    @classmethod
    def _bucket(cls, v):
        if v is None or _norm(v) in ("", "auto", "null", "none"):
            return None
        v = _norm(v)
        return {"daily": "day", "weekly": "week", "monthly": "month",
                "quarterly": "quarter", "yearly": "year", "annual": "year"}.get(v, v)


class KPISpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: uuid4().hex[:8])
    label: str = ""
    column: Optional[str] = None
    agg: Literal["sum", "mean", "median", "count", "min", "max", "nunique"] = "sum"
    filters: List[FilterSpec] = []

    @field_validator("id", mode="before")
    @classmethod
    def _id(cls, v):
        return str(v) if v else uuid4().hex[:8]

    @field_validator("filters", mode="before")
    @classmethod
    def _filters(cls, v):
        return v if isinstance(v, list) else []

    @field_validator("agg", mode="before")
    @classmethod
    def _agg_v(cls, v):
        return _agg(v)

    @field_validator("column", mode="before")
    @classmethod
    def _col(cls, v):
        return None if v is None or _norm(v) in _NO_Y else str(v)


# ------------------------------------------------------------ helpers
def match_column(name, profile) -> Optional[str]:
    """Exact match first, then ignore case, spaces and underscores."""
    if name is None:
        return None
    cols = profile["columns"]
    if name in cols:
        return name
    key = re.sub(r"[\s_]+", "", str(name).lower())
    for c in cols:
        if re.sub(r"[\s_]+", "", c.lower()) == key:
            return c
    return None


def value_label(spec: dict) -> str:
    if spec.get("type") == "scatter":
        return spec.get("y") or ""
    if not spec.get("y") or spec.get("agg") == "count":
        return "Count of rows"
    return f"{AGG_WORD[spec['agg']]} {spec['y']}"


def default_title(spec: dict) -> str:
    x, y, agg, top = spec["x"], spec.get("y"), spec["agg"], spec.get("top")
    if spec["type"] == "scatter":
        return f"{y} vs {x}"
    measure = y if (y and agg != "count") else "count"
    if top:
        return f"Top {top} {x} by {measure}"
    if not y or agg == "count":
        return f"Count of rows by {x}"
    return f"{AGG_WORD[agg]} {y} by {x}"


def check_filters(filters, profile):
    """Resolve column names and check each filter fits its column. Returns (filters, errors)."""
    out, errors = [], []
    for f in filters:
        f = f.model_dump() if hasattr(f, "model_dump") else dict(f)
        col = match_column(f.get("column"), profile)
        if not col:
            errors.append(f"filter column “{f.get('column')}” doesn't exist")
            continue
        t = profile["columns"][col]["type"]
        op = f["op"]
        if op in ("year", "month") and t != "date":
            errors.append(f"a {op} filter needs a date column, and “{col}” isn't one")
            continue
        if op in ("gt", "gte", "lt", "lte", "between") and t not in ("numeric", "date"):
            errors.append(f"“{col}” isn't a number or date, so it can't be compared with {op}")
            continue
        if op == "between" and not (isinstance(f["value"], list) and len(f["value"]) == 2):
            errors.append("a between filter needs two values, like [1000, 5000]")
            continue
        if f["value"] is None or f["value"] == []:
            errors.append(f"the filter on “{col}” has no value")
            continue
        out.append({"column": col, "op": op, "value": f["value"]})
    return out, errors


def describe_filters(filters) -> str:
    words = {"eq": "=", "neq": "≠", "gt": ">", "gte": "≥", "lt": "<", "lte": "≤", "in": "in",
             "not_in": "not in", "between": "between", "year": "year", "month": "month"}
    parts = []
    for f in filters or []:
        v = f["value"]
        if isinstance(v, list):
            v = " and ".join(map(str, v)) if f["op"] == "between" else ", ".join(map(str, v))
        parts.append(f"{f['column']} {words[f['op']]} {v}")
    return "; ".join(parts)


def _short_error(e: ValidationError) -> str:
    err = e.errors()[0]
    field = ".".join(str(p) for p in err.get("loc", [])) or "spec"
    return f"invalid value for “{field}” ({err.get('msg', 'invalid')})"


# ---------------------------------------------------------- validation
def validate_chart(raw, profile):
    """Return (spec dict or None, notes, errors)."""
    notes: list[str] = []
    try:
        spec = ChartSpec.model_validate(raw)
    except ValidationError as e:
        return None, notes, [_short_error(e)]

    cols = profile["columns"]
    x = match_column(spec.x, profile)
    if not x:
        return None, notes, [f"there is no column called “{spec.x}”"]
    spec.x = x
    if spec.y is not None:
        y = match_column(spec.y, profile)
        if not y:
            return None, notes, [f"there is no column called “{spec.y}”"]
        spec.y = y
    xt = cols[x]["type"]
    yt = cols[spec.y]["type"] if spec.y else None
    filters, ferrs = check_filters(spec.filters, profile)
    if ferrs:
        return None, notes, ferrs

    if xt == "empty":
        return None, notes, [f"“{x}” has no data"]

    if spec.type == "scatter":
        if xt != "numeric" or yt != "numeric":
            return None, notes, ["a scatter chart needs number columns on both X and Y"]
        spec.top = None
    else:
        if spec.agg == "count":
            spec.y = None
        elif spec.y is None:
            spec.agg = "count"
        elif spec.agg in NUMERIC_AGGS and yt != "numeric":
            notes.append(f"“{spec.y}” isn't a number column, so I counted its distinct values instead")
            spec.agg = "nunique"

        if spec.type in ("line", "area") and xt not in ("date", "numeric"):
            notes.append(f"line and area charts need dates or numbers on the X axis, so “{x}” is shown as a bar chart")
            spec.type = "bar"

        if xt == "date":
            spec.top = None
        else:
            unique = cols[x]["unique"]
            if spec.type in ("pie", "donut") and unique > 8 and (spec.top is None or spec.top > 8):
                spec.top = 8
                notes.append("pie and donut charts show at most 8 slices, so the rest are grouped as “Others”")
            elif spec.type in ("bar", "hbar") and spec.top is None and unique > 25:
                spec.top = 15
                notes.append(f"“{x}” has {unique} values, so I showed the top 15")

    d = spec.model_dump()
    d["filters"] = filters
    if not d["title"]:
        d["title"] = default_title(d)
    return d, notes, []


def validate_kpi(raw, profile):
    try:
        k = KPISpec.model_validate(raw)
    except ValidationError as e:
        return None, [_short_error(e)]
    if k.column is not None:
        col = match_column(k.column, profile)
        if not col:
            return None, [f"there is no column called “{k.column}”"]
        k.column = col
    if k.agg in NUMERIC_AGGS:
        if not k.column or profile["columns"][k.column]["type"] != "numeric":
            return None, [f"“{k.label or k.column}” needs a number column"]
    if k.agg == "nunique" and not k.column:
        return None, ["a distinct count needs a column"]
    filters, ferrs = check_filters(k.filters, profile)
    if ferrs:
        return None, ferrs
    d = k.model_dump()
    d["filters"] = filters
    if not d["label"]:
        d["label"] = "Rows" if not k.column else f"{AGG_WORD[k.agg]} {k.column}"
    return d, []


def validate_dashboard(raw, profile):
    """Return (dashboard dict or None, notes, errors)."""
    if not isinstance(raw, dict):
        return None, [], ["the dashboard wasn't in the expected format"]
    notes, errors, kpis, charts = [], [], [], []
    for k in (raw.get("kpis") or [])[:6]:
        spec, errs = validate_kpi(k, profile) if isinstance(k, dict) else (None, ["invalid KPI"])
        if spec:
            kpis.append(spec)
        errors += [f"KPI skipped: {e}" for e in errs]
    for i, c in enumerate((raw.get("charts") or [])[:12], 1):
        if not isinstance(c, dict):
            errors.append(f"Chart {i} skipped: invalid format")
            continue
        spec, n, errs = validate_chart(c, profile)
        notes += [f"Chart {i}: {m}" for m in n]
        errors += [f"Chart {i} skipped: {e}" for e in errs]
        if spec:
            charts.append(spec)
    title = str(raw.get("title") or "My Dashboard").strip()[:80]
    return {"title": title, "kpis": kpis, "charts": charts}, notes, errors
