"""analyze_data: answer questions about a spreadsheet the user uploaded, and
draw charts from it -- "where did my money go?", "spend by month", "top 5
customers".

Deliberately NOT a Python sandbox: the model never runs code on this server.
It picks from a fixed set of operations (describe, filter, group, aggregate,
sort, chart) on validated column names, executed with pandas. That covers the
everyday questions with no way for a prompt injection to run commands; a real
sandbox (e.g. a hosted one) can come later for power users.

Reads CSV/XLSX from the user's own folder (basename only); charts are PNGs
written back there and shown as an image card. Plan-gated: Plus and up.
"""

import asyncio
import re
from pathlib import Path

from harness.tools.base import Tool, ToolOutput
from harness.tools.builtin.files import fresh_name, user_folder

MAX_ROWS_SHOWN = 50
OPS = {"sum", "mean", "count", "min", "max", "median"}
FILTER_OPS = {"=", "!=", ">", ">=", "<", "<=", "contains", "startswith"}
DATE_PARTS = {"day", "week", "month", "quarter", "year", "weekday"}


class DataError(ValueError):
    pass


def _number_like(s):
    """'₹1,240.50' / '$ 12' / '(300)' -> float; anything else -> None."""
    if s is None:
        return None
    t = re.sub(r"[₹$€£¥,\s]|INR|USD|EUR|Rs\.?", "", str(s), flags=re.I)
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()")
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def load(user_id: str, filename: str, sheet: str | None = None):
    import pandas as pd
    folder = user_folder(user_id)
    path = folder / Path(filename).name
    if path.suffix.lower() not in (".csv", ".xlsx") or not path.is_file():
        have = sorted(p.name for p in folder.glob("*") if p.suffix.lower() in (".csv", ".xlsx"))
        raise DataError(f"No spreadsheet named {Path(filename).name!r}. "
                        + (f"Available: {', '.join(have[-20:])}." if have else "The user has not uploaded a CSV or Excel file."))
    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path, encoding_errors="replace")
    else:
        sheets = pd.read_excel(path, sheet_name=None)
        if sheet and sheet not in sheets:
            raise DataError(f"No sheet {sheet!r}; sheets: {', '.join(sheets)}.")
        df = sheets[sheet] if sheet else next(iter(sheets.values()))
    df.columns = [str(c).strip() for c in df.columns]
    # money/number columns stored as text ('₹1,240') become numbers
    for c in df.columns:
        if pd.api.types.is_object_dtype(df[c]) or pd.api.types.is_string_dtype(df[c]):
            conv = df[c].map(_number_like)
            if conv.notna().sum() >= max(1, int(0.8 * df[c].notna().sum())):
                df[c] = conv
            else:
                parsed = pd.to_datetime(df[c], errors="coerce", dayfirst=True, format="mixed")
                if parsed.notna().sum() >= max(1, int(0.8 * df[c].notna().sum())):
                    df[c] = parsed
    return df


def _col(df, name: str) -> str:
    if name in df.columns:
        return name
    low = {c.lower(): c for c in df.columns}
    if name.lower() in low:
        return low[name.lower()]
    raise DataError(f"No column {name!r}. Columns: {', '.join(df.columns)}.")


def apply_filters(df, filters):
    for f in filters or []:
        c, op, v = _col(df, f.get("column", "")), f.get("op", "="), f.get("value")
        if op not in FILTER_OPS:
            raise DataError(f"Filter op must be one of {sorted(FILTER_OPS)}.")
        s = df[c]
        if op in ("contains", "startswith"):
            m = s.astype(str).str.lower()
            df = df[m.str.contains(str(v).lower(), regex=False) if op == "contains" else m.str.startswith(str(v).lower())]
            continue
        import pandas as pd
        if pd.api.types.is_datetime64_any_dtype(s):
            v = pd.to_datetime(v, dayfirst=True)
        elif pd.api.types.is_numeric_dtype(s):
            v = _number_like(v) if _number_like(v) is not None else v
        df = df[{"=": s == v, "!=": s != v, ">": s > v, ">=": s >= v, "<": s < v, "<=": s <= v}[op]]
    return df


