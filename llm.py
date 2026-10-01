"""Step 3: the AI layer.

The AI only sees the data profile (column names, types, a few stats), never
the full data, and it only returns JSON: a reply, plus a dashboard or query
spec. pandas computes every number, so the AI can't produce wrong numbers.

Two free providers are supported:
  - Google Gemini (GEMINI_API_KEY)
  - Groq, running open models like Llama (GROQ_API_KEY)
If one is busy, out of quota or unavailable, the other is tried automatically.
"""
from __future__ import annotations

import json
import os
import re
import time

import requests
import streamlit as st

PLACEHOLDERS = {"", "PASTE_YOUR_GEMINI_API_KEY_HERE", "PASTE_YOUR_GROQ_API_KEY_HERE"}
GEMINI_MODELS = ["gemini-flash-latest", "gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-flash-lite-latest"]
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_DEFAULT_MODEL = "llama-3.3-70b-versatile"


class LLMError(Exception):
    pass


class ProviderError(Exception):
    """One provider failed. kind: busy, quota, model, key, other."""

    def __init__(self, kind: str, detail: str):
        super().__init__(detail)
        self.kind, self.detail = kind, detail


def get_secret(name: str, default=None):
    """Read from .streamlit/secrets.toml (or Streamlit Cloud secrets), then env vars."""
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.environ.get(name, default)


def _key(name: str):
    key = str(get_secret(name, "") or "").strip()
    return None if key in PLACEHOLDERS else key


def available_providers() -> list[str]:
    order = []
    if _key("GEMINI_API_KEY"):
        order.append("Gemini")
    if _key("GROQ_API_KEY"):
        order.append("Groq")
    if str(get_secret("AI_PROVIDER", "") or "").lower() == "groq":
        order.sort(key=lambda p: p != "Groq")
    return order


def get_api_key():
    """Truthy when at least one AI provider is configured (kept for the app's checks)."""
    return ", ".join(available_providers()) or None


SYSTEM_TEMPLATE = """You are Dashboard GPT. You build dashboards from a dataset the user uploaded.
You never see the raw data, only the profile below. Python code computes every number,
so never state numbers or results yourself.

## Dataset profile
{brief}

## Current dashboard (JSON)
{dashboard}

## How to talk to the user
- Be short and friendly. Ask ONE question at a time.
- When the user asks for a dashboard without details, collect them in this order,
  skipping anything they already told you:
  1. How many charts?
  2. For each chart in turn: chart type (bar, hbar, line, area, pie, donut, scatter)
     -> X axis column -> Y axis column (or count of rows)
     -> aggregation (sum, mean, median, count, min, max, nunique) -> top N (optional).
  In each question, offer 2-4 sensible options using the real column names.
- If the user says "you decide", "suggest" or similar, design a sensible dashboard and build it.
- Build (action "update_dashboard") only when every chart is fully specified, or when the user
  asks you to decide.
- For changes like "make chart 2 a line chart" or "show top 10", return the FULL updated dashboard
  and keep every other chart exactly the same. Charts are numbered from 1 in the order listed.
- For questions about the data ("which product sold the most?"), use action "query". The app
  computes and shows the answer as a table. In "reply" only introduce it, e.g.
  "Here are the products ranked by total sales:". Never guess numbers.
- If the user asks to explain, summarise or interpret the dashboard, or asks for insights,
  trends or recommendations, use action "explain" (the app computes the facts and writes
  the explanation). Put a one-line intro in "reply".
- If something can't be done with the available columns, say so and suggest what is possible.

## Chart rules
- Use column names EXACTLY as written in the profile.
- X axis: categorical, text or date columns (id columns are never charted).
- Y axis: numeric columns only, or null to count rows.
- line/area charts need a date (or ordered number) on the X axis.
- pie/donut: at most 8 slices, so set top to 8 or fewer when the X column has more values.
- scatter: X and Y are both numeric; agg is ignored.
- For "top products / top customers" style charts use top (e.g. 5 or 10) with sort "desc".
- To limit a chart, KPI or query to part of the data ("in 2026", "only South region",
  "orders above 5000"), add "filters". Each filter is {{"column": "...", "op": "...", "value": ...}}
  with op one of: eq, neq, in, not_in, gt, gte, lt, lte, between, year, month.
  Examples: {{"column": "Date", "op": "year", "value": 2026}},
  {{"column": "Region", "op": "in", "value": ["South", "West"]}},
  {{"column": "Sales", "op": "between", "value": [1000, 5000]}}.
  year/month filters only work on date columns. Mention the filter in the chart title.
- Give every chart a short, clear title.
- KPI cards (big single numbers like total sales) are added ONLY when the user asks for them.
  When you build a dashboard without cards, end your reply by suggesting 2-3 useful cards
  (e.g. "Want summary cards for Total Sales and Orders?"). Keep existing cards unless asked.
  To count orders with an id column use agg "nunique" on it.

## Output format
Reply with ONE JSON object and nothing else:
{{
  "reply": "message shown to the user (markdown allowed)",
  "action": "ask" | "update_dashboard" | "query" | "explain" | "none",
  "dashboard": null or {{
    "title": "...",
    "kpis": [{{"label": "...", "column": "<column or null>", "agg": "sum", "filters": []}}],
    "charts": [{{"title": "...", "type": "bar", "x": "...", "y": "<column or null>",
                "agg": "sum", "top": null, "sort": "desc", "date_bucket": null, "filters": []}}]
  }},
  "query": null or {{"x": "...", "y": "<column or null>", "agg": "sum", "top": 10, "sort": "desc", "filters": []}}
}}
date_bucket is null (automatic) or one of: day, week, month, quarter, year.
"""


