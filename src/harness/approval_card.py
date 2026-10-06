"""What a waiting action will do, in words a person checks before tapping Approve.

One description used by the approval email, the /approve/<link> page and push
text, so they never disagree. A card is {title, rows: [[label, value]], body}:
the title is the question ("Create an event?"), rows are the facts that matter
(who it reaches, when), body is the long text (an email's body) if any.
"""

from datetime import datetime

TITLES = {
    "calendar__create_event": "Add an event to your calendar?",
    "calendar__update_event": "Change this calendar event?",
    "calendar__delete_event": "Delete this calendar event?",
    "gmail__send_message": "Send this email?",
    "gmail__send_draft": "Send this draft?",
    "gmail__create_draft": "Save this email as a draft?",
    "docs__append_text": "Add this text to the document?",
    "sheets__append_rows": "Add these rows to the spreadsheet?",
    "sheets__create_spreadsheet": "Create this spreadsheet?",
    "github__create_issue": "Open this GitHub issue?",
    "github__comment": "Post this GitHub comment?",
    "notion__append_to_page": "Add this to the Notion page?",
    "notion__create_page": "Create this Notion page?",
    "slack__send_message": "Post this in Slack?",
    "web_search": "Search the web?",
    "read_webpage": "Open this web page?",
}


def _when(value: object) -> str:
    """'2026-10-06T17:15:00+05:30' -> 'Tue 6 Oct, 5:15 PM'; a date or anything else as given."""
    text = str(value or "")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return text
    if "T" not in text:
        return dt.strftime("%a %-d %b")
    return dt.strftime("%a %-d %b, %-I:%M %p")


def card(pending: dict | None) -> dict:
    pending = pending or {}
    name, a = pending.get("name", ""), pending.get("arguments") or {}
    title = TITLES.get(name, f"Run {name.replace('__', ' ').replace('_', ' ')}?")
    rows: list[list[str]] = []
    body = ""
    if name.startswith("calendar__"):
        rows += [["Event", str(a.get("summary") or "")]] if a.get("summary") else []
        if a.get("start"):
            start, end = _when(a.get("start")), _when(a.get("end"))
            same_day = end.split(",")[0] == start.split(",")[0] and "," in end
            rows.append(["When", f"{start} – {end.split(', ', 1)[-1] if same_day else end}" if a.get("end") else start])
        if a.get("location"):
            rows.append(["Where", str(a["location"])])
        rows.append(["Invites", ", ".join(map(str, a.get("attendees") or [])) or "Nobody — only your calendar"])
        body = str(a.get("description") or "")
    elif name.startswith("gmail__"):
        rows += [[k.capitalize(), str(a[k])] for k in ("to", "cc", "subject") if a.get(k)]
        body = str(a.get("body") or "")
    elif name.startswith("github__"):
        rows += [["Repository", str(a.get("repo") or "")]]
        rows += [["Issue", f"#{a['number']}"]] if a.get("number") else []
        rows += [["Title", str(a["title"])]] if a.get("title") else []
        body = str(a.get("body") or "")
    elif name.startswith("slack__"):
        rows.append(["Channel", str(a.get("channel_id") or "")])
        body = str(a.get("text") or "")
    else:
        for k, v in a.items():
            if isinstance(v, str) and len(v) > 200:
                body = body or v
            else:
                rows.append([k.replace("_", " ").capitalize(), str(v)])
    return {"title": title, "rows": [r for r in rows if r[1]], "body": body[:4000]}


def one_line(pending: dict | None) -> str:
    """A notification-length version: 'Add an event to your calendar? Focus · Tue 6 Oct, 5:15 PM'."""
    c = card(pending)
    facts = " · ".join(v for k, v in c["rows"][:2] if k != "Invites")
    return f"{c['title']} {facts}".strip()
