"""Dashboard GPT: upload data, describe what you need, get an accurate dashboard.

Run locally:  streamlit run app.py
"""
from __future__ import annotations

import copy
import hashlib
import html
import json
import re
from pathlib import Path

import pandas as pd
import streamlit as st

from charts import aggregate, build_figure, click_filter, compute_kpi
from export import to_excel, to_html, to_pdf
from formatting import fmt_full, fmt_num
from insights import build_facts
from llm import LLMError, ask_ai, ask_insights, get_api_key, get_secret
from profiler import (brief_for_llm, brief_markdown, list_sheets, load_file, numeric_columns,
                      profile_dataframe, profile_table)
from spec import (AGG_LABELS, AGGS, CHART_TYPES, TYPE_LABELS, default_title, describe_filters, validate_chart,
                  validate_dashboard, validate_kpi, value_label)

st.set_page_config(page_title="Dashboard GPT", page_icon="📊", layout="wide",
                   initial_sidebar_state="collapsed")

SAMPLE_PATH = Path(__file__).parent / "sample_data" / "sample_sales.csv"
COUNT_ROWS = "(Count of rows)"
ss = st.session_state

st.markdown("""<style>
/* ================= Forest glass theme: charcoal-green to lime ================= */
[data-testid="stApp"] {
  background:
    radial-gradient(900px 500px at 85% 105%, rgba(190,242,100,.35), transparent 60%),
    linear-gradient(180deg, #1C2524 0%, #212E29 28%, #29432C 52%, #4F8A2C 78%, #8CC63F 92%, #A9DC4F 100%);
  background-attachment: fixed;
}
header[data-testid="stHeader"] {background: transparent;}
.stAppDeployButton {display: none;}
.block-container {padding-top: 1rem; padding-bottom: 6rem; max-width: 1640px;}

/* dark frosted glass surfaces */
.st-key-topbar, [class*="st-key-card_"], [class*="st-key-kpi_"], .st-key-empty,
.st-key-chatpanel, .st-key-datapanel {
  background: rgba(17,25,21,.58) !important;
  backdrop-filter: blur(18px) saturate(140%); -webkit-backdrop-filter: blur(18px) saturate(140%);
  border: 1px solid rgba(255,255,255,.10) !important;
  border-radius: 1.1rem !important;
  box-shadow: 0 12px 36px rgba(0,0,0,.35), inset 0 1px 0 rgba(255,255,255,.06);
}
.st-key-topbar {padding: .65rem 1.1rem; margin-bottom: .4rem;}
.st-key-topbar [data-testid="stMarkdownContainer"], .st-key-topbar .stMarkdown {margin: 0 !important;}
.st-key-titlebar {padding: .3rem .1rem;}
.st-key-titlegroup {gap: .4rem !important; align-items: center !important;}
.st-key-titlegroup [data-testid="stMarkdownContainer"], .st-key-titlegroup .stMarkdown {margin: 0 !important;}
.st-key-titlegroup [data-testid="stPopoverButton"] {min-height: 2rem !important; height: 2rem; width: 2rem;
  padding: 0 !important; justify-content: center;}
[class*="st-key-card_"] {padding: 1rem 1.1rem .6rem; transition: transform .18s ease, box-shadow .18s ease;}
[class*="st-key-card_"]:hover {transform: translateY(-2px); box-shadow: 0 18px 44px rgba(0,0,0,.45);}
[class*="st-key-kpi_"] {padding: .9rem 1.1rem; box-shadow: inset 0 3px 0 #A3E635, 0 12px 32px rgba(0,0,0,.35);}
.st-key-card_insights {
  background: linear-gradient(135deg, rgba(54,83,20,.70), rgba(20,40,30,.70)) !important;
  border: 1px solid rgba(163,230,53,.45) !important;
}
.st-key-filterbar {
  background: rgba(113,63,18,.55); backdrop-filter: blur(10px);
  border: 1px solid rgba(250,204,21,.45); border-radius: .9rem; padding: 4px 12px;
}

/* buttons */
[data-testid^="stBaseButton-secondary"], [data-testid="stPopoverButton"] {
  background: rgba(255,255,255,.06) !important; backdrop-filter: blur(10px);
  border: 1px solid rgba(255,255,255,.14) !important; border-radius: 999px !important;
  min-height: 2.45rem; padding: .35rem 1.05rem !important; font-size: .92rem; font-weight: 500;
  color: #E6EFE0 !important;
}
[data-testid^="stBaseButton-secondary"]:hover, [data-testid="stPopoverButton"]:hover {
  border-color: rgba(163,230,53,.7) !important; color: #D9F99D !important; background: rgba(163,230,53,.08) !important;
}
[data-testid^="stBaseButton-primary"] {
  background: linear-gradient(135deg, #BEF264, #4ADE80) !important; border: none !important;
  border-radius: 999px !important; min-height: 2.45rem; padding: .35rem 1.2rem !important;
  color: #0F1A12 !important; font-weight: 600; box-shadow: 0 6px 18px rgba(132,204,22,.35);
}
[data-testid^="stBaseButton-primary"] * {color: #0F1A12 !important;}
[data-testid^="stBaseButton-tertiary"] {border-radius: 999px !important; min-height: 2.2rem; padding: .25rem .6rem !important;}
[data-testid^="stBaseButton-tertiary"]:hover {background: rgba(163,230,53,.10) !important;}
[class*="st-key-card_"] [data-testid="stPopoverButton"], [class*="st-key-kpi_"] [data-testid="stPopoverButton"] {
  min-height: 2.1rem; padding: .2rem .55rem !important;
}
[data-testid="stPopoverButton"][aria-label=""] div[aria-hidden="true"] {display: none;}
:is([class*="st-key-card_"], [class*="st-key-kpi_"], .st-key-chatpanel, .st-key-datapanel)
  [data-testid="stColumn"]:last-child [data-testid="stVerticalBlock"] {align-items: flex-end;}

/* floating AI assistant */
.st-key-chatfab {position: fixed; right: 28px; bottom: 28px; z-index: 1001; width: auto !important;}
.st-key-chatfab button {
  width: 62px; height: 62px; border-radius: 50% !important; padding: 0 !important; border: none !important;
  background: linear-gradient(135deg, #BEF264, #22C55E) !important;
  box-shadow: 0 10px 30px rgba(0,0,0,.45), 0 0 0 6px rgba(163,230,53,.18) !important;
}
.st-key-chatfab button [data-testid="stIconMaterial"] {font-size: 1.8rem; color: #0F1A12 !important;}
.st-key-chatfab button:hover {transform: scale(1.06);}
.st-key-chatpanel {
  position: fixed; right: 28px; bottom: 104px; z-index: 1000;
  width: min(440px, calc(100vw - 32px)) !important; max-height: calc(100vh - 130px);
  overflow-y: auto; padding: .8rem 1rem 1rem; background: rgba(17,25,21,.88) !important;
}
.chat-head {display: flex; gap: .65rem; align-items: center; color: #F0F7EA;}
.bot-dot {width: 34px; height: 34px; border-radius: 50%; display: grid; place-items: center;
  background: linear-gradient(135deg, #BEF264, #22C55E); flex-shrink: 0;}
[data-testid="stChatMessage"] {background: rgba(255,255,255,.05); border-radius: .9rem;}
.st-key-datapanel {
  position: fixed; right: 40px; top: 110px; z-index: 999;
  width: min(760px, calc(100vw - 32px)) !important; max-height: calc(100vh - 140px);
  overflow-y: auto; padding: .8rem 1.1rem 1rem; background: rgba(17,25,21,.90) !important;
}
.drag-handle {cursor: move; user-select: none; font-weight: 600; color: #F0F7EA; padding: .25rem 0;}
.grip {color: #7E9486; margin-right: .3rem;}

/* brand */
.brand-row {display: flex; align-items: center; gap: .8rem; height: 46px;}
.logo {width: 44px; height: 44px; border-radius: 13px; display: grid; place-items: center; flex-shrink: 0;
  background: linear-gradient(145deg, #D9F99D 0%, #84CC16 55%, #16A34A 100%);
  box-shadow: 0 6px 18px rgba(132,204,22,.35), inset 0 1px 0 rgba(255,255,255,.6);}
.logo svg {display: block;}
.brand {font-size: 1.25rem; font-weight: 700; letter-spacing: -0.01em; line-height: 1;
  background: linear-gradient(90deg, #F7FEE7, #BEF264); -webkit-background-clip: text; background-clip: text; color: transparent;}

/* type */
.dash-title {font-size: 1.5rem; font-weight: 700; color: #F7FEE7; letter-spacing: -0.015em; line-height: 2rem; margin: 0;}
.kpi-l {font-size: .8rem; color: #A9BDB0; font-weight: 500; text-transform: uppercase; letter-spacing: .04em;}
.kpi-v {font-size: 1.85rem; font-weight: 700; line-height: 1.35; padding-bottom: 2px;
  background: linear-gradient(90deg, #ECFCCB, #A3E635); -webkit-background-clip: text; background-clip: text; color: transparent;}
.kpi-f {font-size: .72rem; color: #8FA596;}
.ct {font-weight: 600; font-size: 1rem; color: #F0F7EA; line-height: 1.3;}
.cs {font-size: .78rem; color: #95AA9C; font-weight: 400;}
.hero {font-size: 2.4rem; font-weight: 800; line-height: 1.12; letter-spacing: -0.02em; margin-bottom: .7rem;
  background: linear-gradient(90deg, #F7FEE7, #A3E635); -webkit-background-clip: text; background-clip: text; color: transparent;}
.hero-sub {font-size: 1.05rem; color: #C9D8CD; max-width: 34rem; line-height: 1.55;}
.steps {margin-top: 1.4rem; color: #C9D8CD; line-height: 1.8; max-width: 34rem;}
.steps b {color: #A3E635;}
</style>""", unsafe_allow_html=True)


