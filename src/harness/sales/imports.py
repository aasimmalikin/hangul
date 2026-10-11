"""Daily sales from a spreadsheet the owner already has: a billing app's sales
report (Vyapar, myBillBook, Swipe), a TallyPrime day book, a Petpooja sales
report, or a UPI statement (PhonePe / Paytm / Google Pay for Business).

No mapping per app is needed in the common case: the header row is found
(exports often start with a title block), the date and amount columns are
picked by name and checked by content, rows that aren't sales are dropped
(returns, purchases, payments out, debits, failed or cancelled), and what's
left is added up per day, with one row = one bill unless the sheet already
has a bill count. The owner can name the two columns when the guess is
wrong, and the result always says which columns were used.
"""

import io
import re
from dataclasses import asdict, dataclass, field

from harness.tools.builtin.data import _number_like

MAX_BYTES = 10 * 1024 * 1024
MAX_ROWS = 200_000
DATE_WORDS = ("invoice date", "bill date", "order date", "transaction date", "txn date", "date", "created", "time")
AMOUNT_WORDS = ("grand total", "total amount", "invoice amount", "bill amount", "net amount", "amount received",
                "net sales", "total", "amount", "sales", "credit", "my amount", "value")
COUNT_WORDS = ("no. of bills", "bills", "no of bills", "orders", "no. of orders", "invoices", "transactions", "count")
SKIP_STATUS = re.compile(r"cancel|fail|refund|void|reject|declin|revers|pending", re.IGNORECASE)


_ISO = re.compile(r"^\s*\d{4}-\d{1,2}-\d{1,2}")


def to_dates(series):
    """Dates as Indian exports write them (day first: 01/09/2026 is 1 September), but
    year-first ISO dates (2026-09-01) are never swapped."""
    import pandas as pd
    s = series.astype(str)
    iso = s.str.match(_ISO)
    out = pd.to_datetime(s.where(~iso), errors="coerce", dayfirst=True, format="mixed")
    if iso.any():
        out = out.where(~iso, pd.to_datetime(s.where(iso).str.slice(0, 19), errors="coerce", format="mixed"))
    return out


class ImportProblem(ValueError):
    pass


@dataclass
class Imported:
    days: list[dict]                          # [{day: "2026-09-01", sales, bills}]
    date_col: str
    amount_col: str
    rows_used: int
    rows_skipped: int
    columns: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["from"] = self.days[0]["day"] if self.days else None
        d["to"] = self.days[-1]["day"] if self.days else None
        d["total"] = round(sum(x["sales"] for x in self.days), 2)
        return d


def _frames(data: bytes, filename: str):
    import pandas as pd
    name = filename.lower()
    if name.endswith(".csv"):
        return [pd.read_csv(io.BytesIO(data), header=None, dtype=str, encoding_errors="replace", on_bad_lines="skip")]
    if name.endswith((".xlsx", ".xls")):
        return list(pd.read_excel(io.BytesIO(data), sheet_name=None, header=None, dtype=str).values())
    raise ImportProblem("Upload the sales report as Excel (.xlsx) or CSV.")


def _header_row(raw) -> int:
    """The first row in the top 20 that names a date column and an amount column."""
    for i in range(min(20, len(raw))):
        cells = [str(c).strip().lower() for c in raw.iloc[i].tolist() if str(c).strip() and str(c) != "nan"]
        if any(any(w in c for w in ("date", "time", "created")) for c in cells) and \
                any(any(w in c for w in ("amount", "total", "sales", "credit", "value")) for c in cells):
            return i
    return 0


def _pick(columns: list[str], words: tuple[str, ...], ok) -> str | None:
    low = {c: c.lower() for c in columns}
    for w in words:
        for c in columns:
            if (low[c] == w or w in low[c]) and ok(c):
                return c
    return None


def _table(raw):
    h = _header_row(raw)
    df = raw.iloc[h + 1:].copy()
    cols, seen = [], {}
    for c in raw.iloc[h].tolist():
        c = str(c).strip() if str(c) != "nan" else ""
        c = c or f"Column {len(cols) + 1}"
        seen[c] = seen.get(c, 0) + 1
        cols.append(c if seen[c] == 1 else f"{c} ({seen[c]})")
    df.columns = cols
    return df.dropna(how="all")


