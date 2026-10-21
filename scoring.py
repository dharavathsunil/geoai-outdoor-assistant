from datetime import datetime, timedelta

from places import is_downwind
from zoneinfo import ZoneInfo
# ---------------- activity rules ----------------
# t_ideal / t_max are in apparent temperature (deg C); aqi = (soft, hard) US AQI limits
# road_w / ind_w = how much traffic / industry upwind matters; exert = exertion level
ACTIVITIES = {
    "walking":     dict(t_ideal=(16, 29), t_max=34, rain=30, wind=35, aqi=(100, 200), uv=8, day="prefer", dur=1, exert=0.6, road_w=0.9, ind_w=0.9),
    "running":     dict(t_ideal=(16, 27), t_max=33, rain=30, wind=30, aqi=(100, 200), uv=8,  day="prefer",  dur=1, exert=1.0, road_w=1.0, ind_w=1.0),
    "cycling":     dict(t_ideal=(16, 28), t_max=34, rain=30, wind=25, aqi=(100, 200), uv=8,  day="prefer",  dur=1, exert=1.0, road_w=0.8, ind_w=0.8),
    "golf":        dict(t_ideal=(18, 30), t_max=35, rain=25, wind=30, aqi=(150, 250), uv=9,  day="require", dur=3, exert=0.6, road_w=0.3, ind_w=0.4),
    "cricket":     dict(t_ideal=(18, 30), t_max=35, rain=20, wind=35, aqi=(125, 225), uv=9,  day="require", dur=2, exert=0.9, road_w=0.7, ind_w=0.7),
    "football":    dict(t_ideal=(16, 28), t_max=33, rain=25, wind=30, aqi=(100, 200), uv=8,  day="prefer",  dur=1, exert=1.1, road_w=0.8, ind_w=0.8),
    "tennis":      dict(t_ideal=(16, 28), t_max=33, rain=25, wind=20, aqi=(110, 200), uv=8,  day="prefer",  dur=1, exert=0.9, road_w=0.6, ind_w=0.6),
    "hiking":      dict(t_ideal=(14, 27), t_max=32, rain=25, wind=35, aqi=(125, 225), uv=8,  day="require", dur=3, exert=1.0, road_w=0.6, ind_w=0.6),
    "picnic":      dict(t_ideal=(18, 30), t_max=34, rain=20, wind=25, aqi=(150, 250), uv=8,  day="require", dur=2, exert=0.5, road_w=0.8, ind_w=0.8),
    "event":       dict(t_ideal=(18, 30), t_max=35, rain=15, wind=25, aqi=(150, 250), uv=8,  day="prefer",  dur=3, exert=0.5, road_w=0.6, ind_w=0.6),
    "photography": dict(t_ideal=(10, 34), t_max=38, rain=40, wind=40, aqi=(200, 300), uv=12, day="golden",  dur=1, exert=0.3, road_w=0.4, ind_w=0.4),
}

# ---------------- personal profiles (tighten limits) ----------------
# aqi = multiplier on AQI limits, heat = shift on temperature limits (deg C),
# uv = shift on UV limit, wind/rain = multipliers, src = multiplier on road/industry penalty
PROFILES = {
    "none":      dict(aqi=1.0,  heat=0,  uv=0,  wind=1.0, rain=1.0, src=1.0),
    "asthma":    dict(aqi=0.6,  heat=-2, uv=0,  wind=1.0, rain=1.0, src=1.6),
    "senior":    dict(aqi=0.75, heat=-4, uv=-1, wind=0.8, rain=0.8, src=1.2),
    "child":     dict(aqi=0.75, heat=-3, uv=-2, wind=0.9, rain=0.9, src=1.2),
    "pregnancy": dict(aqi=0.75, heat=-4, uv=-1, wind=1.0, rain=1.0, src=1.2),
}

ROAD_TYPE_W = {"motorway": 1.0, "trunk": 1.0, "primary": 0.7}
TRAFFIC_HOURS = {7, 8, 9, 10, 17, 18, 19, 20}


# ---------------- build hourly rows from API data ----------------
def build_hours(w, aq):
    h, a = w["hourly"], aq["hourly"]
    aq_idx = {t: i for i, t in enumerate(a["time"])}
    sun = {
        d: (datetime.fromisoformat(sr), datetime.fromisoformat(ss))
        for d, sr, ss in zip(w["daily"]["time"], w["daily"]["sunrise"], w["daily"]["sunset"])
    }
    rows = []
    for i, t in enumerate(h["time"]):
        dt = datetime.fromisoformat(t)
        sr, ss = sun[t[:10]]
        mid = dt + timedelta(minutes=30)
        j = aq_idx.get(t)
        rows.append(dict(
            dt=dt,
            temp=h["temperature_2m"][i],
            feels=h["apparent_temperature"][i],
            rain_p=h["precipitation_probability"][i] or 0,
            rain_mm=h["precipitation"][i] or 0,
            wind=h["wind_speed_10m"][i] or 0,
            wind_dir=h["wind_direction_10m"][i] or 0,
            uv=h["uv_index"][i] or 0,
            aqi=a["us_aqi"][j] if j is not None else None,
            pm25=a["pm2_5"][j] if j is not None else None,
            daylight=sr <= mid <= ss,
            golden=abs((mid - sr).total_seconds()) <= 3600 or abs((mid - ss).total_seconds()) <= 3600,
            after_sunset_min=(mid - ss).total_seconds() / 60,
        ))
    return rows