# ------------------------------------------------------------------ state
def empty_dashboard() -> dict:
    return {"title": "My Dashboard", "kpis": [], "charts": []}


def init_state():
    defaults = {"df": None, "profile": None, "file_name": None, "data_sig": None,
                "last_upload_sig": None, "dashboard": empty_dashboard(), "undo": [],
                "messages": [], "ai_calls": 0, "exports": None,
                "cross": None, "sel_v": 0, "insights": None, "chat_open": False, "data_open": False}
    for k, v in defaults.items():
        if k not in ss:
            ss[k] = copy.deepcopy(v)


def max_ai_calls() -> int:
    try:
        return int(get_secret("MAX_AI_CALLS_PER_SESSION", 40))
    except (TypeError, ValueError):
        return 40


def set_data(raw: pd.DataFrame, name: str, sig: str):
    df, profile = profile_dataframe(raw)
    ss.df, ss.profile, ss.file_name, ss.data_sig = df, profile, name, sig
    ss.dashboard, ss.undo, ss.exports = empty_dashboard(), [], None
    ss.cross, ss.insights = None, None
    ss.messages = [{"role": "assistant", "content": brief_markdown(profile, name), "kind": "brief"}]


def push_undo():
    ss.undo.append(copy.deepcopy(ss.dashboard))
    ss.undo = ss.undo[-20:]
    ss.exports = None