def group(df, group_by: list[str], date_part: str | None):
    keys = []
    for g in group_by or []:
        c = _col(df, g)
        if date_part and df[c].dtype.kind == "M":
            if date_part not in DATE_PARTS:
                raise DataError(f"date_part must be one of {sorted(DATE_PARTS)}.")
            s = df[c].dt
            df = df.assign(**{c: {"day": s.strftime("%Y-%m-%d"), "week": s.strftime("%G-W%V"),
                                  "month": s.strftime("%Y-%m"), "quarter": s.to_period("Q").astype(str),
                                  "year": s.strftime("%Y"), "weekday": s.day_name()}[date_part]})
        keys.append(c)
    return df, keys


def run_query(df, *, filters=None, group_by=None, aggregate=None, sort_by=None, descending=True,
              limit=MAX_ROWS_SHOWN, date_part=None):
    import pandas as pd
    df = apply_filters(df, filters)
    df, keys = group(df, group_by or [], date_part)
    aggs = aggregate or ([{"column": keys[0], "op": "count"}] if keys else [])
    if keys:
        spec = {}
        for a in aggs:
            op = a.get("op", "sum")
            if op not in OPS:
                raise DataError(f"Aggregate op must be one of {sorted(OPS)}.")
            col = _col(df, a.get("column", keys[0]))
            spec[f"{op}_{col}" if op != "count" else "count"] = (col, "size" if op == "count" else op)
        out = df.groupby(keys, dropna=False).agg(**spec).reset_index()
    elif aggs:
        out = pd.DataFrame([{(f"{a.get('op', 'sum')}_{_col(df, a['column'])}"):
                             (len(df) if a.get("op") == "count" else getattr(df[_col(df, a["column"])], a.get("op", "sum"))())
                             for a in aggs}])
    else:
        out = df
    if sort_by:
        target = next((c for c in out.columns if c == sort_by or c.endswith(f"_{sort_by}") or c.lower() == sort_by.lower()), None)
        if target is None:
            raise DataError(f"Can't sort by {sort_by!r}; result columns: {', '.join(map(str, out.columns))}.")
        out = out.sort_values(target, ascending=not descending)
    elif keys and len(out.columns) > len(keys):
        out = out.sort_values(out.columns[len(keys)], ascending=False)
    return out.head(max(1, min(int(limit or MAX_ROWS_SHOWN), MAX_ROWS_SHOWN))), len(out)


def to_rows(df) -> list[list]:
    def cell(v):
        if hasattr(v, "isoformat"):
            return v.isoformat()[:10]
        if isinstance(v, float):
            return int(v) if v.is_integer() else round(v, 2)
        return None if v != v else v                 # NaN -> None
    return [list(map(str, df.columns))] + [[cell(v) for v in r] for r in df.itertuples(index=False)]


def markdown_table(rows: list[list]) -> str:
    head, *body = rows
    fmt = lambda v: f"{v:,}" if isinstance(v, (int, float)) and not isinstance(v, bool) else ("" if v is None else str(v))  # noqa: E731
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
                     + ["| " + " | ".join(fmt(v) for v in r) + " |" for r in body])


