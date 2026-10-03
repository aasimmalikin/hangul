"""maps_search and travel_time: places, addresses and how long it takes to get
somewhere (Plus plan).

Built on OpenStreetMap, which needs no API key:
  * Nominatim (geocoding / place search). Its usage policy asks for an
    identifying User-Agent with a contact address and at most one request per
    second, enforced here in-process (like the arXiv connector).
  * The FOSSGIS OSRM servers (routing.openstreetmap.de) for car, bike and foot.

Neither knows live traffic or public transport, so every route also carries a
Google Maps directions link (a plain URL, no key) for those. For heavy traffic
in production, swap in a paid geocoder/router behind the same two tools.
"""

import asyncio
import time
from urllib.parse import quote_plus

import httpx

from harness.config import get_settings
from harness.tools.base import Tool, ToolOutput

NOMINATIM = "https://nominatim.openstreetmap.org/search"
OSRM = "https://routing.openstreetmap.de/routed-{profile}/route/v1/driving/{a};{b}"
# fallback for cars when the FOSSGIS server is slow (the project's demo server, car only)
OSRM_CAR_FALLBACK = "https://router.project-osrm.org/route/v1/driving/{a};{b}"
PROFILES = {"driving": "car", "car": "car", "cycling": "bike", "bike": "bike", "walking": "foot", "foot": "foot"}
GMAPS_MODE = {"car": "driving", "bike": "bicycling", "foot": "walking"}

_lock = asyncio.Lock()
_last = 0.0


def _agent() -> str:
    s = get_settings()
    contact = s.maps_contact_email or s.email_from or s.app_url
    return f"HangulAssistant/1.0 ({contact})"


async def _nominatim(client: httpx.AsyncClient, q: str, limit: int = 5) -> list[dict]:
    """One Nominatim search, never more than one per second across the process."""
    global _last
    async with _lock:
        wait = 1.05 - (time.monotonic() - _last)
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            r = await client.get(NOMINATIM, params={"q": q, "format": "jsonv2", "limit": limit, "addressdetails": 0},
                                 headers={"User-Agent": _agent(), "Accept-Language": "en"})
        finally:
            _last = time.monotonic()
    r.raise_for_status()
    return r.json()


def gmaps_search(q: str) -> str:
    return f"https://www.google.com/maps/search/?api=1&query={quote_plus(q)}"


def gmaps_directions(origin: str, destination: str, mode: str) -> str:
    return (f"https://www.google.com/maps/dir/?api=1&origin={quote_plus(origin)}"
            f"&destination={quote_plus(destination)}&travelmode={mode}")


def fmt_duration(seconds: float) -> str:
    m = round(seconds / 60)
    return f"{m} min" if m < 60 else f"{m // 60} h {m % 60} min"


async def maps_search(query: str, near: str = "", limit: int = 5) -> ToolOutput | str:
    q = f"{query}, {near}" if near else query
    try:
        async with httpx.AsyncClient(timeout=12) as c:
            found = await _nominatim(c, q, max(1, min(int(limit or 5), 10)))
    except httpx.HTTPError as e:
        return f"The map service is unavailable right now ({type(e).__name__})."
    if not found:
        return f"Nothing found for {q!r}. Try adding the city or area."
    places = [{"name": p.get("name") or p.get("display_name", "").split(",")[0],
               "address": p.get("display_name", ""), "type": (p.get("type") or "").replace("_", " "),
               "lat": float(p["lat"]), "lon": float(p["lon"]),
               "link": gmaps_search(p.get("display_name") or q)} for p in found]
    text = "\n".join(f"{i + 1}. {p['name']} ({p['type']}) — {p['address']}" for i, p in enumerate(places))
    return ToolOutput(text + "\n(OpenStreetMap data; opening hours and ratings are not included.)",
                      {"kind": "places", "query": q, "places": places})


async def travel_time(origin: str, destination: str, mode: str = "driving") -> ToolOutput | str:
    profile = PROFILES.get((mode or "driving").lower())
    link_mode = GMAPS_MODE.get(profile or "", "transit")
    link = gmaps_directions(origin, destination, link_mode if profile else "transit")
    if profile is None:          # transit, flights…: no free router; hand over to Google Maps
        return ToolOutput(f"Public transport times aren't available here; directions: {link}",
                          {"kind": "route", "origin": origin, "destination": destination, "mode": mode, "link": link})
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            a = await _nominatim(c, origin, 1)
            b = await _nominatim(c, destination, 1)
            if not a or not b:
                return f"Couldn't find {'the start' if not a else 'the destination'} on the map. Ask for a fuller address."
            pa, pb = f"{a[0]['lon']},{a[0]['lat']}", f"{b[0]['lon']},{b[0]['lat']}"
            urls = [OSRM.format(profile=profile, a=pa, b=pb)]
            if profile == "car":
                urls.append(OSRM_CAR_FALLBACK.format(a=pa, b=pb))
            routes, last_err = [], None
            for url in urls:
                try:
                    r = await c.get(url, params={"overview": "false"}, headers={"User-Agent": _agent()}, timeout=12)
                    r.raise_for_status()
                    routes = r.json().get("routes") or []
                    break
                except httpx.HTTPError as e:
                    last_err = e
            if not routes and last_err is not None:
                raise last_err
    except httpx.HTTPError as e:
        return f"The routing service is unavailable right now ({type(e).__name__}). Directions: {link}"
    if not routes:
        return f"No {mode} route found between those places. Directions: {link}"
    km, secs = routes[0]["distance"] / 1000, routes[0]["duration"]
    names = (a[0].get("display_name", origin).split(",")[0], b[0].get("display_name", destination).split(",")[0])
    return ToolOutput(
        f"{mode.capitalize()} from {names[0]} to {names[1]}: about {fmt_duration(secs)}, {km:.1f} km "
        f"(no live traffic). Directions: {link}",
        {"kind": "route", "origin": names[0], "destination": names[1], "mode": profile,
         "minutes": round(secs / 60), "km": round(km, 1), "link": link})


MAPS_SEARCH_TOOL = Tool(
    name="maps_search",
    description=(
        "Find places or addresses on the map: 'pharmacies near Koregaon Park, Pune', 'Phoenix Mall Pune', an "
        "address. Pass `query` and, if useful, `near` (an area or city -- ask the user if you don't know where "
        "they are). Returns names, addresses and map links."),
    parameter={
        "type": "object",
        "properties": {"query": {"type": "string"}, "near": {"type": "string"}, "limit": {"type": "integer"}},
        "required": ["query"],
    },
    handler=maps_search,
)

TRAVEL_TIME_TOOL = Tool(
    name="travel_time",
    description=(
        "How long it takes to get from one place to another by driving, cycling or walking (distance and time, "
        "without live traffic), plus a Google Maps directions link. For public transport pass mode='transit' to "
        "get the directions link. Use full place names or addresses."),
    parameter={
        "type": "object",
        "properties": {
            "origin": {"type": "string"}, "destination": {"type": "string"},
            "mode": {"type": "string", "enum": ["driving", "cycling", "walking", "transit"]},
        },
        "required": ["origin", "destination"],
    },
    handler=travel_time,
)