def say(content: str, table: list | None = None):
    msg = {"role": "assistant", "content": content}
    if table is not None:
        msg["table"] = table
    ss.messages.append(msg)


def bullets(title: str, items: list[str]) -> str:
    return "" if not items else f"\n\n**{title}**\n" + "\n".join(f"- {i}" for i in items)


# ------------------------------------------------------------- chat logic
def handle_prompt(prompt: str):
    ss.messages.append({"role": "user", "content": prompt})
    key = get_api_key()
    if not key:
        say("The AI isn't connected, so I can't read free-text requests yet. "
            "Add a Gemini or Groq key to `.streamlit/secrets.toml`, or use **Add** above the dashboard.")
        return
    if ss.ai_calls >= max_ai_calls():
        say("This session has used all its AI requests. Refresh the page to start a new session, "
            "or keep editing charts by hand.")
        return

    history = [m for m in ss.messages[:-1] if m.get("kind") != "brief"][-12:]
    ss.ai_calls += 1
    try:
        with st.spinner("Thinking…"):
            out = ask_ai(brief_for_llm(ss.profile), ss.dashboard, history, prompt)
    except LLMError as e:
        say(f"⚠️ {e}")
        return

    reply = str(out.get("reply") or "").strip()
    action = str(out.get("action") or "none").lower()

    if action == "update_dashboard" and isinstance(out.get("dashboard"), dict):
        new, notes, errors = validate_dashboard(out["dashboard"], ss.profile)
        if new and (new["charts"] or new["kpis"]):
            push_undo()
            ss.dashboard = new
            reply = reply or "Your dashboard is ready. Tell me what to change."
        else:
            reply = "I couldn't build a valid dashboard from that. Tell me which columns to use and I'll try again."
        say(reply + bullets("Adjustments", notes) + bullets("Skipped", errors))
    elif action == "query" and isinstance(out.get("query"), dict):
        answer_query(out["query"], reply)
    elif action == "explain":
        if not ss.dashboard["charts"] and not ss.dashboard["kpis"]:
            say("There's no dashboard to explain yet. Tell me what charts you'd like first.")
            return
        try:
            with st.spinner("Analysing the dashboard…"):
                text = run_insights(question=prompt)
            say((reply + "\n\n" if reply else "") + text)
        except LLMError as e:
            say(f"⚠️ {e}")
    else:
        say(reply or "I didn't catch that. Could you say it another way?")


def answer_query(query: dict, reply: str):
    q = {**query, "type": "bar"}
    q.setdefault("top", 10)
    spec, notes, errors = validate_chart(q, ss.profile)
    if not spec:
        say(f"{reply}\n\nI couldn't calculate that: {'; '.join(errors)}.".strip())
        return
    res = aggregate(ss.df, spec, ss.profile)
    if res.empty:
        say("No rows matched that question.")
        return
    vl = value_label(spec)
    table = [{spec["x"]: r.label, vl: fmt_full(r.value)} for r in res.itertuples()]
    lead = ""
    if ss.profile["columns"][spec["x"]]["type"] != "date" and spec["sort"] == "desc":
        lead = f"**{res.label.iloc[0]}** is highest, with {vl.lower()} of **{fmt_full(res.value.iloc[0])}**."
    say(f"{reply}\n\n{lead}".strip() + bullets("Note", notes), table=table)


# ------------------------------------------------------------ data input
def upload_widget(key: str):
    up = st.file_uploader("Upload a CSV or Excel file", type=["csv", "xlsx"], key=key)
    if up is None:
        return
    sig, sheet = f"{up.name}-{up.size}", None
    if up.name.lower().endswith(".xlsx"):
        try:
            sheets = list_sheets(up)
            sheet = st.selectbox("Sheet", sheets, key=f"{key}_sheet") if len(sheets) > 1 else sheets[0]
            sig += f"-{sheet}"
        except Exception as e:
            st.error(f"Couldn't open this Excel file: {e}")
            return
    if sig != ss.last_upload_sig:
        ss.last_upload_sig = sig
        try:
            set_data(load_file(up, sheet), up.name, sig)
            st.rerun()
        except Exception as e:
            st.error(f"Couldn't read this file: {e}")


def load_sample():
    set_data(load_file(str(SAMPLE_PATH)), "sample_sales.csv", "sample")