def draw_chart(df, kind: str, title: str, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    labels = [str(v) for v in df.iloc[:, 0]]
    values = [float(v or 0) for v in df.iloc[:, 1]]
    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=120)
    if kind == "pie":
        # labels in a legend: thin slices would otherwise pile their names on top of each other
        wedges, _t, _a = ax.pie(values, autopct=lambda p: f"{p:.0f}%" if p >= 4 else "", startangle=90,
                                counterclock=False, pctdistance=0.75, wedgeprops={"linewidth": 1, "edgecolor": "white"})
        ax.legend(wedges, [f"{lab} ({v:,.0f})" for lab, v in zip(labels, values)], loc="center left",
                  bbox_to_anchor=(1, 0.5), frameon=False)
        ax.axis("equal")
    elif kind == "line":
        ax.plot(labels, values, marker="o")
        ax.grid(axis="y", alpha=0.3)
    else:
        ax.bar(labels, values)
        ax.grid(axis="y", alpha=0.3)
    if kind != "pie":
        ax.set_ylabel(str(df.columns[1]))
        if len(labels) > 6:
            plt.setp(ax.get_xticklabels(), rotation=35, ha="right")
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def make_analyze_data_tool(user_id: str) -> Tool:
    async def analyze_data(action: str, file: str, sheet: str | None = None, filters: list[dict] | None = None,
                           group_by: list[str] | None = None, date_part: str | None = None,
                           aggregate: list[dict] | None = None, sort_by: str | None = None, descending: bool = True,
                           limit: int = 20, chart: str = "bar", title: str = "") -> ToolOutput | str:
        def work():
            df = load(user_id, file, sheet)
            if action == "describe":
                cols = [f"- {c} ({'number' if df[c].dtype.kind in 'if' else 'date' if df[c].dtype.kind == 'M' else 'text'})"
                        for c in df.columns]
                sample = to_rows(df.head(5))
                return ToolOutput(f"{Path(file).name}: {len(df)} rows.\nColumns:\n" + "\n".join(cols)
                                  + "\nFirst rows:\n" + markdown_table(sample),
                                  {"kind": "table", "title": f"{Path(file).name} · {len(df)} rows", "rows": sample})
            out, total = run_query(df, filters=filters, group_by=group_by, aggregate=aggregate, sort_by=sort_by,
                                   descending=descending, limit=limit, date_part=date_part)
            rows = to_rows(out)
            more = f"\n(showing {len(out)} of {total} rows)" if total > len(out) else ""
            if action == "query":
                return ToolOutput(markdown_table(rows) + more, {"kind": "table", "title": title or "Result", "rows": rows})
            if action == "chart":
                if not group_by or out.shape[1] < 2:
                    raise DataError("A chart needs `group_by` (the labels) and an `aggregate` (the values).")
                if chart not in ("bar", "line", "pie"):
                    raise DataError("chart must be bar, line or pie.")
                folder = user_folder(user_id)
                name = fresh_name(folder, title or f"{chart} chart", "png")
                draw_chart(out.iloc[:, :2], chart, title or f"{out.columns[1]} by {out.columns[0]}", folder / name)
                return ToolOutput(f"Chart saved as {name} and shown to the user. Data:\n" + markdown_table(rows) + more,
                                  {"kind": "chart", "name": name, "title": title, "rows": rows})
            raise DataError("action must be describe, query or chart.")

        try:
            return await asyncio.to_thread(work)
        except DataError as e:
            return str(e)
        except Exception as e:  # noqa: BLE001 - odd spreadsheets must not crash the run
            return f"Couldn't analyse that: {type(e).__name__}: {e}"

    return Tool(
        name="analyze_data",
        description=(
            "Analyse a CSV/Excel file the user uploaded and draw charts. Start with action=describe to see the "
            "columns. action=query: optional `filters` [{column, op (= != > >= < <= contains startswith), value}], "
            "`group_by` [columns], `date_part` (day/week/month/quarter/year/weekday, for a date column in group_by), "
            "`aggregate` [{column, op (sum mean count min max median)}], `sort_by`, `descending`, `limit`. "
            "action=chart: the same grouping plus `chart` (bar/line/pie) and `title`; shows the chart to the user. "
            "Example — spend by category: group_by=['Category'], aggregate=[{column:'Amount', op:'sum'}], chart='pie'."),
        parameter={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["describe", "query", "chart"]},
                "file": {"type": "string", "description": "The uploaded file's name, e.g. 'statement.csv'."},
                "sheet": {"type": "string"},
                "filters": {"type": "array", "items": {"type": "object", "properties": {
                    "column": {"type": "string"}, "op": {"type": "string"}, "value": {}}}},
                "group_by": {"type": "array", "items": {"type": "string"}},
                "date_part": {"type": "string", "enum": sorted(DATE_PARTS)},
                "aggregate": {"type": "array", "items": {"type": "object", "properties": {
                    "column": {"type": "string"}, "op": {"type": "string"}}}},
                "sort_by": {"type": "string"},
                "descending": {"type": "boolean"},
                "limit": {"type": "integer"},
                "chart": {"type": "string", "enum": ["bar", "line", "pie"]},
                "title": {"type": "string"},
            },
            "required": ["action", "file"],
        },
        handler=analyze_data,
    )
