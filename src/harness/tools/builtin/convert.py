"""convert (units + currency) and world_clock.

Units are a local table -- exact, instant, free. Currency uses the ECB
reference rates via frankfurter.dev (no key; updated once per working day),
so it is clearly labelled as an indicative rate, not a bank quote.
"""

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from harness.tools.base import Tool, ToolOutput

FX_URL = "https://api.frankfurter.dev/v1/latest"

# unit -> (dimension, factor to the base unit)
_UNITS: dict[str, tuple[str, float]] = {}


def _add(dim: str, factor: float, *names: str) -> None:
    for n in names:
        _UNITS[n] = (dim, factor)


_add("length", 1, "m", "meter", "meters", "metre", "metres")
_add("length", 1000, "km", "kilometer", "kilometers", "kilometre", "kilometres")
_add("length", 0.01, "cm", "centimeter", "centimeters", "centimetre", "centimetres")
_add("length", 0.001, "mm", "millimeter", "millimeters", "millimetre", "millimetres")
_add("length", 0.0254, "in", "inch", "inches")
_add("length", 0.3048, "ft", "foot", "feet")
_add("length", 0.9144, "yd", "yard", "yards")
_add("length", 1609.344, "mi", "mile", "miles")
_add("mass", 1, "kg", "kilogram", "kilograms", "kilo", "kilos")
_add("mass", 0.001, "g", "gram", "grams")
_add("mass", 0.45359237, "lb", "lbs", "pound", "pounds")
_add("mass", 0.028349523125, "oz", "ounce", "ounces")
_add("mass", 1000, "t", "tonne", "tonnes", "ton", "tons")
_add("volume", 1, "l", "liter", "liters", "litre", "litres")
_add("volume", 0.001, "ml", "milliliter", "milliliters", "millilitre", "millilitres")
_add("volume", 3.785411784, "gal", "gallon", "gallons")
_add("volume", 0.2365882365, "cup", "cups")
_add("volume", 0.0295735295625, "floz", "fl oz", "fluid ounce", "fluid ounces")
_add("speed", 1, "km/h", "kmh", "kph")
_add("speed", 1.609344, "mph")
_add("speed", 3.6, "m/s")
_add("area", 1, "m2", "sqm", "square meter", "square meters", "square metre", "square metres")
_add("area", 0.09290304, "sqft", "ft2", "square foot", "square feet")
_add("area", 10_000, "hectare", "hectares", "ha")
_add("area", 4046.8564224, "acre", "acres")
_add("data", 1, "b", "byte", "bytes")
_add("data", 1024, "kb", "kilobyte", "kilobytes")
_add("data", 1024 ** 2, "mb", "megabyte", "megabytes")
_add("data", 1024 ** 3, "gb", "gigabyte", "gigabytes")
_add("data", 1024 ** 4, "tb", "terabyte", "terabytes")

_TEMP = {"c": "C", "celsius": "C", "°c": "C", "f": "F", "fahrenheit": "F", "°f": "F", "k": "K", "kelvin": "K"}


def _num(x: float) -> str:
    return f"{x:,.4f}".rstrip("0").rstrip(".") if abs(x) < 1e15 else f"{x:.4g}"


def convert_units(value: float, from_unit: str, to_unit: str) -> float:
    f, t = from_unit.strip().lower(), to_unit.strip().lower()
    if f in _TEMP and t in _TEMP:
        c = {"C": value, "F": (value - 32) * 5 / 9, "K": value - 273.15}[_TEMP[f]]
        return {"C": c, "F": c * 9 / 5 + 32, "K": c + 273.15}[_TEMP[t]]
    if f not in _UNITS or t not in _UNITS:
        raise ValueError(f"Unknown unit {from_unit if f not in _UNITS else to_unit!r}.")
    (df, ff), (dt, ft) = _UNITS[f], _UNITS[t]
    if df != dt:
        raise ValueError(f"Can't convert {df} to {dt}.")
    return value * ff / ft


def _is_currency(code: str) -> bool:
    return len(code.strip()) == 3 and code.strip().isalpha()


async def convert(value: float, from_unit: str, to_unit: str) -> ToolOutput | str:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "value must be a number."
    if _is_currency(from_unit) and _is_currency(to_unit) and from_unit.lower() not in _UNITS:
        f, t = from_unit.upper(), to_unit.upper()
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(FX_URL, params={"amount": value, "from": f, "to": t})
            if r.status_code == 404 or r.status_code == 422:
                return f"Unknown currency {f} or {t}."
            r.raise_for_status()
            data = r.json()
        except httpx.HTTPError as e:
            return f"The exchange-rate service is unavailable ({type(e).__name__})."
        out = data["rates"][t]
        text = f"{_num(value)} {f} = {_num(out)} {t} (ECB reference rate, {data.get('date')}; banks add a margin)."
        return ToolOutput(text, {"kind": "conversion", "from": f"{_num(value)} {f}", "to": f"{_num(out)} {t}",
                                 "note": f"ECB rate · {data.get('date')}"})
    try:
        out = convert_units(value, from_unit, to_unit)
    except ValueError as e:
        return str(e)
    return ToolOutput(f"{_num(value)} {from_unit} = {_num(out)} {to_unit}",
                      {"kind": "conversion", "from": f"{_num(value)} {from_unit}", "to": f"{_num(out)} {to_unit}"})


