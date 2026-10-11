"""Daily rain and temperature for a business's city, past and tomorrow.

Open-Meteo, no key (like the weather tool): the forecast API gives the last
92 days and the next two; the archive API anything older. Results are kept
in-process for an hour per place and range, and the past days are written
onto ``business_days`` so each is fetched once.
"""

import time
from datetime import date, timedelta

import httpx

from harness.logging import log
from harness.tools.builtin.weather import GEO

FORECAST = "https://api.open-meteo.com/v1/forecast"
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
RECENT_DAYS = 92
_cache: dict[tuple, tuple[float, dict]] = {}
TTL_S = 3600


async def geocode(city: str) -> tuple[float, float] | None:
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(GEO, params={"name": city.split(",")[0].strip(), "count": 1, "language": "en"})
            r.raise_for_status()
            hit = (r.json().get("results") or [None])[0]
    except httpx.HTTPError as e:
        log.warning("sales: geocoding failed", error=type(e).__name__)
        return None
    return (float(hit["latitude"]), float(hit["longitude"])) if hit else None


async def _daily(url: str, params: dict) -> dict[date, tuple[float | None, float | None]]:
    key = (url, tuple(sorted(params.items())))
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < TTL_S:
        return hit[1]
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(url, params={**params, "daily": "precipitation_sum,temperature_2m_max", "timezone": "auto"})
            r.raise_for_status()
            d = r.json().get("daily") or {}
    except httpx.HTTPError as e:
        log.warning("sales: weather fetch failed", url=url, error=type(e).__name__)
        return {}
    out = {date.fromisoformat(t): (rain, tmax) for t, rain, tmax in
           zip(d.get("time", []), d.get("precipitation_sum", []), d.get("temperature_2m_max", []))}
    _cache[key] = (time.monotonic(), out)
    return out


async def days(lat: float, lon: float, start: date, end: date, today: date) -> dict[date, tuple[float | None, float | None]]:
    """Rain (mm) and max temperature (°C) for every day from ``start`` to ``end``."""
    out: dict = {}
    recent_from = today - timedelta(days=RECENT_DAYS - 1)
    if start < recent_from:
        out.update(await _daily(ARCHIVE, {"latitude": round(lat, 3), "longitude": round(lon, 3),
                                          "start_date": start.isoformat(),
                                          "end_date": min(end, recent_from - timedelta(days=1)).isoformat()}))
    if end >= recent_from:
        out.update(await _daily(FORECAST, {"latitude": round(lat, 3), "longitude": round(lon, 3),
                                           "past_days": RECENT_DAYS, "forecast_days": 3}))
    return {d: v for d, v in out.items() if start <= d <= end}
