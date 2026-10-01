# Dashboard GPT

**An AI assistant that turns a dataset into an accurate dashboard through conversation.**

Upload a CSV or Excel file, say what you want to see ("sales, top products and top customers"),
answer a few questions (how many charts, which type, which columns), and get an interactive
dashboard you can edit by chat or by hand, then export as PDF, HTML or a Power BI-ready Excel file.

🔗 **Live demo:** _add your streamlit.app link here_

## Why it's accurate

**The AI decides *what* to chart. Code computes *every number*.**

1. **Data is read by code, not AI.** Each column is read as text and typed by explicit rules
   (95% of values must parse as a number or date). This handles `₹1,200`, `(300)`, `NA`,
   and day-first dates like `03/04/2024`.
2. **Gemini only sees a profile** (column names, types and summary stats), never the rows.
3. **Gemini returns a JSON chart spec**, e.g.
   `{"type": "donut", "x": "Customer", "y": "Sales", "agg": "sum", "top": 8}`.
4. **Every spec is validated** with Pydantic against the real columns. Impossible charts are
   rejected, and small issues are fixed and explained (for example, a pie with 30 slices is
   limited to the top 8 plus "Others").
5. **pandas does all the maths** (group-by, top N, date bucketing), so the numbers are exact.
   Data questions ("which product sold the most?") are answered the same way.


## Features

- Upload CSV (any delimiter or encoding) or Excel (sheet picker)
- Instant data brief: rows, columns, types, missing values, duplicates
- Conversational dashboard building, one question at a time
- Answers data questions with computed tables
- **AI insights**: one click explains the dashboard, with business insights and suggested actions written only from numbers pandas computed
- **Click to filter (like Power BI)**: click a bar, point or slice chip and every other chart and KPI filters to it; click again to clear
- Filter panel for choosing several values at once
- KPI cards plus bar, horizontal bar, line, area, pie, donut and scatter charts
- Top N with a correctly recomputed "Others" group, and automatic date bucketing
- Edit, reorder or remove charts by chat or by hand, with undo
- Works without AI too: build charts from the sidebar
- Export as PDF, interactive HTML, or a Power BI-ready Excel file (clean data, one sheet per chart and a visual-by-visual spec)
- Indian number formatting (K, Lakh, Crore)

## Tech stack

Python · Streamlit · pandas · Plotly · Google Gemini (`google-genai`) · Pydantic · matplotlib · fpdf2 · openpyxl


## Project structure

```
app.py            Streamlit UI, chat flow, click-to-filter
insights.py       Exact fact sheet for AI insights
profiler.py       Step 1–2: load files and profile data accurately
llm.py            Step 3: Gemini prompt, JSON parsing, retries
spec.py           Chart spec format and validation (Pydantic)
charts.py         Step 4: pandas aggregation and Plotly charts
export.py         Step 5: PDF, HTML and Power BI-ready Excel
formatting.py     Indian number formatting
sample_data/      Demo dataset
```

## Limitations and roadmap

- Built for clean, tabular data (one row per record)
- Free Gemini tier has per-minute and daily limits; a per-session cap protects the quota
- Next: filters and slicers, multi-series charts, evaluation set measuring spec accuracy on test prompts, provider switch (Claude / Ollama)
