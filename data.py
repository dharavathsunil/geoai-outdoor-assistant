import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path

import requests

HEADERS = {"User-Agent": "geoai-hackathon-dharavathsunil/0.1 (student project; contact: YOUR_EMAIL_HERE)"}
GEO_CACHE = Path(".cache") / "geocode.json"
_geo_lock = threading.Lock()
_last_nominatim = [0.0]


def _load_geo_cache():
    try:
        return json.loads(GEO_CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _nom_call(place, india_only):
    with _geo_lock:
        wait = 1.2 - (time.time() - _last_nominatim[0])
        if wait > 0:
            time.sleep(wait)
        _last_nominatim[0] = time.time()
    params = {"q": place, "format": "json", "limit": 3, "addressdetails": 1}
    if india_only:
        params["countrycodes"] = "in"
    r = requests.get("https://nominatim.openstreetmap.org/search",
                     params=params, headers=HEADERS, timeout=8)
    r.raise_for_status()
    return r.json()


def _nominatim(place):
    ind = _nom_call(place, True)
    top = ind[0] if ind else None
    imp = float(top.get("importance", 0) or 0) if top else 0.0
    if top is None or imp < 0.35:          # weak Indian match: is there a major foreign place?
        world = _nom_call(place, False)
        if world:
            w = world[0]
            cc = (w.get("address") or {}).get("country_code", "")
            if cc != "in" and float(w.get("importance", 0) or 0) >= 0.6:
                return "FOREIGN"
    if top is None:
        return None
    return float(top["lat"]), float(top["lon"]), top["display_name"]


def _photon(place):
    r = requests.get("https://photon.komoot.io/api/",
                     params={"q": place, "limit": 5, "lang": "en"}, headers=HEADERS, timeout=8)
    r.raise_for_status()
    for f in r.json().get("features", []):
        p = f.get("properties", {})
        if str(p.get("countrycode", "")).upper() != "IN":
            continue
        lon, lat = f["geometry"]["coordinates"]
        name = ", ".join(x for x in [p.get("name"), p.get("district") or p.get("locality"),
                                     p.get("city"), p.get("state")] if x)
        return lat, lon, name
    return None


def _open_meteo_geo(place):
    r = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                     params={"name": place.split(",")[0], "count": 10, "language": "en", "format": "json"},
                     timeout=8)
    r.raise_for_status()
    for x in r.json().get("results") or []:
        if x.get("country_code") == "IN":
            name = ", ".join(v for v in [x.get("name"), x.get("admin2"), x.get("admin1")] if v)
            return x["latitude"], x["longitude"], name
    return None


def geocode(place: str):
    """Place name -> (lat, lon, display_name), "FOREIGN" for places outside India, or None.
    Cached on disk. Other geocoders are used only when Nominatim errors out."""
    key = re.sub(r"\s+", " ", place.strip().lower())
    cache = _load_geo_cache()
    if key in cache:
        v = cache[key]
        return v if isinstance(v, str) else (v[0], v[1], v[2])

    result, ok = None, False
    try:
        result, ok = _nominatim(place), True
    except Exception:
        pass
    if not ok:
        for fn in (_photon, _open_meteo_geo):
            try:
                result, ok = fn(place), True
            except Exception:
                continue
            if result:
                break
    if not ok:
        raise RuntimeError("all geocoders failed")

    if result:
        try:
            cache[key] = result if isinstance(result, str) else list(result)
            GEO_CACHE.parent.mkdir(exist_ok=True)
            GEO_CACHE.write_text(json.dumps(cache), encoding="utf-8")
        except Exception:
            pass
    return result


def get_weather(lat: float, lon: float, days: int = 7):
    """Hourly forecast from Open-Meteo."""
    r = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "hourly": "temperature_2m,apparent_temperature,relative_humidity_2m,"
                      "precipitation_probability,precipitation,wind_speed_10m,"
                      "wind_direction_10m,cloud_cover,uv_index",
            "daily": "sunrise,sunset",
            "timezone": "Asia/Kolkata",
            "forecast_days": days,
        },
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def get_air_quality(lat: float, lon: float, days: int = 5):
    """Hourly air quality from Open-Meteo."""
    r = requests.get(
        "https://air-quality-api.open-meteo.com/v1/air-quality",
        params={
            "latitude": lat,
            "longitude": lon,
            "hourly": "pm2_5,pm10,us_aqi,ozone,nitrogen_dioxide",
            "timezone": "Asia/Kolkata",
            "forecast_days": days,
        },
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


if __name__ == "__main__":
    for p in ("Koregaon Park, Pune", "London"):
        print(p, "->", geocode(p))