def _clean_dashboard(d: dict) -> dict:
    return {"title": d.get("title"),
            "kpis": [{k: v for k, v in c.items() if k != "id"} for c in d.get("kpis", [])],
            "charts": [{k: v for k, v in c.items() if k != "id"} for c in d.get("charts", [])]}


def _turns(history: list[dict], user_msg: str) -> list[tuple[str, str]]:
    """Alternating (role, text) turns that start with the user."""
    turns: list[list] = []
    for m in history + [{"role": "user", "content": user_msg}]:
        role = "user" if m["role"] == "user" else "assistant"
        text = str(m.get("content", ""))
        if turns and turns[-1][0] == role:
            turns[-1][1] += "\n\n" + text
        else:
            turns.append([role, text])
    while turns and turns[0][0] != "user":
        turns.pop(0)
    return [(r, t) for r, t in turns]


def parse_json(text: str) -> dict:
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        out = json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, re.S)
        try:
            out = json.loads(m.group(0)) if m else None
        except json.JSONDecodeError:
            out = None
    if not isinstance(out, dict):
        return {"reply": text or "", "action": "none"}
    return out


def _classify(status, msg: str) -> str:
    low = msg.lower()
    if status in (429,) or "resource_exhausted" in low or "quota" in low or "rate limit" in low:
        return "quota"
    if status in (500, 502, 503, 504) or "unavailable" in low or "overloaded" in low or "503" in msg:
        return "busy"
    if status in (401, 403) or "api key" in low or "api_key" in low or "permission_denied" in low:
        return "key"
    if status == 404 or "404" in msg or "not found" in low or "not supported" in low:
        return "model"
    return "other"


# ------------------------------------------------------------------ Gemini
@st.cache_resource(show_spinner=False)
def _gemini_client(api_key: str):
    from google import genai
    return genai.Client(api_key=api_key)


