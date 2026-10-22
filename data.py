import json
import re
import threading
import time
from pathlib import Path
import requests
from datetime import datetime

HEADERS = {"User-Agent": "geoai-hackathon-dharavathsunil/0.1 (student project; contact: dharavathsunil110@gmail.com)"}


GEO_CACHE = Path(".cache") / "geocode.json"
_geo_lock = threading.Lock()
_last_nominatim = [0.0]


def _load_geo_cache():
    try:
        return json.loads(GEO_CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _nominatim(place):
    with _geo_lock:
        wait = 1.2 - (time.time() - _last_nominatim[0])
        if wait > 0:
            time.sleep(wait)
        _last_nominatim[0] = time.time()
    r = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": place, "format": "json", "limit": 1, "countrycodes": "in"},
        headers=HEADERS, timeout=8)
    r.raise_for_status()
    d = r.json()
    if not d:
        return None
    return float(d[0]["lat"]), float(d[0]["lon"]), d[0]["display_name"]


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
    """Place name -> (lat, lon, display_name). Cached; falls back only when a service errors."""
    key = re.sub(r"\s+", " ", place.strip().lower())
    cache = _load_geo_cache()
    if key in cache:
        v = cache[key]
        return v[0], v[1], v[2]

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
            cache[key] = list(result)
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
    place = "Koregaon Park, Pune"
    geo = geocode(place)
    if not geo:
        raise SystemExit("Place not found")
    lat, lon, name = geo
    print(f"Place: {name}\nCoordinates: {lat:.4f}, {lon:.4f}\n")

    w = get_weather(lat, lon)
    aq = get_air_quality(lat, lon)

    print("Sunrise/Sunset today:", w["daily"]["sunrise"][0], "/", w["daily"]["sunset"][0], "\n")
    print(f"{'Time':<17}{'Temp':>6}{'Feels':>7}{'Rain%':>7}{'Wind':>6}{'Dir':>5}{'UV':>5}{'AQI':>6}{'PM2.5':>7}")
    now = datetime.now().strftime("%Y-%m-%dT%H:00")
    times = w["hourly"]["time"]
    start = times.index(now) if now in times else 0
    for i in range(start, start + 24):
        h, a = w["hourly"], aq["hourly"]
        print(
            f"{times[i]:<17}"
            f"{h['temperature_2m'][i]:>6}{h['apparent_temperature'][i]:>7}"
            f"{h['precipitation_probability'][i]:>7}{h['wind_speed_10m'][i]:>6}"
            f"{h['wind_direction_10m'][i]:>5}{h['uv_index'][i]:>5}"
            f"{str(a['us_aqi'][i]):>6}{str(a['pm2_5'][i]):>7}"
        )
        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