import hashlib
import json
import math
import time
import re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

CACHE_DIR = Path(".cache")
CACHE_DIR.mkdir(exist_ok=True)
CACHE_TTL = 7 * 24 * 3600  # seconds

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
HEADERS = {"User-Agent": "geoai-hackathon-sunil/0.1 (student project)"}

# Which OSM tags count as a venue for each activity
ACTIVITY_TAGS = {
    "walking":     [("leisure", "park"), ("leisure", "garden"), ("leisure", "nature_reserve")],
    "running":     [("leisure", "park"), ("leisure", "track"), ("leisure", "nature_reserve")],
    "cycling":     [("leisure", "park"), ("leisure", "track")],
    "golf":        [("leisure", "golf_course")],
    "cricket":     [("sport", "cricket")],
    "football":    [("sport", "soccer")],
    "tennis":      [("sport", "tennis")],
    "hiking":      [("natural", "peak"), ("leisure", "nature_reserve"), ("tourism", "viewpoint")],
    "picnic":      [("leisure", "park"), ("leisure", "garden"), ("tourism", "picnic_site")],
    "event":       [("amenity", "events_venue"), ("amenity", "community_centre"), ("leisure", "park")],
    "photography": [("tourism", "viewpoint"), ("leisure", "park"), ("natural", "beach"), ("natural", "peak")],
}


