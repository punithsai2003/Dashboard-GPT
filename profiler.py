"""Step 1 + 2: load the file and read it accurately.

Plain pandas, no AI. Every column is read as text first and its type is
decided by our own rules, because automatic parsing often misreads IDs
like "007", dates like "03-04-2024" or numbers like "₹1,200".
"""
from __future__ import annotations

import csv
import io
import re

import pandas as pd

from formatting import fmt_full, fmt_num

NULL_TOKENS = {"", "na", "n/a", "nan", "null", "none", "nil", "-", "--", "?", "#n/a", "nat"}
THRESHOLD = 0.95  # share of values that must parse for a type to be accepted
ID_WORDS = {"id", "code", "no", "number", "num", "sku", "uuid"}

# Day-first formats come before month-first ones, so an ambiguous date
# like 03/04/2024 is read as 3 April (the Indian convention).
DATE_FORMATS = [
    "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%d.%m.%Y",
    "%d-%b-%Y", "%d %b %Y", "%b %d, %Y", "%d-%B-%Y", "%d %B %Y", "%B %d, %Y",
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S",
    "%d-%m-%Y %H:%M", "%d/%m/%Y %H:%M", "%m/%d/%Y %H:%M",
    "%b-%y", "%b %Y", "%B %Y", "%Y-%m",
]

TYPE_LABELS = {
    "numeric": "🔢 Number", "date": "📅 Date", "categorical": "🏷️ Category",
    "text": "🔤 Text", "id": "🆔 ID", "empty": "⬜ Empty",
}


# ---------------------------------------------------------------- loading
def list_sheets(uploaded) -> list[str]:
    uploaded.seek(0)
    names = pd.ExcelFile(uploaded).sheet_names
    uploaded.seek(0)
    return names


def _read_csv_bytes(raw: bytes) -> pd.DataFrame:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        try:
            sep = csv.Sniffer().sniff(text[:20000], delimiters=",;\t|").delimiter
        except csv.Error:
            sep = ","
        return pd.read_csv(io.StringIO(text), sep=sep, dtype=str, keep_default_na=False)
    raise ValueError("Couldn't decode the file. Save it as UTF-8 CSV and try again.")


def _clean_columns(columns) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for i, c in enumerate(columns):
        name = re.sub(r"\s+", " ", str(c)).strip() or f"Column_{i + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 1
        out.append(name)
    return out


def load_file(uploaded, sheet: str | None = None) -> pd.DataFrame:
    """Read a CSV or Excel upload with every value kept as text."""
    name = str(getattr(uploaded, "name", uploaded)).lower()
    if hasattr(uploaded, "seek"):
        uploaded.seek(0)
    if name.endswith((".xlsx", ".xlsm")):
        df = pd.read_excel(uploaded, sheet_name=sheet or 0, dtype=str, keep_default_na=False)
    else:
        raw = uploaded.read() if hasattr(uploaded, "read") else open(uploaded, "rb").read()
        df = _read_csv_bytes(raw)

    df = df.fillna("").astype(str)
    # Drop fully blank rows and blank "Unnamed" columns that Excel/CSV exports add.
    blank = df.apply(lambda c: c.str.strip() == "")
    df = df.loc[~blank.all(axis=1)]
    drop = [c for c in df.columns if str(c).startswith("Unnamed") and blank[c].all()]
    df = df.drop(columns=drop)
    if df.empty or df.shape[1] == 0:
        raise ValueError("The file has no data rows.")
    df.columns = _clean_columns(df.columns)
    return df.reset_index(drop=True)