# ---------------- score one place at one hour ----------------
def score_hour(ctx, row, act, prof):
    score, pros, cons, avoid = 100.0, [], [], False
    lo, hi = act["t_ideal"]
    lo, hi = lo + prof["heat"], hi + prof["heat"]
    t_max = act["t_max"] + prof["heat"]
    f = row["feels"]

    # temperature
    if f > t_max:
        score -= 30 + (f - t_max) * 4
        avoid = True
        cons.append(f"too hot: feels like {f}°C (limit {t_max}°C for this profile)")
    elif f > hi:
        score -= (f - hi) * 3
        cons.append(f"warm: feels like {f}°C")
    elif f < lo:
        score -= (lo - f) * 2
        cons.append(f"cool: feels like {f}°C")
    else:
        pros.append(f"comfortable temperature (feels like {f}°C)")

    # rain
    rain_lim = act["rain"] * prof["rain"]
    if row["rain_mm"] >= 2.5:
        score -= 50
        avoid = True
        cons.append(f"rain expected ({row['rain_mm']} mm)")
    elif row["rain_mm"] >= 0.5:
        score -= 25
        cons.append(f"light rain possible ({row['rain_mm']} mm)")
    if row["rain_p"] > rain_lim:
        score -= (row["rain_p"] - rain_lim) * 0.8
        cons.append(f"{row['rain_p']}% rain chance")

    # wind
    wind_lim = act["wind"] * prof["wind"]
    if row["wind"] > wind_lim:
        score -= (row["wind"] - wind_lim) * 1.5
        cons.append(f"strong wind {row['wind']} km/h")

    # UV
    uv_lim = act["uv"] + prof["uv"]
    if row["uv"] > uv_lim:
        score -= (row["uv"] - uv_lim) * 5
        cons.append(f"high UV index {row['uv']}")

    # air quality
    
    if row["aqi"] is not None:
        soft, hard = act["aqi"][0] * prof["aqi"], act["aqi"][1] * prof["aqi"]
        sensitive = prof["aqi"] < 1.0
        if row["aqi"] >= hard:
            score -= 40
            avoid = True
            cons.append(f"AQI {row['aqi']} is above the safe limit ({round(hard)}) for this profile and activity")
        elif row["aqi"] > soft:
            score -= (row["aqi"] - soft) * 0.8 * max(act["exert"], 0.5)
            cons.append(f"AQI {row['aqi']} is above the comfortable limit ({round(soft)})")
            if sensitive and row["aqi"] > 100 and act["exert"] >= 0.8:
                avoid = True
                cons.append("AQI above 100 is unhealthy for sensitive groups during exertion")
        else:
            pros.append(f"AQI {row['aqi']} is acceptable")

    # daylight
    mode = act["day"]
    if mode == "golden":
        if row["golden"] and row["daylight"]:
            score += 10
            pros.append("golden-hour light")
        elif not row["daylight"] and -5 <= row["after_sunset_min"] <= 40:
            pros.append("blue-hour light just after sunset")
        elif not row["daylight"]:
            score -= 60
            avoid = True
            cons.append("it is dark")
    elif not row["daylight"]:
        if mode == "require":
            score -= 60
            avoid = True
            cons.append("it is dark")
        else:
            score -= 15
            cons.append("after dark: limited visibility")

    # surroundings (place-specific)
    src = prof["src"]
    road = ctx.get("major_road")
    if road and road["dist_m"] < 800:
        down = row["wind"] >= 3 and is_downwind(road["bearing_to"], row["wind_dir"])
        base = (800 - road["dist_m"]) / 800 * 18 * ROAD_TYPE_W.get(road["type"], 0.5) * act["road_w"] * src
        pen = base * (1.0 if down else 0.3) * (1.4 if row["dt"].hour in TRAFFIC_HOURS else 0.8)
        if pen >= 3:
            score -= pen
            cons.append(
                f"{road['name']} ({road['type']}) is {road['dist_m']} m away"
                + (", and you are downwind of it" if down else "")
                + (" at peak traffic hours" if row["dt"].hour in TRAFFIC_HOURS else "")
            )

    ind = ctx.get("industry")
    if ind and ind["dist_m"] < 1500:
        down = row["wind"] >= 3 and is_downwind(ind["bearing_to"], row["wind_dir"])
        base = (1500 - ind["dist_m"]) / 1500 * 20 * act["ind_w"] * src
        pen = base * (1.0 if down else 0.2)
        if pen >= 3:
            score -= pen
            label = ind["name"] or "an industrial area"
            cons.append(f"{label} is {ind['dist_m']} m away" + (", and you are downwind of it" if down else ""))

    water = ctx.get("water")
    if water and water["dist_m"] < 800 and f > 29:
        score += 3
        pros.append(f"water body {water['dist_m']} m away helps with heat")
    if water and water["dist_m"] < 600 and row["dt"].hour in (5, 6, 17, 18, 19) and act["exert"] <= 0.6:
        score -= 3
        cons.append("mosquitoes likely near water at dusk/dawn")

    if ctx.get("green_patches_within_1km", 0) >= 4:
        score += 4
        pros.append(f"lots of green cover nearby ({ctx['green_patches_within_1km']} green areas within 1 km)")

    return max(0.0, min(100.0, score)), pros, cons, avoid