def _call_gemini(system: str, turns, json_mode: bool = True) -> str:
    from google.genai import types

    config = types.GenerateContentConfig(
        system_instruction=system, temperature=0.2 if json_mode else 0.4,
        response_mime_type="application/json" if json_mode else "text/plain",
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
    contents = [{"role": "user" if r == "user" else "model", "parts": [{"text": t}]} for r, t in turns]
    configured = str(get_secret("GEMINI_MODEL", GEMINI_MODELS[0]) or GEMINI_MODELS[0])
    models = [configured] + [m for m in GEMINI_MODELS if m != configured]
    remembered = st.session_state.get("gemini_model")
    if remembered in models:
        models.remove(remembered)
        models.insert(0, remembered)

    error = None
    for model in models:  # a busy or retired model falls through to the next one
        try:
            resp = _gemini_client(_key("GEMINI_API_KEY")).models.generate_content(
                model=model, contents=contents, config=config)
            st.session_state["gemini_model"] = model
            return resp.text
        except Exception as e:
            code = getattr(e, "code", None)
            error = ProviderError(_classify(code, str(e)), f"{model}: {str(e)[:160]}")
            if error.kind in ("key", "quota", "other"):
                break
            time.sleep(1)
    raise error


# -------------------------------------------------------------------- Groq
def _call_groq(system: str, turns, json_mode: bool = True) -> str:
    model = str(get_secret("GROQ_MODEL", GROQ_DEFAULT_MODEL) or GROQ_DEFAULT_MODEL)
    messages = [{"role": "system", "content": system}] + [{"role": r, "content": t} for r, t in turns]
    body = {"model": model, "messages": messages, "temperature": 0.2 if json_mode else 0.4}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    for attempt in range(2):
        try:
            r = requests.post(GROQ_URL, json=body, timeout=60,
                              headers={"Authorization": f"Bearer {_key('GROQ_API_KEY')}"})
        except requests.RequestException as e:
            raise ProviderError("busy", f"network error: {e}")
        if r.ok:
            return r.json()["choices"][0]["message"]["content"]
        kind = _classify(r.status_code, r.text)
        if kind == "busy" and attempt == 0:
            time.sleep(2)
            continue
        raise ProviderError(kind, f"{model}: HTTP {r.status_code} {r.text[:160]}")


CALLERS = {"Gemini": _call_gemini, "Groq": _call_groq}
MESSAGES = {
    "busy": "is overloaded right now",
    "quota": "has hit its free-tier limit",
    "model": "has no working model for this key",
    "key": "rejected the API key",
    "other": "returned an error",
}


def _run(system: str, turns, json_mode: bool) -> str:
    """Try each configured provider in order and return the raw text."""
    providers = available_providers()
    if not providers:
        raise LLMError("No AI key is set. Add GEMINI_API_KEY or GROQ_API_KEY to .streamlit/secrets.toml.")
    problems = []
    for name in providers:
        try:
            text = CALLERS[name](system, turns, json_mode)
            st.session_state["ai_provider_used"] = name
            return text
        except ProviderError as e:
            problems.append((name, e))
    summary = "; ".join(f"{n} {MESSAGES[e.kind]}" for n, e in problems)
    tip = ""
    if len(providers) == 1:
        tip = " Add a free Groq key (GROQ_API_KEY) as a backup so the app keeps working when this happens."
    elif all(e.kind in ("busy", "quota") for _, e in problems):
        tip = " Wait a minute and try again."
    details = " | ".join(e.detail for _, e in problems)
    raise LLMError(f"{summary}.{tip}\n\nDetails: `{details}`")


def ask_ai(brief: str, dashboard: dict, history: list[dict], user_msg: str) -> dict:
    """Chat turn: returns the parsed JSON reply (reply, action, dashboard, query)."""
    system = SYSTEM_TEMPLATE.format(
        brief=brief, dashboard=json.dumps(_clean_dashboard(dashboard), indent=1, default=str))
    return parse_json(_run(system, _turns(history, user_msg), json_mode=True))


INSIGHTS_SYSTEM = """You are a senior business analyst explaining a dashboard to a manager.
You receive FACTS computed exactly by code from the data. Use only these numbers:
never invent, estimate or recalculate figures, and copy numbers exactly as written.
If something can't be concluded from the facts, don't claim it.

Write in plain, friendly English using markdown, under 350 words, with these parts:
**Summary**: 2-3 sentences on the big picture.
**What each chart shows**: one short bullet per chart, naming the key number.
**Business insights**: 3-5 bullets on patterns, concentration, risks and opportunities.
**Suggested actions**: 2-4 concrete, practical next steps.
**Caveats**: only if relevant (e.g. small sample, partial periods, active filters).
"""


def ask_insights(facts: str, question: str | None = None) -> str:
    """Plain-text explanation of the dashboard, written only from computed facts."""
    msg = f"FACTS:\n{facts}\n\n" + (f"The user asks: {question}" if question else
                                      "Explain this dashboard and give business insights.")
    return _run(INSIGHTS_SYSTEM, [("user", msg)], json_mode=False).strip()
