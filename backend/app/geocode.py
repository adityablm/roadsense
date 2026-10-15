"""
Turns latitude/longitude into a readable address ("reverse geocoding"),
using OpenStreetMap's free Nominatim service.

Nominatim's rules: identify your app in the User-Agent, and at most 1 request
per second. We only call it when a complaint letter is drafted, and save the
result, so we stay far below that.
"""
import httpx

from . import config

URL = "https://nominatim.openstreetmap.org/reverse"
PARTS = ("road", "neighbourhood", "suburb", "city_district", "city", "state_district", "state", "postcode")


def reverse_geocode(lat: float, lng: float) -> str | None:
    contact = f" ({config.CONTACT_EMAIL})" if config.CONTACT_EMAIL else ""
    try:
        resp = httpx.get(
            URL,
            params={"format": "jsonv2", "lat": lat, "lon": lng, "zoom": 17, "addressdetails": 1},
            headers={"User-Agent": f"RoadSense/1.0 student project{contact}", "Accept-Language": "en"},
            timeout=8,
        )
        resp.raise_for_status()
        address = resp.json().get("address", {})
    except Exception:
        return None          # the letter still works with just coordinates
    seen, parts = set(), []
    for key in PARTS:
        value = address.get(key)
        if value and value not in seen:
            seen.add(value)
            parts.append(value)
    return ", ".join(parts) or None