def suggestions() -> list[str]:
    cols = ss.profile["columns"]
    nums = numeric_columns(ss.profile)
    cats = [c for c, i in cols.items() if i["type"] == "categorical"]
    dates = [c for c, i in cols.items() if i["type"] == "date"]
    measure = next((c for c in nums if re.search(r"sales|revenue|amount|total|value", c, re.I)),
                   nums[0] if nums else None)
    out = []
    if measure:
        out.append(f"Build a {measure.lower()} overview dashboard, you choose the charts")
        if cats:
            big = max(cats, key=lambda c: cols[c]["unique"])
            out.append(f"Top 5 {big} by {measure}")
        if dates:
            out.append(f"How does {measure} change month by month?")
    elif cats:
        out.append(f"How many rows are there per {cats[0]}?")
    return out


def _use_suggestion():
    choice = ss.get("suggest")
    if choice:
        ss.pending_prompt = choice
    ss.suggest = None


# ---------------------------------------------------------- chart editing
def chart_fields(prefix: str, spec: dict | None = None) -> dict:
    """Shared widgets for adding and editing a chart."""
    spec = spec or {}
    cols = list(ss.profile["columns"].keys())
    y_opts = [COUNT_ROWS] + numeric_columns(ss.profile)
    if spec.get("y") and spec["y"] not in y_opts:
        y_opts.append(spec["y"])
    ctype = st.selectbox("Chart type", CHART_TYPES, format_func=TYPE_LABELS.get, key=f"{prefix}_type",
                         index=CHART_TYPES.index(spec.get("type", "bar")))
    x = st.selectbox("X axis", cols, key=f"{prefix}_x",
                     index=cols.index(spec["x"]) if spec.get("x") in cols else 0)
    y = st.selectbox("Y axis", y_opts, key=f"{prefix}_y",
                     index=y_opts.index(spec.get("y") or COUNT_ROWS))
    agg = st.selectbox("Aggregation", AGGS, format_func=AGG_LABELS.get, key=f"{prefix}_agg",
                       index=AGGS.index(spec.get("agg", "sum")))
    top = st.number_input("Show top N (0 = all)", 0, 50, int(spec.get("top") or 0), key=f"{prefix}_top")
    title = st.text_input("Title (optional)", spec.get("title", ""), key=f"{prefix}_title")
    return {"type": ctype, "x": x, "y": None if y == COUNT_ROWS else y,
            "agg": agg, "top": top or None, "title": title}


def kpi_form(prefix: str, kpi: dict | None = None, idx: int | None = None):
    """Create or edit a KPI card: one big number, e.g. Total Sales or Number of orders."""
    kpi = kpi or {}
    cols = list(ss.profile["columns"].keys())
    col_opts = [COUNT_ROWS] + cols
    with st.form(prefix, border=False):
        label = st.text_input("Card title", kpi.get("label", ""), placeholder="e.g. Total sales",
                              key=f"{prefix}_label")
        column = st.selectbox("Column", col_opts, key=f"{prefix}_col",
                              index=col_opts.index(kpi["column"]) if kpi.get("column") in col_opts else 0)
        agg = st.selectbox("Calculation", AGGS, format_func=AGG_LABELS.get, key=f"{prefix}_agg",
                           index=AGGS.index(kpi.get("agg", "sum")))
        st.caption("Tip: to count orders, pick the order ID column with Distinct count.")
        if st.form_submit_button("Save card" if kpi else "Add card", type="primary", width="stretch"):
            raw = {**kpi, "label": label, "column": None if column == COUNT_ROWS else column,
                   "agg": "count" if column == COUNT_ROWS else agg}
            new, errors = validate_kpi(raw, ss.profile)
            if errors:
                st.error("; ".join(errors))
            else:
                push_undo()
                if idx is None:
                    ss.dashboard["kpis"].append(new)
                else:
                    ss.dashboard["kpis"][idx] = new
                st.rerun()


def render_kpis(kpis: list[dict]):
    per_row = 4
    for start in range(0, len(kpis), per_row):
        row = kpis[start:start + per_row]
        cols = st.columns(per_row if len(kpis) > per_row else len(row), gap="small")
        for j, k in enumerate(row):
            idx = start + j
            k.setdefault("id", f"k{idx}")
            try:
                kk = {**k, "filters": list(k.get("filters") or []) + ([ss.cross["filter"]] if ss.cross else [])}
                val = fmt_num(compute_kpi(ss.df, kk, ss.profile))
            except Exception:
                val = "–"
            note = describe_filters(k.get("filters"))
            with cols[j]:
                with st.container(border=True, key=f"kpi_{k['id']}"):
                    left, right = st.columns([5, 1], vertical_alignment="top", gap="small")
                    left.markdown(f"<div class='kpi-l'>{html.escape(k['label'])}</div>"
                                  f"<div class='kpi-v'>{html.escape(val)}</div>"
                                  + (f"<div class='kpi-f'>{html.escape(note)}</div>" if note else ""),
                                  unsafe_allow_html=True)
                    with right:
                        with st.popover("", icon=":material/more_vert:", type="tertiary",
                                        key=f"kpipop_{k['id']}", help="Edit card"):
                            kpi_form(f"edit_kpi_{k['id']}", k, idx)
                            if st.button("Remove card", icon=":material/delete:", key=f"rmkpi_{k['id']}"):
                                push_undo()
                                ss.dashboard["kpis"].pop(idx)
                                st.rerun()


