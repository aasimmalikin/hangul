"""Per-user personalisation (user_settings) and the prompt block built from it."""

from dataclasses import asdict, dataclass
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from harness.db.base import SessionLocal
from harness.db.models import UserSettings

TONES = ("concise", "balanced", "detailed")

# Who the user is, picked in onboarding or /settings. The text goes into the
# system prompt so answers fit them; the web uses the key for starter prompts
# and billing.plans.RECOMMENDED for the plan it suggests. "" = not chosen.
PERSONAS: dict[str, str] = {
    "founder": "Founder or business owner: their inbox, calendar and decisions matter most. Be brief and action-first; "
               "flag what needs a decision or a reply.",
    "developer": "Software developer: comfortable with technical detail, code and exact commands. Be precise; skip "
                 "basics they already know.",
    "student": "Student: deadlines, studying and research. Explain clearly, cite sources, and help them plan their time.",
    "professional": "Working professional: meetings, email and getting work done. Keep answers practical and ready to use.",
    "personal": "Using Hangul for everyday life: reminders, plans, errands and family. Keep it friendly and simple.",
}


@dataclass
class Settings:
    display_name: str = ""
    instructions: str = ""
    tone: str = "balanced"
    timezone: str = "UTC"
    language: str = ""
    timezone_auto: bool = True
    city: str = ""
    onboarded: bool = False
    home_address: str = ""
    persona: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def _row_to(row: UserSettings | None) -> Settings:
    if row is None:
        return Settings()
    return Settings(display_name=row.display_name, instructions=row.instructions, tone=row.tone,
                    timezone=row.timezone, language=row.language,
                    timezone_auto=bool(row.timezone_auto) if row.timezone_auto is not None else True,
                    city=getattr(row, "city", "") or "", onboarded=bool(getattr(row, "onboarded", False)),
                    home_address=getattr(row, "home_address", "") or "",
                    persona=getattr(row, "persona", "") or "")


def get_settings(user_id: str) -> Settings:
    with SessionLocal() as s:
        return _row_to(s.get(UserSettings, int(user_id)))


# Browsers (Chrome's ICU) still report some zones by their pre-rename names;
# they work, but users should see the name they know.
LEGACY_ZONES = {
    "Asia/Calcutta": "Asia/Kolkata", "Asia/Katmandu": "Asia/Kathmandu", "Asia/Saigon": "Asia/Ho_Chi_Minh",
    "Asia/Rangoon": "Asia/Yangon", "Asia/Dacca": "Asia/Dhaka", "Asia/Thimbu": "Asia/Thimphu",
    "Asia/Ulan_Bator": "Asia/Ulaanbaatar", "Europe/Kiev": "Europe/Kyiv", "Atlantic/Faeroe": "Atlantic/Faroe",
    "America/Godthab": "America/Nuuk", "Pacific/Truk": "Pacific/Chuuk", "Pacific/Ponape": "Pacific/Pohnpei",
    "Pacific/Enderbury": "Pacific/Kanton", "Africa/Asmera": "Africa/Asmara",
    "America/Buenos_Aires": "America/Argentina/Buenos_Aires", "America/Indianapolis": "America/Indiana/Indianapolis",
}


def canonical_timezone(name: str) -> str:
    return LEGACY_ZONES.get(name, name)


def valid_timezone(name: str) -> bool:
    try:
        ZoneInfo(name)
        return True
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return False


def save_settings(user_id: str, values: Settings) -> Settings:
    if values.tone not in TONES:
        raise ValueError(f"tone must be one of {TONES}")
    if not valid_timezone(values.timezone):
        raise ValueError(f"unknown timezone {values.timezone!r}")
    if values.persona and values.persona not in PERSONAS:
        raise ValueError(f"persona must be one of {tuple(PERSONAS)}")
    with SessionLocal() as s:
        row = s.get(UserSettings, int(user_id))
        if row is None:
            row = UserSettings(user_id=int(user_id))
            s.add(row)
        row.display_name = values.display_name.strip()[:80]
        row.instructions = values.instructions.strip()[:2000]
        row.tone = values.tone
        row.timezone = values.timezone
        row.timezone_auto = values.timezone_auto
        row.city = values.city.strip()[:80]
        row.home_address = values.home_address.strip()[:200]
        row.persona = values.persona
        row.onboarded = bool(row.onboarded) or values.onboarded
        row.language = values.language.strip()[:16]
        s.commit()
        return _row_to(row)


def mark_onboarded(user_id: str) -> None:
    """The first-run walkthrough is done (or skipped); never show it again."""
    with SessionLocal() as s:
        row = s.get(UserSettings, int(user_id))
        if row is None:
            row = UserSettings(user_id=int(user_id))
            s.add(row)
        row.onboarded = True
        s.commit()


def adopt_device_timezone(user_id: str, tz: str | None) -> Settings:
    """Follow the user's device: when their timezone is automatic (the
    default), store the timezone the browser reports, so reminders, emails,
    scheduled tasks and the agent's "local time now" match where they are --
    including after they travel. A pinned timezone is left alone. Returns the
    settings to use for this request."""
    tz = canonical_timezone(tz) if tz else tz
    with SessionLocal() as s:
        row = s.get(UserSettings, int(user_id))
        current = _row_to(row)
        if not tz or not valid_timezone(tz) or not current.timezone_auto or tz == current.timezone:
            return current
        if row is None:
            row = UserSettings(user_id=int(user_id))
            s.add(row)
        row.timezone = tz
        row.timezone_auto = True
        s.commit()
        out = _row_to(row)
    from harness.db.tasks import retime_daily
    retime_daily(user_id, tz)
    return out


TONE_TEXT = {
    "concise": "Be brief: lead with the answer, skip preamble, no restating the question.",
    "balanced": "Answer directly, then add the context that matters.",
    "detailed": "Be thorough: explain reasoning, alternatives and caveats when they matter.",
}


def prompt_block(st: Settings, now: datetime | None = None) -> str:
    """The personalisation block for the system prompt. Custom instructions
    come from the user and rank like their messages: honoured, but they cannot
    override the rules above them (the loop says so explicitly)."""
    lines = []
    if st.display_name:
        lines.append(f"Name: {st.display_name}")
    try:
        tz = ZoneInfo(st.timezone or "UTC")
        local = (now or datetime.now(tz)).astimezone(tz)
        lines.append(f"Timezone: {st.timezone} (local time now: {local.strftime('%A %Y-%m-%d %H:%M')})")
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        pass
    if st.city:
        lines.append(f"Home city: {st.city} (use it for weather, places and 'near me' unless they say otherwise)")
    if st.language:
        lines.append(f"Preferred language: {st.language}")
    if st.persona in PERSONAS:
        lines.append(f"Who they are: {PERSONAS[st.persona]}")
    lines.append(f"Tone: {TONE_TEXT.get(st.tone, TONE_TEXT['balanced'])}")
    if st.instructions:
        lines.append("Custom instructions from the user (follow them unless they conflict with the rules above):\n"
                     + st.instructions)
    return "=== ABOUT THE USER ===\n" + "\n".join(lines)
