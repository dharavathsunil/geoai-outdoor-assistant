import json
import time
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from zoneinfo import ZoneInfo

from data import geocode, get_weather, get_air_quality
from places import get_candidates, get_context
from scoring import ACTIVITIES, build_hours, rank_places
from parser import parse_query
from writer import write_answer

IST = ZoneInfo("Asia/Kolkata")
COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
           "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
SOURCES = ["OpenStreetMap via Overpass and Nominatim (© OpenStreetMap contributors)",
           "Open-Meteo weather and air-quality forecast APIs"]

ACT_TIPS = {
    "running": "comfortable running shoes",
    "walking": "comfortable walking shoes",
    "cycling": "a helmet and front and rear lights",
    "golf": "a cap, sunscreen and a towel",
    "cricket": "a cap and a spare water bottle for the team",
    "football": "shin guards and a spare water bottle",
    "tennis": "a cap and a towel",
    "hiking": "sturdy shoes, a snack, and tell someone your route",
    "picnic": "a mat, shade cover and a bag for waste",
    "event": "a shaded or covered backup area for guests",
    "photography": "a lens cloth and a tripod",
}


def compass(deg):
    return COMPASS[int((deg % 360) / 22.5 + 0.5) % 16]


def fmt_window(s, e):
    s, e = datetime.fromisoformat(s), datetime.fromisoformat(e)
    return f"{s.strftime('%a %d %b')}, {s.strftime('%H:%M')}-{e.strftime('%H:%M')}"


def compress(avoid):
    out, cur = [], None
    for s in avoid:
        day, hm = s.split()
        h = int(hm[:2])
        if cur and cur[0] == day and h == cur[2] + 1:
            cur[2] = h
        else:
            if cur:
                out.append(cur)
            cur = [day, h, h]
    if cur:
        out.append(cur)
    return [f"{d} {a:02d}:00-{b + 1:02d}:00" for d, a, b in out]


def window_conditions(rows, s, e):
    s, e = datetime.fromisoformat(s), datetime.fromisoformat(e)
    rs = [r for r in rows if s <= r["dt"] < e]
    if not rs:
        return {}, False
    fl = [r["feels"] for r in rs]
    aqs = [r["aqi"] for r in rs if r["aqi"] is not None]
    cond = {
        "feels_like_min_c": round(min(fl), 1),
        "feels_like_max_c": round(max(fl), 1),
        "rain_chance_pct": max(r["rain_p"] for r in rs),
        "wind_kmh": round(sum(r["wind"] for r in rs) / len(rs), 1),
        "wind_from": compass(rs[0]["wind_dir"]),
        "uv_index": round(max(r["uv"] for r in rs), 1),
    }
    if aqs:
        cond["aqi_min"], cond["aqi_max"] = min(aqs), max(aqs)
    return cond, any(not r["daylight"] for r in rs)


def prep_tips(act, prof, cond, dark, cons_text):
    t = ["water and your phone"]
    if cond.get("feels_like_max_c", 0) >= 28:
        t.append("light breathable clothing and a cap")
    if cond.get("uv_index", 0) >= 6:
        t.append("sunscreen and sunglasses")
    if cond.get("rain_chance_pct", 0) >= 30:
        t.append("a light rain jacket or umbrella")
    if cond.get("aqi_max", 0) > 100:
        t.append("a well-fitted N95 mask")
    if dark:
        t.append("a torch or phone light, reflective clothing, and stay on lit paths")
    if cond.get("wind_kmh", 0) >= 25:
        t.append("something to secure loose items")
    if "mosquito" in cons_text:
        t.append("mosquito repellent")
    if prof == "asthma":
        t.append("your reliever inhaler (stop if you feel wheezy or short of breath)")
    elif prof == "senior":
        t.append("a companion, and take regular rests")
    elif prof == "child":
        t.append("an adult supervising, with regular water and shade breaks")
    elif prof == "pregnancy":
        t.append("a companion, and rest often (stop if dizzy)")
    if act in ACT_TIPS:
        t.append(ACT_TIPS[act])
    return t[:8]


