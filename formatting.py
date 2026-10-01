"""Number formatting helpers (Indian style: K, Lakh, Crore)."""
from __future__ import annotations

import math


def _to_float(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def fmt_num(v) -> str:
    """Short form for cards and chart labels: 1.2K, 3.45 L, 2.10 Cr."""
    f = _to_float(v)
    if f is None:
        return "–" if v is None else str(v)
    sign = "-" if f < 0 else ""
    a = abs(f)
    if a >= 1e7:
        return f"{sign}{a / 1e7:.2f} Cr"
    if a >= 1e5:
        return f"{sign}{a / 1e5:.2f} L"
    if a >= 1e3:
        return f"{sign}{a / 1e3:.1f}K"
    if a.is_integer():
        return f"{sign}{int(a)}"
    return f"{sign}{a:.2f}"


def fmt_full(v) -> str:
    """Full number with Indian digit grouping: 12,34,567.89"""
    f = _to_float(v)
    if f is None:
        return "–" if v is None else str(v)
    sign = "-" if f < 0 else ""
    a = abs(f)
    if a.is_integer():
        whole, dec = str(int(a)), ""
    else:
        whole, dec = f"{a:.2f}".split(".")
        dec = "." + dec
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{sign}{whole}{dec}"
