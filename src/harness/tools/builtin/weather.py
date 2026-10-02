"""weather: current conditions and a short forecast for a place.

Open-Meteo (geocoding + forecast): free, no key, no account, so it does not go
through the vault. Results come back as a ``weather`` card.
"""

import httpx

from harness.tools.base import Tool, ToolOutput

GEO = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST = "https://api.open-meteo.com/v1/forecast"

# WMO weather interpretation codes -> (label, icon name for the card)
WMO: dict[int, tuple[str, str]] = {
    0: ("Clear sky", "sun"), 1: ("Mainly clear", "sun"), 2: ("Partly cloudy", "cloud-sun"), 3: ("Overcast", "cloud"),
    45: ("Fog", "mist"), 48: ("Freezing fog", "mist"),
    51: ("Light drizzle", "cloud-rain"), 53: ("Drizzle", "cloud-rain"), 55: ("Heavy drizzle", "cloud-rain"),
    56: ("Freezing drizzle", "cloud-rain"), 57: ("Freezing drizzle", "cloud-rain"),
    61: ("Light rain", "cloud-rain"), 63: ("Rain", "cloud-rain"), 65: ("Heavy rain", "cloud-storm"),
    66: ("Freezing rain", "cloud-rain"), 67: ("Freezing rain", "cloud-rain"),
    71: ("Light snow", "snowflake"), 73: ("Snow", "snowflake"), 75: ("Heavy snow", "snowflake"), 77: ("Snow grains", "snowflake"),
    80: ("Rain showers", "cloud-rain"), 81: ("Rain showers", "cloud-rain"), 82: ("Violent showers", "cloud-storm"),
    85: ("Snow showers", "snowflake"), 86: ("Snow showers", "snowflake"),
    95: ("Thunderstorm", "cloud-storm"), 96: ("Thunderstorm, hail", "cloud-storm"), 99: ("Thunderstorm, hail", "cloud-storm"),
}


def describe(code) -> tuple[str, str]:
    return WMO.get(int(code or 0), ("Unknown", "cloud"))


async def _get(client: httpx.AsyncClient, url: str, params: dict) -> dict:
    r = await client.get(url, params=params)
    r.raise_for_status()
    return r.json()


async def weather(location: str, days: int = 3) -> ToolOutput | str:
    days = max(1, min(int(days or 3), 7))
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            geo = await _get(c, GEO, {"name": location.split(",")[0].strip(), "count": 5, "language": "en"})
            places = geo.get("results") or []
            if not places:
                return f"Could not find a place called {location!r}. Ask the user for a nearby city."
            # "Paris, US" -> prefer the matching country when given
            hint = location.split(",")[1].strip().lower() if "," in location else ""
            place = next((p for p in places if hint and hint in (p.get("country", "") + p.get("country_code", "")).lower()),
                         places[0])
            fc = await _get(c, FORECAST, {
                "latitude": place["latitude"], "longitude": place["longitude"], "timezone": "auto",
                "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,precipitation",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "forecast_days": days,
            })
    except httpx.HTTPError as e:
        return f"The weather service is unavailable right now ({type(e).__name__})."

    name = ", ".join(x for x in (place.get("name"), place.get("admin1"), place.get("country")) if x)
    cur = fc.get("current") or {}
    label, icon = describe(cur.get("weather_code"))
    d = fc.get("daily") or {}
    daily = [{
        "date": d["time"][i],
        "label": describe(d["weather_code"][i])[0], "icon": describe(d["weather_code"][i])[1],
        "max": d["temperature_2m_max"][i], "min": d["temperature_2m_min"][i],
        "rain_chance": (d.get("precipitation_probability_max") or [None] * len(d["time"]))[i],
    } for i in range(len(d.get("time", [])))]
    lines = [f"{name} now: {label}, {cur.get('temperature_2m')}°C (feels {cur.get('apparent_temperature')}°C), "
             f"humidity {cur.get('relative_humidity_2m')}%, wind {cur.get('wind_speed_10m')} km/h."]
    lines += [f"{x['date']}: {x['label']}, {x['min']}–{x['max']}°C, rain chance {x['rain_chance']}%" for x in daily]
    return ToolOutput("\n".join(lines), {
        "kind": "weather", "place": name, "timezone": fc.get("timezone"),
        "current": {"temp": cur.get("temperature_2m"), "feels": cur.get("apparent_temperature"),
                    "humidity": cur.get("relative_humidity_2m"), "wind": cur.get("wind_speed_10m"),
                    "label": label, "icon": icon},
        "daily": daily,
    })


WEATHER_TOOL = Tool(
    name="weather",
    description=(
        "Current weather and a forecast (up to 7 days) for a city. Use for 'do I need an umbrella', "
        "'weather in Pune this weekend'. Pass `location` as 'City' or 'City, Country'. If the user did not "
        "say where and you don't know their city (check recall), ask."),
    parameter={
        "type": "object",
        "properties": {
            "location": {"type": "string"},
            "days": {"type": "integer", "minimum": 1, "maximum": 7},
        },
        "required": ["location"],
    },
    handler=weather,
)