def parse(data: bytes, filename: str, *, date_col: str | None = None, amount_col: str | None = None) -> Imported:
    import pandas as pd
    if len(data) > MAX_BYTES:
        raise ImportProblem("That file is too big (the limit is 10 MB). Export a shorter date range.")
    try:
        frames = _frames(data, filename)
    except ImportProblem:
        raise
    except Exception as e:
        raise ImportProblem(f"Couldn't read that file ({type(e).__name__}). Is it the Excel or CSV export?") from e

    best = None
    for raw in frames:
        if raw.empty:
            continue
        df = _table(raw)[:MAX_ROWS]
        cols = list(df.columns)
        def dates(c, df=df):
            return to_dates(df[c]).notna().mean() >= 0.6

        def money(c, df=df):
            return df[c].map(_number_like).notna().mean() >= 0.6
        dc = date_col if date_col in cols else _pick(cols, DATE_WORDS, dates)
        ac = amount_col if amount_col in cols else _pick(cols, AMOUNT_WORDS, money)
        if dc and ac:
            best = (df, dc, ac)
            break
        best = best or (df, dc, ac)
    if best is None:
        raise ImportProblem("That file is empty.")
    df, dc, ac = best
    cols = [str(c) for c in df.columns]
    if not dc or not ac:
        missing = "date" if not dc else "amount"
        raise ImportProblem(f"Couldn't find the {missing} column. Pick it from: {', '.join(cols[:30])}.")

    notes = []
    keep = pd.Series(True, index=df.index)
    for c in cols:
        lc = c.lower()
        vals = df[c].astype(str)
        if "status" in lc:
            bad = vals.str.contains(SKIP_STATUS, na=False)
            if bad.any():
                notes.append(f"Left out {int(bad.sum())} cancelled, failed or refunded rows.")
            keep &= ~bad
        elif lc in ("type", "transaction type", "txn type", "voucher type", "vch type", "dr/cr", "cr/dr"):
            v = vals.str.lower()
            if v.str.contains("sale", na=False).any():
                ok = v.str.contains("sale", na=False) & ~v.str.contains("return|purchase", na=False)
            elif v.str.contains(r"\bcredit\b|\bcr\b", na=False, regex=True).any():
                ok = v.str.contains(r"\bcredit\b|\bcr\b", na=False, regex=True)
            else:
                continue
            if (~ok).any():
                notes.append(f"Kept only sales: left out {int((~ok).sum())} other rows ({c}).")
            keep &= ok
    df = df[keep]
    day = to_dates(df[dc]).dt.date
    amount = df[ac].map(_number_like)
    good = day.notna() & amount.notna() & (amount >= 0)
    skipped = int((~good).sum())
    count_col = _pick([c for c in cols if c not in (dc, ac)], COUNT_WORDS, lambda c: df[c].map(_number_like).notna().mean() >= 0.6)
    frame = pd.DataFrame({"day": day[good], "sales": amount[good]})
    if count_col:
        frame["bills"] = df.loc[good.index[good], count_col].map(_number_like).fillna(0).astype(int).values
        per_day = frame.groupby("day").agg(sales=("sales", "sum"), bills=("bills", "sum"))
    else:
        per_day = frame.groupby("day").agg(sales=("sales", "sum"), bills=("sales", "size"))
    if per_day.empty:
        raise ImportProblem(f"No sales rows with a date in {dc!r} and an amount in {ac!r}.")
    days = [{"day": d.isoformat(), "sales": round(float(r.sales), 2), "bills": int(r.bills)} for d, r in per_day.sort_index().iterrows()]
    if skipped:
        notes.append(f"Skipped {skipped} rows without a date or an amount (totals and blank lines).")
    return Imported(days=days, date_col=dc, amount_col=ac, rows_used=int(good.sum()), rows_skipped=skipped,
                    columns=cols[:40], notes=notes)