def label(score):
    return "Great" if score >= 80 else "Good" if score >= 60 else "Fair" if score >= 40 else "Poor"


def _uniq(seq, n=5):
    out = []
    for s in seq:
        if s not in out:
            out.append(s)
    return out[:n]


# ---------------- rank places x time windows ----------------
def rank_places(cands, rows, activity, profile="none", start=None, end=None, duration=None):
    act, prof = ACTIVITIES[activity], PROFILES[profile]
    dur = duration or act["dur"]
    now = datetime.now(ZoneInfo("Asia/Kolkata")).replace(tzinfo=None, minute=0, second=0, microsecond=0)
    start = start or now
    end = end or (start + timedelta(hours=36))
    window_rows = [r for r in rows if start <= r["dt"] < end]
    if not window_rows:
        return []

    results = []
    for c in cands:
        ctx = c.get("context", {})
        scored = []
        for r in window_rows:
            s, pros, cons, avoid = score_hour(ctx, r, act, prof)
            c["_dist_pen"] = min(c["dist_from_center_km"] * 2, 10)
            scored.append(dict(dt=r["dt"], score=max(0, s - c["_dist_pen"]), pros=pros, cons=cons, avoid=avoid))

        def best_window(allow_avoid):
            best = None
            for i in range(len(scored) - dur + 1):
                chunk = scored[i:i + dur]
                if chunk[-1]["dt"] - chunk[0]["dt"] != timedelta(hours=dur - 1):
                    continue
                if not allow_avoid and any(x["avoid"] for x in chunk):
                    continue
                s = sum(x["score"] for x in chunk) / dur
                if best is None or s > best[0]:
                    best = (s, chunk)
            return best

        best = best_window(False)
        fallback = best is None
        if fallback:
            best = best_window(True)

        avoid_hours = [x["dt"].strftime("%a %H:%M") for x in scored if x["avoid"]]
        entry = dict(place=c["name"], lat=c["lat"], lon=c["lon"],
                     distance_km=c["dist_from_center_km"], avoid_hours=avoid_hours)
        if best:
            s, chunk = best
            if fallback:
                s = min(s, 35)
            entry.update(
                score=round(s),
                rating="Not recommended" if fallback else label(s),
                safe_window_found=not fallback,
                window_start=chunk[0]["dt"].isoformat(),
                window_end=(chunk[-1]["dt"] + timedelta(hours=1)).isoformat(),
                pros=_uniq([p for x in chunk for p in x["pros"]]),
                cons=_uniq([p for x in chunk for p in x["cons"]]),
            )
        else:
            entry.update(score=0, rating="No data", safe_window_found=False,
                         window_start=None, window_end=None, pros=[], cons=[])
        results.append(entry)

    results.sort(key=lambda e: e["score"], reverse=True)
    return results


if __name__ == "__main__":
    from data import geocode, get_weather, get_air_quality
    from places import get_candidates, get_context

    activity = "running"
    lat, lon, name = geocode("Koregaon Park, Pune")
    cands = get_context(get_candidates(lat, lon, activity, radius_m=3000, limit=5))
    rows = build_hours(get_weather(lat, lon), get_air_quality(lat, lon))

    for profile in ("none", "asthma"):
        print(f"\n===== {activity} | profile: {profile} =====")
        for e in rank_places(cands, rows, activity, profile)[:3]:
            print(f"\n{e['place']}  [{e['rating']}, {e['score']}/100]  ({e['distance_km']} km)")
            if e["window_start"]:
                print(f"  best window: {e['window_start'][5:16]} to {e['window_end'][11:16]}")
            for p in e["pros"]:
                print(f"  + {p}")
            for c in e["cons"]:
                print(f"  - {c}")
            if e["avoid_hours"]:
                print(f"  avoid: {', '.join(e['avoid_hours'][:8])}{'...' if len(e['avoid_hours']) > 8 else ''}")
    print("\nMap data © OpenStreetMap contributors | Weather & AQ: Open-Meteo")