CONVERT_TOOL = Tool(
    name="convert",
    description=(
        "Convert units (length, weight, volume, temperature, speed, area, data size) or currencies "
        "(3-letter codes like USD, INR, EUR -- indicative daily rates). Use instead of doing the maths "
        "yourself. Example: value=500, from_unit='USD', to_unit='INR'; value=5.8, from_unit='ft', to_unit='cm'."),
    parameter={
        "type": "object",
        "properties": {
            "value": {"type": "number"},
            "from_unit": {"type": "string"},
            "to_unit": {"type": "string"},
        },
        "required": ["value", "from_unit", "to_unit"],
    },
    handler=convert,
)

# common cities people ask about -> IANA zone (anything else: pass the zone)
CITY_ZONES = {
    "london": "Europe/London", "paris": "Europe/Paris", "berlin": "Europe/Berlin", "madrid": "Europe/Madrid",
    "rome": "Europe/Rome", "amsterdam": "Europe/Amsterdam", "dublin": "Europe/Dublin", "moscow": "Europe/Moscow",
    "istanbul": "Europe/Istanbul", "dubai": "Asia/Dubai", "riyadh": "Asia/Riyadh", "karachi": "Asia/Karachi",
    "delhi": "Asia/Kolkata", "new delhi": "Asia/Kolkata", "mumbai": "Asia/Kolkata", "bangalore": "Asia/Kolkata",
    "bengaluru": "Asia/Kolkata", "kolkata": "Asia/Kolkata", "chennai": "Asia/Kolkata", "hyderabad": "Asia/Kolkata",
    "pune": "Asia/Kolkata", "dhaka": "Asia/Dhaka", "kathmandu": "Asia/Kathmandu", "colombo": "Asia/Colombo",
    "bangkok": "Asia/Bangkok", "jakarta": "Asia/Jakarta", "singapore": "Asia/Singapore", "kuala lumpur": "Asia/Kuala_Lumpur",
    "hong kong": "Asia/Hong_Kong", "shanghai": "Asia/Shanghai", "beijing": "Asia/Shanghai", "tokyo": "Asia/Tokyo",
    "seoul": "Asia/Seoul", "sydney": "Australia/Sydney", "melbourne": "Australia/Melbourne", "auckland": "Pacific/Auckland",
    "new york": "America/New_York", "boston": "America/New_York", "toronto": "America/Toronto", "chicago": "America/Chicago",
    "dallas": "America/Chicago", "denver": "America/Denver", "los angeles": "America/Los_Angeles",
    "san francisco": "America/Los_Angeles", "seattle": "America/Los_Angeles", "vancouver": "America/Vancouver",
    "mexico city": "America/Mexico_City", "sao paulo": "America/Sao_Paulo", "buenos aires": "America/Argentina/Buenos_Aires",
    "cairo": "Africa/Cairo", "lagos": "Africa/Lagos", "nairobi": "Africa/Nairobi", "johannesburg": "Africa/Johannesburg",
}


def zone_for(place: str) -> ZoneInfo:
    key = place.strip().lower()
    try:
        return ZoneInfo(CITY_ZONES.get(key, place.strip()))
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"Unknown place or timezone {place!r}; pass an IANA zone like 'Europe/London'.")


def make_world_clock_tool(user_tz: str = "UTC") -> Tool:
    async def world_clock(places: list[str], at: str = "") -> ToolOutput | str:
        """Times in ``places`` now, or at ``at`` (the USER's local time, 'YYYY-MM-DDTHH:MM')."""
        home = ZoneInfo(user_tz or "UTC")
        try:
            base = datetime.fromisoformat(at).replace(tzinfo=home) if at else datetime.now(home)
        except ValueError:
            return f"Could not read {at!r}; use 'YYYY-MM-DDTHH:MM'."
        rows, errors = [], []
        for p in (places or [])[:10]:
            try:
                z = zone_for(p)
            except ValueError as e:
                errors.append(str(e))
                continue
            t = base.astimezone(z)
            rows.append({"place": p, "zone": str(z), "time": t.strftime("%H:%M"), "day": t.strftime("%a %d %b")})
        if not rows:
            return " ".join(errors) or "Give at least one place."
        head = f"At {base.strftime('%H:%M %a')} your time ({user_tz}):" if at else "Right now:"
        text = head + "\n" + "\n".join(f"{r['place']}: {r['time']} ({r['day']})" for r in rows)
        return ToolOutput(text + ("\n" + " ".join(errors) if errors else ""),
                          {"kind": "world_clock", "rows": rows, "home": user_tz, "at": at or None})

    return Tool(
        name="world_clock",
        description=(
            "Current time in other cities/timezones, or what a given time of the USER's day is elsewhere "
            "('if I call at 6pm, what time is it in London?' -> at='YYYY-MM-DDT18:00'). `places` are city names "
            "or IANA zones."),
        parameter={
            "type": "object",
            "properties": {
                "places": {"type": "array", "items": {"type": "string"}},
                "at": {"type": "string", "description": "Optional: the user's local time 'YYYY-MM-DDTHH:MM'."},
            },
            "required": ["places"],
        },
        handler=world_clock,
    )