def add_chart_form():
    with st.form("add_chart", border=False):
        raw = chart_fields("add")
        if st.form_submit_button("Add to dashboard", type="primary", width="stretch"):
            spec, notes, errors = validate_chart(raw, ss.profile)
            if errors:
                st.error("; ".join(errors))
            else:
                push_undo()
                ss.dashboard["charts"].append(spec)
                if notes:
                    say(f"Added “{spec['title']}”." + bullets("Adjustments", notes))
                st.rerun()


def edit_chart(idx: int, spec: dict):
    with st.form(f"edit_{spec['id']}", border=False):
        raw = chart_fields(f"edit_{spec['id']}", spec)
        if st.form_submit_button("Save changes", type="primary", width="stretch"):
            if raw["title"] == spec["title"] and raw["title"] == default_title(spec):
                raw["title"] = ""  # auto title: regenerate it for the new settings
            new, notes, errors = validate_chart({**spec, **raw}, ss.profile)
            if errors:
                st.error("; ".join(errors))
            else:
                push_undo()
                ss.dashboard["charts"][idx] = new
                if notes:
                    say(f"Updated chart {idx + 1}." + bullets("Adjustments", notes))
                st.rerun()

    charts = ss.dashboard["charts"]
    with st.container(horizontal=True):
        if st.button("Move up", icon=":material/arrow_upward:", key=f"up_{spec['id']}",
                     disabled=idx == 0):
            push_undo()
            charts[idx - 1], charts[idx] = charts[idx], charts[idx - 1]
            st.rerun()
        if st.button("Move down", icon=":material/arrow_downward:", key=f"down_{spec['id']}",
                     disabled=idx == len(charts) - 1):
            push_undo()
            charts[idx + 1], charts[idx] = charts[idx], charts[idx + 1]
            st.rerun()
        if st.button("Remove", icon=":material/delete:", key=f"rm_{spec['id']}"):
            push_undo()
            charts.pop(idx)
            st.rerun()