# -------------------------------------------------------------- profiling
def _words(name: str) -> list[str]:
    return [w.lower() for w in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", name)]


def _looks_like_id(name: str) -> bool:
    return any(w in ID_WORDS for w in _words(name))


def _clean_text(series: pd.Series) -> pd.Series:
    s = series.astype(object).map(lambda v: str(v).strip())
    return s.where(~s.str.lower().isin(NULL_TOKENS))


def _to_numeric(s: pd.Series) -> pd.Series:
    t = s.str.replace(r"(?i)^(rs\.?|inr)\s*", "", regex=True)
    t = t.str.replace(r"[₹$€£¥,\s]", "", regex=True)
    t = t.str.replace(r"^\((.+)\)$", r"-\1", regex=True)  # (500) -> -500
    t = t.str.replace(r"%$", "", regex=True)
    return pd.to_numeric(t, errors="coerce")


def _to_date(s: pd.Series):
    nonnull = s.dropna()
    sample = nonnull.head(500)
    best, best_ratio = None, 0.0
    for fmt in DATE_FORMATS:
        ratio = pd.to_datetime(sample, format=fmt, errors="coerce").notna().mean()
        if ratio > best_ratio:
            best, best_ratio = fmt, ratio
        if ratio == 1.0:
            break
    if best is None or best_ratio < THRESHOLD:
        return None, None
    full = pd.to_datetime(s, format=best, errors="coerce")
    if full.notna().sum() / len(nonnull) < THRESHOLD:
        return None, None
    return full, best


def profile_dataframe(raw: pd.DataFrame):
    """Return (typed dataframe, profile dict)."""
    n = len(raw)
    typed: dict[str, pd.Series] = {}
    cols: dict[str, dict] = {}

    for name in raw.columns:
        s = _clean_text(raw[name])
        nonnull = s.dropna()
        k = len(nonnull)
        info = {"type": None, "missing": 0, "unparsed": 0, "unique": 0,
                "examples": [str(v) for v in nonnull.head(3)]}

        if k == 0:
            info.update(type="empty", missing=n)
            typed[name] = s
            cols[name] = info
            continue

        col = s
        num = _to_numeric(s)
        num_ok = int(num.notna().sum())
        if num_ok / k >= THRESHOLD:
            if _looks_like_id(name) and num_ok >= 5 and num.nunique() == num_ok:
                info["type"] = "id"
            else:
                info["type"], info["unparsed"], col = "numeric", k - num_ok, num
        else:
            dates, fmt = _to_date(s)
            if dates is not None:
                info["type"], info["date_format"], col = "date", fmt, dates
                info["unparsed"] = int(k - dates.notna().sum())
            else:
                nun = nonnull.nunique()
                if nun == k and k >= 5 and _looks_like_id(name):
                    info["type"] = "id"
                elif nun <= 50 or nun / k <= 0.5:
                    info["type"] = "categorical"
                else:
                    info["type"] = "text"

        typed[name] = col
        info["missing"] = int(col.isna().sum())
        info["unique"] = int(col.nunique())
        if info["type"] == "numeric":
            v = col.dropna()
            info.update(min=float(v.min()), max=float(v.max()), mean=float(v.mean()),
                        median=float(v.median()), sum=float(v.sum()),
                        integer=bool((v % 1 == 0).all()))
        elif info["type"] == "date":
            v = col.dropna()
            info.update(min=v.min().strftime("%Y-%m-%d"), max=v.max().strftime("%Y-%m-%d"))
        else:
            vc = col.value_counts().head(10)
            info["top_values"] = [[str(i), int(c)] for i, c in vc.items()]
        cols[name] = info

    df = pd.DataFrame(typed)
    profile = {"rows": n, "n_cols": len(raw.columns),
               "duplicates": int(raw.duplicated().sum()), "columns": cols}
    return df, profile


# ------------------------------------------------------------ helpers
def numeric_columns(profile) -> list[str]:
    return [c for c, i in profile["columns"].items() if i["type"] == "numeric"]


def dimension_columns(profile) -> list[str]:
    return [c for c, i in profile["columns"].items() if i["type"] in ("categorical", "date", "text")]


def _details(info) -> str:
    t = info["type"]
    if t == "numeric":
        d = f"{fmt_full(info['min'])} to {fmt_full(info['max'])}, avg {fmt_num(info['mean'])}"
    elif t == "date":
        d = f"{info['min']} → {info['max']}"
    elif t == "categorical":
        top = ", ".join(v for v, _ in info["top_values"][:3])
        d = f"{info['unique']} values, e.g. {top}"
    elif t == "text":
        d = f"{info['unique']} different values"
    elif t == "id":
        d = "Unique identifier (not charted)"
    else:
        d = "No data"
    if info.get("unparsed"):
        d += f" · {info['unparsed']} unreadable value(s) treated as missing"
    return d.replace("|", "\\|")


def profile_table(profile) -> pd.DataFrame:
    return pd.DataFrame([
        {"Column": c, "Type": TYPE_LABELS[i["type"]], "Missing": i["missing"],
         "Unique": i["unique"], "Details": _details(i).replace("\\|", "|")}
        for c, i in profile["columns"].items()
    ])


def brief_markdown(profile, file_name: str) -> str:
    """Short data brief shown in chat right after upload (100% code, no AI).
    The full column table is shown separately under "Column details"."""
    cols = profile["columns"]
    missing = sum(i["missing"] for i in cols.values())
    dups = profile["duplicates"]
    facts = [f"{profile['rows']:,} rows", f"{profile['n_cols']} columns",
             "no missing values" if not missing else f"{missing:,} missing values",
             "no duplicate rows" if not dups else f"{dups:,} duplicate rows"]
    lines = [f"I've read **{file_name}**: " + ", ".join(facts) + "."]

    groups = {"Numbers": [], "Categories": [], "Dates": [], "Free text": [], "IDs": []}
    for c, i in cols.items():
        t = i["type"]
        if t == "numeric":
            groups["Numbers"].append(c)
        elif t == "categorical":
            groups["Categories"].append(f"{c} ({i['unique']})")
        elif t == "date":
            groups["Dates"].append(f"{c} ({i['min']} to {i['max']})")
        elif t == "text":
            groups["Free text"].append(c)
        elif t == "id":
            groups["IDs"].append(c)
    for label, items in groups.items():
        if items:
            lines.append(f"**{label}:** {', '.join(items)}")

    problems = [c for c, i in cols.items() if i["missing"] or i.get("unparsed")]
    if problems:
        lines.append(f"⚠️ Check these columns for gaps: {', '.join(problems)}.")
    lines.append("What would you like to see?")
    return "\n\n".join(lines)


def brief_for_llm(profile) -> str:
    """Compact profile sent to Gemini. Never includes the raw rows."""
    out = [f"Rows: {profile['rows']}. Columns: {profile['n_cols']}."]
    for c, i in profile["columns"].items():
        t = i["type"]
        miss = f", {i['missing']} missing" if i["missing"] else ""
        if t == "numeric":
            out.append(f'- "{c}" (numeric{miss}): min {i["min"]:.4g}, max {i["max"]:.4g}, mean {i["mean"]:.4g}')
        elif t == "date":
            out.append(f'- "{c}" (date{miss}): {i["min"]} to {i["max"]}')
        elif t == "categorical":
            vals = ", ".join(v[:30] for v, _ in i["top_values"][:8])
            more = "" if i["unique"] <= 8 else ", ..."
            out.append(f'- "{c}" (categorical, {i["unique"]} unique{miss}): {vals}{more}')
        elif t == "text":
            out.append(f'- "{c}" (text, {i["unique"]} unique values, use top N when charting{miss})')
        elif t == "id":
            out.append(f'- "{c}" (id, one per row, do not chart; can be counted)')
        else:
            out.append(f'- "{c}" (empty column, ignore)')
    return "\n".join(out)