# ---------- geometry helpers ----------
def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def bearing_deg(lat1, lon1, lat2, lon2):
    """Compass bearing from point 1 to point 2 (0 = north, 90 = east)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def angle_diff(a, b):
    d = abs(a - b) % 360
    return min(d, 360 - d)


def is_downwind(bearing_to_source, wind_from_deg, tolerance=45):
    """Wind direction is where the wind comes FROM. A place is downwind of a
    source if the source lies in the direction the wind is coming from."""
    return angle_diff(bearing_to_source, wind_from_deg) <= tolerance


# ---------- Overpass with cache ----------
def _try_overpass(url, query):
    r = requests.post(url, data={"data": query}, headers=HEADERS, timeout=(6, 35))
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    data = r.json()
    remark = data.get("remark", "").lower()
    if "runtime error" in remark or "timed out" in remark:
        raise RuntimeError("server-side timeout")
    return data


def run_overpass(query: str):
    key = hashlib.md5(query.encode()).hexdigest()
    f = CACHE_DIR / f"{key}.json"
    if f.exists() and time.time() - f.stat().st_mtime < CACHE_TTL:
        return json.loads(f.read_text(encoding="utf-8"))

    errors = []
    for attempt in range(2):
        ex = ThreadPoolExecutor(max_workers=len(OVERPASS_URLS))
        futs = {ex.submit(_try_overpass, u, query): u for u in OVERPASS_URLS}
        try:
            for fut in as_completed(futs):
                try:
                    data = fut.result()
                except Exception as e:
                    errors.append(f"{futs[fut]} -> {e}")
                    continue
                if data.get("elements"):
                    f.write_text(json.dumps(data), encoding="utf-8")
                return data
        finally:
            ex.shutdown(wait=False, cancel_futures=True)
        time.sleep(2)

    if f.exists():
        print("WARNING: Overpass down, using stale cache")
        return json.loads(f.read_text(encoding="utf-8"))
    raise RuntimeError("Overpass failed:\n  " + "\n  ".join(errors))


def el_point(el):
    if el["type"] == "node":
        return el["lat"], el["lon"]
    c = el.get("center")
    return (c["lat"], c["lon"]) if c else (None, None)


# ---------- candidate venues ----------
def bbox_from_radius(lat, lon, r_m):
    dlat = r_m / 111320
    dlon = r_m / (111320 * math.cos(math.radians(lat)))
    return lat - dlat, lon - dlon, lat + dlat, lon + dlon  # south, west, north, east


NOMINATIM_TERMS = {
    "walking": "park","running": "park", "cycling": "park", "golf": "golf course",
    "cricket": "cricket ground", "football": "football ground",
    "tennis": "tennis court", "hiking": "viewpoint", "picnic": "park",
    "event": "community hall", "photography": "viewpoint",
}


def _nominatim_candidates(lat, lon, activity, radius_m, limit):
    s, w, n, e = bbox_from_radius(lat, lon, radius_m)
    r = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": NOMINATIM_TERMS[activity], "format": "json", "limit": 20,
                "viewbox": f"{w},{n},{e},{s}", "bounded": 1},
        headers=HEADERS, timeout=20,
    )
    r.raise_for_status()
    seen, cands = set(), []
    for it in r.json():
        name = it.get("name") or it["display_name"].split(",")[0]
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        plat, plon = float(it["lat"]), float(it["lon"])
        cands.append({
            "name": name, "lat": plat, "lon": plon,
            "osm": f'{it.get("osm_type")}/{it.get("osm_id")}',
            "dist_from_center_km": round(haversine_m(lat, lon, plat, plon) / 1000, 2),
            "source": "nominatim",
        })
    cands.sort(key=lambda c: c["dist_from_center_km"])
    return cands[:limit]


def get_candidates(lat, lon, activity, radius_m=3000, limit=8):
    tags = ACTIVITY_TAGS.get(activity)
    if not tags:
        raise ValueError(f"Unsupported activity: {activity}")
    s, w, n, e = bbox_from_radius(lat, lon, radius_m)
    parts = [f'nwr["{k}"="{v}"]["name"]({s:.5f},{w:.5f},{n:.5f},{e:.5f});' for k, v in tags]
    query = "[out:json][timeout:25];(" + "".join(parts) + ");out center tags;"

    try:
        data = run_overpass(query)
    except RuntimeError as err:
        print("Overpass unavailable, falling back to Nominatim")
        time.sleep(1)
        return _nominatim_candidates(lat, lon, activity, radius_m, limit)

    seen, cands = set(), []
    for el in data.get("elements", []):
        name = el.get("tags", {}).get("name")
        plat, plon = el_point(el)
        key = re.sub(r"[^a-z0-9]", "", name.lower())
        key = re.sub(r"s$", "", key)
        if not name or plat is None or any(
                key == k or (min(len(key), len(k)) >= 8 and (key.startswith(k) or k.startswith(key)))
                for k in seen):
            continue
        seen.add(key)
        cands.append({
            "name": name, "lat": plat, "lon": plon,
            "osm": f'{el["type"]}/{el["id"]}',
            "dist_from_center_km": round(haversine_m(lat, lon, plat, plon) / 1000, 2),
            "source": "overpass",
        })
    cands.sort(key=lambda c: c["dist_from_center_km"])
    return cands[:limit]
# ---------- geospatial context around each candidate ----------
def get_context(cands, ctx_radius=1500):
    if not cands:
        return cands
    road_parts, other_parts = [], []
    for c in cands:
        a = f"(around:{ctx_radius},{c['lat']},{c['lon']})"
        road_parts.append(f'way["highway"~"^(motorway|trunk|primary)$"]{a};')
        other_parts += [
            f'nwr["landuse"="industrial"]{a};',
            f'nwr["natural"="water"]{a};',
            f'way["waterway"~"^(river|canal)$"]{a};',
            f'nwr["leisure"~"^(park|garden)$"]{a};',
            f'nwr["natural"="wood"]{a};',
            f'nwr["landuse"="forest"]{a};',
        ]
    query = (
        "[out:json][timeout:40];"
        "(" + "".join(road_parts) + ")->.roads;"
        "(" + "".join(other_parts) + ")->.others;"
        ".roads out geom tags;"
        ".others out center tags;"
    )
    try:
        data = run_overpass(query)
    except RuntimeError:
        for c in cands:
            c["context"] = {"major_road": None, "industry": None, "water": None,
                            "green_patches_within_1km": 0, "unavailable": True}
        return cands

    roads, industry, water, green = [], [], [], []
    for el in data.get("elements", []):
        t = el.get("tags", {})
        if "highway" in t and "geometry" in el:
            pts = [(g["lat"], g["lon"]) for g in el["geometry"]]
            roads.append({"name": t.get("name") or t.get("ref") or t["highway"],
                          "type": t["highway"], "pts": pts})
            continue
        plat, plon = el_point(el)
        if plat is None:
            continue
        item = {"name": t.get("name", ""), "lat": plat, "lon": plon}
        if t.get("landuse") == "industrial":
            industry.append(item)
        elif t.get("natural") == "water" or "waterway" in t:
            water.append(item)
        elif t.get("leisure") in ("park", "garden") or t.get("natural") == "wood" or t.get("landuse") == "forest":
            green.append(item)

    def nearest_point(c, items):
        best = None
        for it in items:
            d = haversine_m(c["lat"], c["lon"], it["lat"], it["lon"])
            if best is None or d < best["dist_m"]:
                best = {"name": it["name"], "dist_m": round(d),
                        "bearing_to": round(bearing_deg(c["lat"], c["lon"], it["lat"], it["lon"]))}
        return best

    def nearest_road(c):
        best = None
        for r in roads:
            for (la, lo) in r["pts"]:
                d = haversine_m(c["lat"], c["lon"], la, lo)
                if best is None or d < best["dist_m"]:
                    best = {"name": r["name"], "type": r["type"], "dist_m": round(d),
                            "bearing_to": round(bearing_deg(c["lat"], c["lon"], la, lo))}
        return best

    for c in cands:
        near_green = [g for g in green
                      if haversine_m(c["lat"], c["lon"], g["lat"], g["lon"]) <= 1000
                      and g["name"] != c["name"]]
        c["context"] = {
            "major_road": nearest_road(c),
            "industry": nearest_point(c, industry),
            "water": nearest_point(c, water),
            "green_patches_within_1km": len(near_green),
        }
    return cands


if __name__ == "__main__":
    from data import geocode

    place, activity = "Koregaon Park, Pune", "running"
    lat, lon, name = geocode(place)
    print(f"{activity} near {name}\n")
    cands = get_candidates(lat, lon, activity, radius_m=3000, limit=5)
    if not cands:
        raise SystemExit("No venues found - try a larger radius_m or another activity")
    cands = get_context(cands)
    for c in cands:
        print(f"* {c['name']}  ({c['dist_from_center_km']} km from centre)")
        ctx = c["context"]
        for k in ("major_road", "industry", "water"):
            v = ctx[k]
            print(f"    {k:<11}: {v if v else 'none within 1.5 km'}")
        print(f"    green patches within 1 km: {ctx['green_patches_within_1km']}")
    print("\nMap data © OpenStreetMap contributors")