# -------------------------------------------------------------- exports
def export_panel():
    d = ss.dashboard
    if not d["charts"] and not d["kpis"]:
        st.caption("Add a chart first.")
        return
    sig = hashlib.md5(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest() + str(ss.data_sig)
    slug = re.sub(r"[^A-Za-z0-9]+", "_", d["title"]).strip("_") or "dashboard"
    if not ss.exports or ss.exports.get("sig") != sig:
        st.caption("Files are built from the current dashboard.")
        if st.button("Prepare files", type="primary", width="stretch"):
            try:
                with st.spinner("Preparing files…"):
                    ss.exports = {"sig": sig,
                                  "pdf": to_pdf(ss.df, ss.profile, d, ss.file_name),
                                  "html": to_html(ss.df, ss.profile, d),
                                  "xlsx": to_excel(ss.df, ss.profile, d)}
                st.rerun()
            except Exception as e:
                st.error(f"Export failed: {e}")
        return
    st.download_button("PDF report", ss.exports["pdf"], f"{slug}.pdf", "application/pdf",
                       icon=":material/picture_as_pdf:", width="stretch")
    st.download_button("Interactive HTML", ss.exports["html"], f"{slug}.html", "text/html",
                       icon=":material/public:", width="stretch")
    st.download_button("Power BI-ready Excel", ss.exports["xlsx"], f"{slug}_powerbi.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       icon=":material/table_view:", width="stretch")


def data_window():
    """Floating data window. Drag it by its header; position is remembered."""
    with st.container(key="datapanel"):
        left, right = st.columns([12, 1], vertical_alignment="center")
        left.markdown("<div class='drag-handle'><span class='grip'>⠿</span> Your data "
                      f"<span class='cs'>· {html.escape(ss.file_name)} · drag this bar to move</span></div>",
                      unsafe_allow_html=True)
        with right:
            if st.button("", icon=":material/close:", type="tertiary", key="data_close", help="Close"):
                ss.data_open = False
                st.rerun()
        t1, t2, t3 = st.tabs(["Columns", "Preview", "Change data"])
        with t1:
            st.dataframe(profile_table(ss.profile), hide_index=True, width="stretch", height=330)
        with t2:
            st.dataframe(ss.df.head(200), width="stretch", height=330)
            st.caption("Showing the first 200 rows. Drag column edges to resize them.")
        with t3:
            upload_widget("replace_upload")
            with st.container(horizontal=True):
                if st.button("Load sample data", icon=":material/dataset:"):
                    load_sample()
                    st.rerun()
                if st.button("Start over", icon=":material/restart_alt:"):
                    for k in list(ss.keys()):
                        del ss[k]
                    st.rerun()


# -------------------------------------------------------------- layout
def top_bar():
    with st.container(key="topbar"):
        left, right = st.columns([1, 1], vertical_alignment="center")
        left.markdown(
            "<div class='brand-row'><div class='logo'>"
            "<svg viewBox='0 0 24 24' width='24' height='24' fill='none'>"
            "<rect x='3.5' y='12' width='3.6' height='8' rx='1.2' fill='#0F1A12'/>"
            "<rect x='10.2' y='8' width='3.6' height='12' rx='1.2' fill='#0F1A12'/>"
            "<rect x='16.9' y='4.5' width='3.6' height='15.5' rx='1.2' fill='#0F1A12' opacity='.85'/>"
            "<path d='M4 9.5 L11.5 5 L15 7 L20.5 2.8' stroke='#F7FEE7' stroke-width='1.8' "
            "stroke-linecap='round' stroke-linejoin='round'/></svg></div>"
            "<div class='brand'>Dashboard GPT</div></div>", unsafe_allow_html=True)
        with right, st.container(horizontal=True, horizontal_alignment="right", vertical_alignment="center",
                                 gap="small", wrap=False):
            with st.popover("Add", icon=":material/add:"):
                tab_chart, tab_card = st.tabs(["Chart", "KPI card"])
                with tab_chart:
                    add_chart_form()
                with tab_card:
                    kpi_form("add_kpi")
            if st.button("Data", icon=":material/table_chart:", key="data_toggle",
                         type="primary" if ss.data_open else "secondary"):
                ss.data_open = not ss.data_open
                st.rerun()
            with st.popover("Export", icon=":material/download:"):
                export_panel()
            if st.button("Undo", icon=":material/undo:", disabled=not ss.undo):
                ss.dashboard = ss.undo.pop()
                ss.exports = None
                st.rerun()


def render_assistant():
    """Floating AI assistant: a bot button at the bottom right that opens the chat."""
    if ss.get("pending_prompt"):
        handle_prompt(ss.pop("pending_prompt"))
        st.rerun()

    with st.container(key="chatfab"):
        if st.button("", icon=":material/close:" if ss.chat_open else ":material/smart_toy:",
                     key="fab", help="Close assistant" if ss.chat_open else "Open AI assistant"):
            ss.chat_open = not ss.chat_open
            st.rerun()
    if not ss.chat_open:
        return

    with st.container(key="chatpanel"):
        left, right = st.columns([8, 1], vertical_alignment="center")
        with left:
            st.markdown("<div class='drag-handle chat-head'><div class='bot-dot'>"
                        "<svg viewBox='0 0 24 24' width='16' height='16' fill='none' stroke='#0F1A12' "
                        "stroke-width='2'><rect x='4' y='8' width='16' height='12' rx='3'/>"
                        "<path d='M12 4v4M9 13h.01M15 13h.01'/></svg></div>"
                        "<div><b>Dashboard Assistant</b><div class='cs'>Builds charts, answers questions, "
                        "explains insights</div></div></div>", unsafe_allow_html=True)
        with right:
            if st.button("", icon=":material/close:", type="tertiary", key="chat_close", help="Close"):
                ss.chat_open = False
                st.rerun()
        with st.container(height=380, border=False, autoscroll=True):
            for m in ss.messages:
                with st.chat_message(m["role"]):
                    st.markdown(m["content"])
                    if m.get("kind") == "brief":
                        with st.expander("Column details"):
                            st.dataframe(profile_table(ss.profile), hide_index=True, width="stretch")
                    if m.get("table"):
                        st.dataframe(pd.DataFrame(m["table"]), hide_index=True, width="stretch")
        ai_on = bool(get_api_key())
        if ai_on and not ss.dashboard["charts"]:
            st.pills("Try asking", suggestions(), key="suggest", on_change=_use_suggestion,
                     label_visibility="collapsed")
        if not ai_on:
            st.caption("AI is off. Add `GEMINI_API_KEY` or `GROQ_API_KEY` to `.streamlit/secrets.toml`. "
                       "You can still build charts with **Add**.")
        prompt = st.chat_input("Ask for a chart, a change or an insight…")
        if prompt:
            handle_prompt(prompt)
            st.rerun()


DRAG_JS = """
<script>
(function () {
  const doc = window.parent && window.parent.document ? window.parent.document : document;
  const win = doc.defaultView || window;
  if (win.__dgDragReady) return;
  win.__dgDragReady = true;
  function styleFor(name) {
    let el = doc.getElementById('dg-pos-' + name);
    if (!el) { el = doc.createElement('style'); el.id = 'dg-pos-' + name; doc.head.appendChild(el); }
    return el;
  }
  function place(name, x, y) {
    styleFor(name).textContent = '.st-key-' + name + '{left:' + x + 'px !important;top:' + y +
      'px !important;right:auto !important;bottom:auto !important;}';
  }
  ['datapanel', 'chatpanel'].forEach(function (n) {
    try { const p = JSON.parse(win.localStorage.getItem('dg-pos-' + n)); if (p) place(n, p.x, p.y); } catch (e) {}
  });
  let drag = null;
  doc.addEventListener('mousedown', function (e) {
    const handle = e.target.closest && e.target.closest('.drag-handle');
    if (!handle) return;
    const panel = handle.closest('.st-key-datapanel, .st-key-chatpanel');
    if (!panel) return;
    const name = panel.classList.contains('st-key-datapanel') ? 'datapanel' : 'chatpanel';
    const r = panel.getBoundingClientRect();
    drag = {name: name, dx: e.clientX - r.left, dy: e.clientY - r.top, w: r.width, h: r.height};
    e.preventDefault();
  });
  doc.addEventListener('mousemove', function (e) {
    if (!drag) return;
    const vw = win.innerWidth, vh = win.innerHeight;
    const x = Math.min(Math.max(8, e.clientX - drag.dx), vw - 120);
    const y = Math.min(Math.max(8, e.clientY - drag.dy), vh - 60);
    place(drag.name, x, y);
    drag.x = x; drag.y = y;
  });
  doc.addEventListener('mouseup', function () {
    if (drag && drag.x !== undefined) {
      win.localStorage.setItem('dg-pos-' + drag.name, JSON.stringify({x: drag.x, y: drag.y}));
    }
    drag = null;
  });
  doc.addEventListener('dblclick', function (e) {   // double-click a header to reset its position
    const handle = e.target.closest && e.target.closest('.drag-handle');
    if (!handle) return;
    const panel = handle.closest('.st-key-datapanel, .st-key-chatpanel');
    if (!panel) return;
    const name = panel.classList.contains('st-key-datapanel') ? 'datapanel' : 'chatpanel';
    styleFor(name).textContent = '';
    win.localStorage.removeItem('dg-pos-' + name);
  });
})();
</script>
"""


# ------------------------------------------------- cross-filter + insights
def with_cross(spec: dict) -> dict:
    """Apply the click filter to every chart except the one that was clicked."""
    c = ss.cross
    if not c or spec.get("id") == c.get("source"):
        return spec
    return {**spec, "filters": list(spec.get("filters") or []) + [c["filter"]]}


def set_cross(cross):
    ss.cross = cross
    ss.sel_v += 1  # fresh chart widgets, so old click selections don't linger
    ss.exports = None


def clicked_label(event, spec):
    try:
        points = event.selection.get("points", []) if event else []
    except AttributeError:
        points = (event or {}).get("selection", {}).get("points", [])
    if not points:
        return None
    p = points[0]
    cd = p.get("customdata")
    if isinstance(cd, (list, tuple)) and cd:
        return str(cd[0])
    if p.get("label") is not None:
        return str(p["label"])
    return str(p.get("y") if spec["type"] == "hbar" else p.get("x"))


def dashboard_sig() -> str:
    return hashlib.md5(json.dumps([ss.dashboard, ss.cross], sort_keys=True, default=str)
                       .encode()).hexdigest()


def run_insights(question: str | None = None) -> str:
    facts = build_facts(ss.df, ss.profile, ss.dashboard, ss.cross)
    text = ask_insights(facts, question)
    ss.insights = {"sig": dashboard_sig(), "text": text,
                   "scope": f"{ss.cross['column']} = {ss.cross['label']}" if ss.cross else None}
    return text


def insights_card():
    ins = ss.insights
    with st.container(border=True, key="card_insights"):
        with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
            scope = f" for {ins['scope']}" if ins.get("scope") else ""
            st.markdown(f"<div class='ct'>AI insights{html.escape(scope)}</div>"
                        "<div class='cs'>Written by AI from numbers computed exactly by pandas. "
                        "Check before acting on them.</div>", unsafe_allow_html=True)
            with st.container(horizontal=True, horizontal_alignment="right"):
                refresh = st.button("Refresh", icon=":material/refresh:", type="tertiary", key="ins_refresh")
                close = st.button("Hide", icon=":material/close:", type="tertiary", key="ins_close")
        if ins["sig"] != dashboard_sig():
            st.caption("The dashboard or filter changed since this was written. Click Refresh to update it.")
        st.markdown(ins["text"])
    if close:
        ss.insights = None
        st.rerun()
    if refresh:
        explain_now()


def explain_now():
    if not get_api_key():
        st.toast("Add a Gemini or Groq key to use AI insights.")
        return
    if ss.ai_calls >= max_ai_calls():
        st.toast("This session has used all its AI requests.")
        return
    ss.ai_calls += 1
    try:
        with st.spinner("Analysing the dashboard…"):
            run_insights()
        st.rerun()
    except LLMError as e:
        st.error(str(e))


def slicer_popover():
    cats = [c for c, i in ss.profile["columns"].items() if i["type"] == "categorical"]
    with st.popover("Filter", icon=":material/filter_alt:"):
        if not cats:
            st.caption("No category columns to filter by. Click a bar or slice instead.")
            return
        col = st.selectbox("Column", cats, key="slicer_col")
        values = sorted(ss.df[col].dropna().astype(str).unique())[:300]
        chosen = st.multiselect("Show only", values, key=f"slicer_vals_{col}")
        if st.button("Apply filter", type="primary", disabled=not chosen):
            set_cross({"column": col, "label": ", ".join(chosen), "source": None,
                       "filter": {"column": col, "op": "in", "value": chosen}})
            st.rerun()
        st.caption("Tip: you can also click any bar, slice or point to filter all charts.")


def render_chart(idx: int, spec: dict):
    with st.container(border=True, key=f"card_{spec['id']}"):
        left, right = st.columns([10, 1], vertical_alignment="top", gap="small")
        with left:
            sub = value_label(spec) + (f" by {spec['x']}" if spec["type"] != "scatter" else "")
            if spec.get("top"):
                sub += f", top {spec['top']}"
            if spec.get("filters"):
                sub += f" (where {describe_filters(spec['filters'])})"
            st.markdown(f"<div class='ct'>{html.escape(spec['title'])}</div>"
                        f"<div class='cs'>{html.escape(sub)}</div>", unsafe_allow_html=True)
        with right:
            with st.popover("", icon=":material/tune:", key=f"pop_{spec['id']}", type="tertiary",
                            help="Edit chart"):
                edit_chart(idx, spec)
        try:
            res = aggregate(ss.df, with_cross(spec), ss.profile)
        except Exception as e:
            st.warning(f"Couldn't draw this chart: {e}")
            return
        if res.empty:
            st.caption("No data for the current selection.")
            return
        is_source = bool(ss.cross) and ss.cross.get("source") == spec["id"]
        fig = build_figure(res, spec, show_title=False,
                           highlight=ss.cross["label"] if is_source else None)
        key = f"fig_{spec['id']}_{ss.sel_v}"
        if spec["type"] == "scatter":
            st.plotly_chart(fig, width="stretch", key=key, config={"displayModeBar": False})
            return
        event = st.plotly_chart(fig, width="stretch", key=key, on_select="rerun",
                                selection_mode="points", config={"displayModeBar": False})
        label = clicked_label(event, spec)
        if spec["type"] in ("pie", "donut"):
            # Plotly pie slices don't send click events to Streamlit, so the
            # slices get clickable chips underneath instead.
            options = [l for l in res["label"] if l != "Others"]
            current = ss.cross["label"] if is_source and ss.cross["label"] in options else None
            picked = st.pills("Filter by", options, default=current, key=f"pills_{spec['id']}_{ss.sel_v}",
                              label_visibility="collapsed")
            if picked != current:
                label = picked if picked is not None else current
        if label is None:
            return
        if is_source and ss.cross["label"] == label:
            set_cross(None)  # clicking the selected item again clears the filter
        else:
            f = click_filter(res, spec, ss.profile, label)
            if f is None:
                st.toast("“Others” groups several items, so it can't be used as a filter.")
                ss.sel_v += 1
            else:
                set_cross({"column": spec["x"], "label": label, "filter": f, "source": spec["id"]})
        st.rerun()


def render_dashboard():
    d = ss.dashboard
    with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center",
                      key="titlebar"):
        with st.container(horizontal=True, vertical_alignment="center", gap=None, width="content",
                          key="titlegroup"):
            st.markdown(f"<div class='dash-title'>{html.escape(d['title'])}</div>", unsafe_allow_html=True)
            with st.popover("", icon=":material/edit:", type="tertiary", help="Rename dashboard"):
                new = st.text_input("Dashboard title", d["title"], key=f"rename_{d['title']}")
                if st.button("Save title", type="primary") and new.strip():
                    d["title"] = new.strip()
                    ss.exports = None
                    st.rerun()
        if d["charts"] or d["kpis"]:
            with st.container(horizontal=True, horizontal_alignment="right", vertical_alignment="center",
                              gap="small", width="content"):
                slicer_popover()
                if st.button("Explain this dashboard", icon=":material/auto_awesome:", type="primary"):
                    explain_now()

    if ss.cross:
        with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center",
                          key="filterbar"):
            st.markdown(f"<div class='cs' style='font-size:.9rem'>Filtered to <b>{html.escape(ss.cross['column'])}"
                        f" = {html.escape(ss.cross['label'])}</b>. Click it again or clear to see everything.</div>",
                        unsafe_allow_html=True)
            if st.button("Clear filter", icon=":material/filter_alt_off:", key="clear_cross"):
                set_cross(None)
                st.rerun()

    if not d["charts"] and not d["kpis"]:
        with st.container(border=True, key="empty"):
            st.markdown("**Your dashboard will appear here.**")
            st.markdown("Describe what you want in the chat, for example "
                        "*“sales by region, top 5 products and a monthly trend”*. "
                        "Or build charts and KPI cards yourself with **Add**.")
        return

    if d["kpis"]:
        render_kpis(d["kpis"])

    if ss.insights:
        insights_card()

    charts = d["charts"]
    for start in range(0, len(charts), 2):
        row = charts[start:start + 2]
        cols = st.columns(2, gap="small")
        for j, spec in enumerate(row):
            with cols[j]:
                render_chart(start + j, spec)


