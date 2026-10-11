"""A launch plan as a PDF or an Excel workbook, built from the same view and
numbers as the dashboard (tools/builtin/files.py writers)."""

from harness.launch import kinds

DISCLAIMER = ("These are estimates to plan with, not financial advice. Prices marked \"estimate\" are Hangul's rough "
              "ranges; sourced prices are from the linked pages on the date shown. Check quotes with sellers before "
              "you spend.")


def _rs(v) -> str:
    return "—" if v is None else f"₹{round(v):,}"


def _cell(text) -> str:
    return str(text if text is not None else "").replace("|", "/").replace("\n", " ")


def markdown(p: dict) -> str:
    e = p["economics"]
    k = kinds.get(p["kind"])
    unit = k.unit if k else "sale"
    lines = [f"# {p['title']}", "", DISCLAIMER, "", "## The numbers", "",
             "| | |", "|---|---|",
             (f"| Start-up cost | {_rs(e['startup_total'])} (one-off {_rs(e['one_off'])} + {e['working_capital_months']:g} "
              f"months of running costs {_rs(e['working_capital'])}) |"),
             f"| Monthly revenue | {_rs(e['revenue'])} ({e['units_per_day']:g} {unit}s a day at {_rs(e['price'])}) |",
             f"| Monthly fixed costs | {_rs(e['fixed'])} |",
             f"| Monthly profit | {_rs(e['profit'])} |",
             f"| Break-even | {e['breakeven_per_day'] or '—'} {unit}s a day |",
             f"| Payback | {str(e['payback_months']) + ' months' if e['payback_months'] else 'not at these numbers'} |"]
    if e.get("budget"):
        lines.append(f"| Your budget | {_rs(e['budget'])} ({'spare ' + _rs(e['budget_gap']) if e['budget_gap'] >= 0 else 'short by ' + _rs(-e['budget_gap'])}) |")
    lines += ["", "## Scenarios", "", "| | Sales a day | Revenue | Profit | Payback |", "|---|---|---|---|---|"]
    for name, s in e["scenarios"].items():
        lines.append(f"| {name.title()} | {s['units_per_day']:g} | {_rs(s['revenue'])} | {_rs(s['profit'])} | "
                     f"{str(s['payback_months']) + ' mo' if s['payback_months'] else '—'} |")
    for cat, label in kinds.CATEGORIES.items():
        rows = [it for it in p["items"] if it["category"] == cat and it.get("include", True)]
        if not rows:
            continue
        lines += ["", f"## {label}", "", "| Item | Qty | Each | Range | Source |", "|---|---|---|---|---|"]
        for it in rows:
            src = it["sellers"][0]["seller"] if it.get("sellers") else ("your number" if it["status"] == "user" else "estimate")
            lines.append(f"| {_cell(it['name'])}{' (monthly)' if it.get('monthly') else ''} | {it['qty']} | "
                         f"{_rs(it['amount'])} | {_rs(it['low'])}-{_rs(it['high'])} | {_cell(src)} |")
    lines += ["", "## Industry figures", "", "| Figure | Value | Source |", "|---|---|---|"]
    for b in p["benchmarks"]:
        lines.append(f"| {_cell(b['label'])} | {_cell(b['value'])} | {_cell(b['source']['url'] if b.get('source') else 'estimate')} |")
    sellers = [(it["name"], s) for it in p["items"] for s in it.get("sellers") or []]
    if sellers:
        lines += ["", "## Sellers found", ""]
        lines += [f"- {_cell(n)}: {_cell(s['seller'])}, {_rs(s['price'])} — {s['url']}" for n, s in sellers]
    return "\n".join(lines) + "\n"


def sheets(p: dict) -> list[dict]:
    e = p["economics"]
    items = [["Category", "Item", "Monthly", "Included", "Qty", "Each (₹)", "Total (₹)", "Low (₹)", "High (₹)",
              "Status", "Seller", "Link", "Checked"]]
    for it in p["items"]:
        s = (it.get("sellers") or [{}])[0]
        items.append([kinds.CATEGORIES.get(it["category"], it["category"]), it["name"], "yes" if it.get("monthly") else "",
                      "yes" if it.get("include", True) else "no", it["qty"], it["amount"],
                      it["amount"] * it["qty"] if it.get("include", True) else 0, it["low"], it["high"], it["status"],
                      s.get("seller", ""), s.get("url", ""), (it.get("checked_at") or "")[:10]])
    summary = [["Figure", "Value"], ["Start-up cost (₹)", e["startup_total"]], ["One-off items (₹)", e["one_off"]],
               ["Working capital (₹)", e["working_capital"]], ["Monthly revenue (₹)", e["revenue"]],
               ["Monthly fixed costs (₹)", e["fixed"]], ["Monthly profit (₹)", e["profit"]],
               ["Break-even (sales a day)", e["breakeven_per_day"]], ["Payback (months)", e["payback_months"]],
               ["Price per sale (₹)", e["price"]], ["Sales a day", e["units_per_day"]],
               ["Days open a month", e["days_per_month"]], ["Variable costs (% of price)", round(e["variable_share"] * 100, 1)],
               [], ["Note", DISCLAIMER]]
    bench = [["Figure", "Value", "Status", "Source"]] + [
        [b["label"], b["value"], b["status"], b["source"]["url"] if b.get("source") else ""] for b in p["benchmarks"]]
    return [{"name": "Summary", "rows": summary}, {"name": "Checklist", "rows": items},
            {"name": "Industry figures", "rows": bench}]


def build(p: dict, fmt: str) -> bytes:
    from harness.tools.builtin import files
    if fmt == "xlsx":
        return files.write_xlsx(sheets(p))
    return files.build("pdf", p["title"], markdown(p), None)