def run(question):
    t0 = time.time()
    timings, last = {}, [t0]

    def lap(name):
        now = time.time()
        timings[name] = round(now - last[0], 1)
        last[0] = now

    q = parse_query(question)
    lap("parse")
    out = {"question": question, "parsed": q, "sources": SOURCES, "timings": timings}

    def done(msg, needs_input=False):
        out.update(answer=msg, needs_input=needs_input, seconds=round(time.time() - t0, 1))
        return out

    if q["status"] != "ok":
        return done(q["clarify"], True)

    act, prof, when = q["activity"], q["profile"], q["when"]
    try:
        geo = geocode(q["place"])
    except Exception:
        return done("The map lookup service is busy right now. Please try again in a minute.")
    lap("geocode")
    if geo == "FOREIGN":
        return done("That looks like a place outside India, and I currently cover India only. "
                    "Could you give an Indian city or area?", True)
    if not geo:
        return done(f"I couldn't find '{q['place']}' on the map. Could you give a nearby landmark or the city name?", True)
    lat, lon, display = geo

    try:
        w, aq = get_weather(lat, lon, 7), get_air_quality(lat, lon, 5)
    except Exception:
        return done("The weather service is not responding right now. Please try again shortly.")
    lap("weather")
    rows = build_hours(w, aq)

    now = datetime.now(IST).replace(tzinfo=None, minute=0, second=0, microsecond=0)
    start = max(datetime.fromisoformat(when["start"]), now)
    end = datetime.fromisoformat(when["end"])
    if start > rows[-1]["dt"]:
        return done("I can only look about a week ahead. Could you pick a nearer day?", True)

    hr0 = when["hour_range"]
    remaining = [r for r in rows if start <= r["dt"] < end
                 and (not hr0 or hr0[0] <= r["dt"].hour < hr0[1])]
    if not remaining:
        return done(f"That time window has already passed (it is {datetime.now(IST):%H:%M} now). "
                    "Want me to check tomorrow instead?", True)

    try:
        cands, used_r = [], q["radius_km"]
        for r in (q["radius_km"], q["radius_km"] * 2, q["radius_km"] * 4):
            used_r = min(r, 40)
            cands = get_candidates(lat, lon, act, radius_m=int(used_r * 1000), limit=6)
            if cands or used_r >= 40:
                break
        lap("venues")
        if not cands:
            return done(f"I couldn't find named {act} spots within {used_r:g} km of {q['place']}. "
                        "Try a bigger radius or a nearby area.", True)
        cands = get_context(cands)
        lap("context")
    except Exception:
        return done("The map data service is busy right now. Please try again in a minute.")

    hr = when["hour_range"]
    if hr:
        rows_f = [r for r in rows if hr[0] <= r["dt"].hour < hr[1]]
        dur = max(1, min(ACTIVITIES[act]["dur"], hr[1] - hr[0]))
    else:
        rows_f, dur = rows, None

    days, d = [], start.replace(hour=0)
    while d < end and len(days) < 4:
        res = rank_places(cands, rows_f, act, prof, start=max(d, start),
                          end=min(d + timedelta(days=1), end), duration=dur)
        if res and res[0]["window_start"]:
            days.append((d, res))
        d += timedelta(days=1)
    if not days:
        return done(f"That time window has already passed (it is {datetime.now(IST):%H:%M} now) "
                    "or no forecast is available for it. Want me to check a later time or tomorrow?", True)

    best_day, results = max(days, key=lambda x: x[1][0]["score"])
    best = results[0]
    cond, dark = window_conditions(rows, best["window_start"], best["window_end"])
    sun_i = w["daily"]["time"].index(best["window_start"][:10])
    ws, we = datetime.fromisoformat(best["window_start"]), datetime.fromisoformat(best["window_end"])

    # when to avoid: whole day for the chosen place, daytime hours only
    best_cand = next(c for c in cands if c["name"] == best["place"])
    full = rank_places([best_cand], rows, act, prof, start=max(best_day, start),
                       end=min(best_day + timedelta(days=1), end), duration=1)
    avoid_all = full[0]["avoid_hours"] if full else best["avoid_hours"]
    avoid_all = [a for a in avoid_all if 5 <= int(a.split()[1][:2]) <= 21]
    lap("score")

    resolved = ", ".join(p.strip() for p in display.split(",")[:3] if p.strip())
    sim = SequenceMatcher(None, q["place"].split(",")[0].strip().lower(),
                          display.split(",")[0].strip().lower()).ratio()

    facts = {
        "activity": act,
        "profile": prof,
        "area": q["place"],
        "resolved_area": resolved,
        "place_note": "" if sim >= 0.7 else (
            f"I read '{q['place']}' as {resolved}. If that is not what you meant, "
            "please give a nearby landmark or the city name."),
        "search_radius_km": used_r,
        "when_asked": when["label"],
        "recommendation": dict(
            place=best["place"], window=fmt_window(best["window_start"], best["window_end"]),
            day_name=ws.strftime("%A"), time_range=f"{ws:%H:%M} to {we:%H:%M}",
            rating=best["rating"], score=best["score"], safe_window_found=best["safe_window_found"],
            distance_km=best["distance_km"], positives=best["pros"], cautions=best["cons"]),
        "conditions_in_window": cond,
        "sunrise": w["daily"]["sunrise"][sun_i][11:16],
        "sunset": w["daily"]["sunset"][sun_i][11:16],
        "avoid_times_for_best_place": compress(avoid_all)[:5],
        "things_to_carry": prep_tips(act, prof, cond, dark, " ".join(best["cons"])),
        "other_options": [dict(place=o["place"], rating=o["rating"], distance_km=o["distance_km"],
                               window=fmt_window(o["window_start"], o["window_end"]))
                          for o in results[1:3] if o["window_start"]],
    }
    if len(days) > 1:
        facts["per_day"] = [dict(day=dd.strftime("%A %d %b"), best_place=rs[0]["place"],
                                 window=fmt_window(rs[0]["window_start"], rs[0]["window_end"]),
                                 rating=rs[0]["rating"], score=rs[0]["score"]) for dd, rs in days]

    wr = write_answer(facts)
    lap("write")
    out.update(
        answer=wr["text"], writer=wr, facts=facts, needs_input=False,
        map=[dict(name=e["place"], lat=e["lat"], lon=e["lon"], rank=i + 1)
             for i, e in enumerate(results[:3])],
        seconds=round(time.time() - t0, 1))
    return out


if __name__ == "__main__":
    import sys
    qtext = " ".join(sys.argv[1:]) or "Where can I run tomorrow evening near Koregaon Park?"
    res = run(qtext)
    print("\n" + res["answer"])
    if "writer" in res:
        print(f"\n[writer: {res['writer']['mode']} {res['writer']['note']}]")
        if res["writer"]["mode"] == "template":
            print("   (model wrote:", res["writer"]["raw"], ")")
        with open("last_facts.json", "w", encoding="utf-8") as f:
            json.dump(res["facts"], f, indent=1, ensure_ascii=False)
    print(f"[total {res['seconds']} s | breakdown: {res['timings']}]")
    print("\nSources: " + " | ".join(SOURCES))