def landing():
    st.markdown("<div style='height:8vh'></div>", unsafe_allow_html=True)
    left, right = st.columns([3, 2], gap="large", vertical_alignment="center")
    with left:
        st.markdown(
            "<div class='hero'>Describe a dashboard.<br>Get one built from your data.</div>"
            "<div class='hero-sub'>Upload a spreadsheet, tell Dashboard GPT what you want to see, "
            "and answer a few quick questions. The AI decides what to chart; pandas computes every "
            "number, so the charts are exact.</div>"
            "<div class='steps'><b>1.</b> Upload a CSV or Excel file and get an instant data brief.<br>"
            "<b>2.</b> Chat: how many charts, which types, which columns.<br>"
            "<b>3.</b> Tweak anything, then export to PDF, HTML or Power BI.</div>",
            unsafe_allow_html=True)
    with right:
        with st.container(border=True, key="card_upload"):
            st.markdown("**Start with your data**")
            upload_widget("main_upload")
            if st.button("Use sample sales data", icon=":material/dataset:", width="stretch"):
                load_sample()
                st.rerun()
            st.caption("Only column names and summary stats are sent to the AI, never your rows. "
                       "The free Gemini tier may use requests to improve Google's products, "
                       "so avoid confidential data.")


# ------------------------------------------------------------------- main
init_state()
if ss.df is None:
    landing()
else:
    top_bar()
    render_dashboard()
    render_assistant()
    if ss.data_open:
        data_window()
    st.html(DRAG_JS, unsafe_allow_javascript=True)
