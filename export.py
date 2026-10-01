"""Step 5: export the dashboard as PDF, interactive HTML, or a Power BI-ready Excel file.

Charts in the PDF are drawn with matplotlib from the same aggregated numbers
as the on-screen charts, so the exports always match the dashboard.
"""
from __future__ import annotations

import html
import io
import re
from datetime import datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from fpdf import FPDF  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

from charts import PALETTE, aggregate, build_figure, compute_kpi  # noqa: E402
from formatting import fmt_num  # noqa: E402
from profiler import profile_table  # noqa: E402
from spec import AGG_LABELS, POWER_BI_VISUAL, TYPE_LABELS, describe_filters, value_label  # noqa: E402


def _short(label, n=18) -> str:
    s = str(label)
    return s if len(s) <= n else s[: n - 1] + "…"


# -------------------------------------------------------------------- PDF
def _chart_png(res: pd.DataFrame, spec: dict) -> bytes:
    fig, ax = plt.subplots(figsize=(7, 4.6), dpi=150)
    t = spec["type"]
    money = FuncFormatter(lambda v, _: fmt_num(v))

    if t == "scatter":
        ax.scatter(res[spec["x"]], res[spec["y"]], s=12, alpha=0.6, color=PALETTE[0])
        ax.set_xlabel(spec["x"])
        ax.set_ylabel(spec["y"])
        ax.yaxis.set_major_formatter(money)
    elif t in ("pie", "donut"):
        r = res[res["value"] > 0]
        ax.pie(r["value"], labels=[_short(v, 16) for v in r["label"]], autopct="%1.0f%%",
               startangle=90, counterclock=False, colors=PALETTE[: len(r)],
               wedgeprops={"width": 0.45} if t == "donut" else None, textprops={"fontsize": 8})
        ax.axis("equal")
    else:
        labels = [_short(v) for v in res["label"]]
        values = res["value"].tolist()
        pos = list(range(len(values)))
        if t == "hbar":
            bars = ax.barh(pos[::-1], values, color=PALETTE[0])
            ax.set_yticks(pos[::-1], labels, fontsize=8)
            ax.bar_label(bars, labels=[fmt_num(v) for v in values], fontsize=7, padding=2)
            ax.xaxis.set_major_formatter(money)
            ax.set_xlabel(value_label(spec))
        else:
            if t == "bar":
                bars = ax.bar(pos, values, color=PALETTE[0])
                ax.bar_label(bars, labels=[fmt_num(v) for v in values], fontsize=7, padding=2)
            elif t == "line":
                ax.plot(pos, values, marker="o", color=PALETTE[0], linewidth=2, markersize=4)
            else:
                ax.fill_between(pos, values, alpha=0.3, color=PALETTE[0])
                ax.plot(pos, values, color=PALETTE[0], linewidth=2)
            step = max(1, len(pos) // 12)
            ax.set_xticks(pos[::step], labels[::step], rotation=35, ha="right", fontsize=8)
            ax.yaxis.set_major_formatter(money)
            ax.set_ylabel(value_label(spec))
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.set_title(spec.get("title", ""), loc="left", fontsize=12, fontweight="bold")
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


def _latin(text) -> str:
    """The built-in PDF fonts only support Latin-1 characters."""
    text = str(text).replace("→", "->").replace("–", "-").replace("…", "...").replace("₹", "Rs.")
    return text.encode("latin-1", "replace").decode("latin-1")


def to_pdf(df, profile, dashboard, file_name) -> bytes:
    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(False)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 10, _latin(dashboard["title"]), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(100, 100, 100)
    stamp = datetime.now().strftime("%d %b %Y, %H:%M")
    pdf.cell(0, 6, _latin(f"Source: {file_name}  |  {profile['rows']:,} rows  |  Generated {stamp}"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    y = pdf.get_y() + 3

    kpis = dashboard["kpis"]
    if kpis:
        per_row = min(len(kpis), 4)
        w = 277 / per_row
        for i, k in enumerate(kpis):
            if i and i % per_row == 0:
                y += 24
            x = 10 + (i % per_row) * w
            try:
                val = fmt_num(compute_kpi(df, k, profile))
            except Exception:
                val = "-"
            pdf.set_draw_color(210, 210, 210)
            pdf.rect(x, y, w - 4, 20)
            pdf.set_xy(x + 3, y + 2)
            pdf.set_font("Helvetica", "", 9)
            pdf.cell(w - 10, 5, _latin(k["label"]))
            pdf.set_xy(x + 3, y + 8)
            pdf.set_font("Helvetica", "B", 15)
            pdf.cell(w - 10, 9, _latin(val))
        y += 26

    img_w = 136
    img_h = img_w * 4.6 / 7
    for i, spec in enumerate(dashboard["charts"]):
        col = i % 2
        if col == 0 and i > 0:
            y += img_h + 4
        if col == 0 and y + img_h > 200:
            pdf.add_page()
            y = 10
        try:
            png = _chart_png(aggregate(df, spec, profile), spec)
            pdf.image(io.BytesIO(png), x=10 + col * (img_w + 5), y=y, w=img_w)
        except Exception as e:
            pdf.set_xy(10 + col * (img_w + 5), y)
            pdf.set_font("Helvetica", "", 9)
            pdf.cell(img_w, 8, _latin(f"Couldn't draw '{spec.get('title')}': {e}"))
    return bytes(pdf.output())


# ------------------------------------------------------------------- HTML
def to_html(df, profile, dashboard) -> bytes:
    title = html.escape(dashboard["title"])
    kpi_html = ""
    for k in dashboard["kpis"]:
        try:
            val = fmt_num(compute_kpi(df, k, profile))
        except Exception:
            val = "–"
        kpi_html += (f'<div class="kpi"><div class="kl">{html.escape(k["label"])}</div>'
                     f'<div class="kv">{html.escape(val)}</div></div>')
    charts_html = ""
    for i, spec in enumerate(dashboard["charts"]):
        try:
            fig = build_figure(aggregate(df, spec, profile), spec)
            charts_html += '<div class="chart">' + fig.to_html(
                full_html=False, include_plotlyjs="cdn" if i == 0 else False) + "</div>"
        except Exception as e:
            charts_html += f'<div class="chart">Couldn\'t draw {html.escape(spec.get("title", ""))}: {html.escape(str(e))}</div>'
    page = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{title}</title>
<style>
body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:linear-gradient(180deg,#1C2524 0%,#29432C 55%,#8CC63F 100%) fixed;min-height:100vh;color:#E6EFE0}}
main{{max-width:1300px;margin:0 auto;padding:28px 20px}}
h1{{margin:0 0 4px;font-size:26px;color:#F7FEE7}} .meta{{color:#A9BDB0;font-size:13px;margin-bottom:20px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:16px}}
.kpi{{background:rgba(17,25,21,.6);border:1px solid rgba(255,255,255,.1);border-radius:14px;padding:14px 16px;box-shadow:inset 0 3px 0 #A3E635,0 8px 24px rgba(0,0,0,.3)}}
.kl{{font-size:13px;color:#A9BDB0}} .kv{{font-size:26px;font-weight:700;color:#BEF264}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(460px,1fr));gap:14px}}
.chart{{background:rgba(17,25,21,.6);border:1px solid rgba(255,255,255,.1);border-radius:14px;padding:8px;overflow-x:auto;box-shadow:0 8px 24px rgba(0,0,0,.3)}}
</style></head><body><main><h1>{title}</h1>
<div class="meta">{profile['rows']:,} rows · Generated {datetime.now():%d %b %Y} with Dashboard GPT</div>
<div class="kpis">{kpi_html}</div><div class="grid">{charts_html}</div></main></body></html>"""
    return page.encode("utf-8")


# ----------------------------------------------------- Power BI-ready Excel
def _sheet_name(name: str, used: set) -> str:
    base = re.sub(r"[\[\]:*?/\\]", "", name)[:28] or "Sheet"
    candidate, n = base, 2
    while candidate.lower() in used:
        candidate = f"{base[:25]}_{n}"
        n += 1
    used.add(candidate.lower())
    return candidate


def _autofit(ws, sample_rows=200):
    for col in ws.iter_cols(min_row=1, max_row=min(ws.max_row, sample_rows)):
        width = max((len(str(c.value)) for c in col if c.value is not None), default=8)
        ws.column_dimensions[col[0].column_letter].width = min(max(width + 2, 8), 50)


def to_excel(df, profile, dashboard) -> bytes:
    buf = io.BytesIO()
    used: set = set()
    guide = pd.DataFrame({"How to use this file in Power BI": [
        "1. Open Power BI Desktop → Get data → Excel workbook → select this file.",
        "2. Load the 'Data' sheet: it's the cleaned dataset with correct column types.",
        "3. Each 'Chart_…' sheet holds the exact numbers behind one dashboard chart.",
        "4. 'Dashboard_Spec' lists every chart with the matching Power BI visual, X axis, Y axis and aggregation.",
        "5. Rebuild each visual from the 'Data' table using those settings.",
    ]})
    spec_rows = []
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        guide.to_excel(xw, sheet_name=_sheet_name("How_to_use", used), index=False)
        df.to_excel(xw, sheet_name=_sheet_name("Data", used), index=False)
        for i, spec in enumerate(dashboard["charts"], 1):
            spec_rows.append({
                "Chart": i, "Title": spec["title"], "Chart type": TYPE_LABELS[spec["type"]],
                "Power BI visual": POWER_BI_VISUAL[spec["type"]], "X axis": spec["x"],
                "Y axis": spec.get("y") or "(count of rows)",
                "Aggregation": AGG_LABELS[spec["agg"]] if spec["type"] != "scatter" else "None",
                "Top N": spec.get("top") or "All", "Sort": spec.get("sort", "desc"),
                "Filters": describe_filters(spec.get("filters")) or "None",
            })
            try:
                res = aggregate(df, spec, profile)
                if spec["type"] != "scatter":
                    res = res.drop(columns="key").rename(columns={"label": spec["x"], "value": value_label(spec)})
                res.to_excel(xw, sheet_name=_sheet_name(f"Chart{i}_{spec['title']}", used), index=False)
            except Exception:
                pass
        pd.DataFrame(spec_rows or [{"Chart": "No charts yet"}]).to_excel(
            xw, sheet_name=_sheet_name("Dashboard_Spec", used), index=False)
        if dashboard["kpis"]:
            pd.DataFrame([{"KPI": k["label"], "Column": k.get("column") or "(rows)",
                           "Aggregation": AGG_LABELS[k["agg"]],
                           "Filters": describe_filters(k.get("filters")) or "None", "Value": compute_kpi(df, k, profile)}
                          for k in dashboard["kpis"]]).to_excel(
                xw, sheet_name=_sheet_name("KPIs", used), index=False)
        profile_table(profile).to_excel(xw, sheet_name=_sheet_name("Data_Profile", used), index=False)
        for ws in xw.book.worksheets:
            _autofit(ws)
    return buf.getvalue()
