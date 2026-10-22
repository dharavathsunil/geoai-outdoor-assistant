import json
import re

from llm import get_llm

PROFILE_TXT = {"asthma": "someone with asthma", "senior": "seniors",
               "child": "children", "pregnancy": "pregnancy"}

NARR_SYSTEM = """You are an outdoor-activity advisor in India. You receive FACTS as JSON, fetched live moments ago.
Write ONE short paragraph of 2 to 3 sentences in plain, friendly English, in your own words.
Rules:
- Name the place, the day and the time window, copying times in 24-hour form like "16:00 to 17:00".
- Use only numbers that appear in FACTS. Never add distances, dates or other numbers.
- If safe_window_found is true, the answer is positive: say it is a good time to go. Never say "not recommended". Mention at most one caution, softened, as something to keep in mind.
- If safe_window_found is false, begin with "Not recommended", give the main reason, and say this is only the least bad option.
- If profile is given (for example asthma), mention it once.
- Do not copy the cautions word for word. Comment only on things listed in positives, cautions or conditions, and never call wind, UV or rain "moderate", "strong" or "high" unless a caution says so. No lists, no headings, no advice about what to carry.
Example of the style (do not reuse its words):
FACTS: {"activity":"running","place":"Lake Park","day":"Friday","time":"06:00 to 07:00","rating":"Good","safe_window_found":true,"positives":["comfortable temperature"],"cautions":["AQI 105 is above the comfortable limit (100)"]}
ANSWER: Lake Park is a good choice for a run on Friday between 06:00 and 07:00, when the temperature is comfortable. Air quality is a little above ideal (AQI 105), so keep the pace easy."""


def _numbers(text):
    return {round(float(x), 1) for x in re.findall(r"\d+(?:\.\d+)?", text)}


def narrative_facts(f):
    r = f["recommendation"]
    d = dict(activity=f["activity"], place=r["place"], day=r["day_name"], time=r["time_range"],
             rating=r["rating"], safe_window_found=r["safe_window_found"],
             positives=r["positives"][:2], cautions=r["cautions"][:2],
             conditions=f["conditions_in_window"])
    if f["profile"] != "none":
        d["profile"] = f["profile"]
    return d


def verify(text, nf):
    allowed = _numbers(json.dumps(nf, ensure_ascii=False))
    allowed |= {n - 12 for n in list(allowed) if 13 <= n <= 23}
    allowed |= {1.0, 2.0, 3.0}
    bad = sorted(n for n in _numbers(text) if n not in allowed)
    low = text.lower()
    if bad:
        return False, f"numbers not in facts: {bad}"
    if nf["place"].lower() not in low:
        return False, "place not mentioned"
    if re.search(r"\b(am|pm)\b", low):
        return False, "12-hour time used"
    if not nf["safe_window_found"] and "not recommended" not in low[:140]:
        return False, "did not say not recommended"
    if nf["safe_window_found"] and ("not recommended" in low or "least bad" in low):
        return False, "contradicts a safe window"
    if not 60 <= len(text) <= 650:
        return False, "bad length"
    return True, ""


def llm_narrative(nf):
    out = get_llm().create_chat_completion(
        messages=[{"role": "system", "content": NARR_SYSTEM},
                  {"role": "user", "content": "FACTS:\n" + json.dumps(nf, ensure_ascii=False)
                   + "\n\nWrite the paragraph now."}],
        temperature=0.2, max_tokens=130)
    return " ".join(out["choices"][0]["message"]["content"].split())


def _who(f):
    return f" for {PROFILE_TXT[f['profile']]}" if f["profile"] in PROFILE_TXT else ""


def template_narrative(f):
    r = f["recommendation"]
    if r["safe_window_found"]:
        s = (f"{r['place']} looks best for {f['activity']}{_who(f)} on {r['day_name']}, "
             f"{r['time_range']} ({r['rating'].lower()}).")
    else:
        s = (f"Not recommended{_who(f)}: conditions are poor for {f['activity']} {f['when_asked']}. "
             f"The least bad option is {r['place']} on {r['day_name']}, {r['time_range']}.")
    if r["cautions"]:
        s += f" Main caution: {r['cautions'][0]}."
    elif r["positives"]:
        s += f" {r['positives'][0][0].upper() + r['positives'][0][1:]}."
    return s


def render(f, narrative):
    r, c = f["recommendation"], f["conditions_in_window"]
    if r["safe_window_found"]:
        head = f"**Recommendation:** {r['place']}, {r['window']} ({r['rating']}, {r['score']}/100){_who(f)}."
    else:
        head = f"**Recommendation:** Not recommended{_who(f)}. Least bad option: {r['place']}, {r['window']}."

    area = f.get("resolved_area") or f["area"]
    parts = [head, f"*Area searched: {area}, within {f['search_radius_km']:g} km.*"]
    if f.get("place_note"):
        parts.append(f"*{f['place_note']}*")
    parts.append(narrative)

    bits = []
    if "feels_like_min_c" in c:
        lo, hi = c["feels_like_min_c"], c["feels_like_max_c"]
        bits.append(f"feels like {lo}°C" if lo == hi else f"feels like {lo} to {hi}°C")
    if "aqi_max" in c:
        lo, hi = c["aqi_min"], c["aqi_max"]
        bits.append(f"AQI {lo}" if lo == hi else f"AQI {lo} to {hi}")
    if "wind_kmh" in c:
        bits.append(f"wind {c['wind_kmh']} km/h from the {c['wind_from']}")
    if "rain_chance_pct" in c:
        bits.append(f"rain chance {c['rain_chance_pct']}%")
    if "uv_index" in c:
        bits.append(f"UV {c['uv_index']}")
    if bits:
        parts.append("**Conditions in that window:** " + ", ".join(bits)
                     + f". Sunrise {f['sunrise']}, sunset {f['sunset']}.")

    days = [d for d in f.get("per_day", []) if d.get("window")]
    if len(days) > 1:
        parts.append("**Day by day:** " + "; ".join(
            f"{d['day']}: {d['best_place']} ({d['rating']}, {d['window']})" for d in days) + ".")

    why = [f"- {p}" for p in r["positives"][:2]] + [f"- {x}" for x in r["cautions"][:3]]
    if why:
        parts.append("**Why:**\n" + "\n".join(why))
    parts.append("**What to carry:** " + "; ".join(f["things_to_carry"][:6]) + ".")
    if f["avoid_times_for_best_place"]:
        parts.append("**Avoid going at:** " + ", ".join(f["avoid_times_for_best_place"][:4]) + ".")
    if f["other_options"]:
        parts.append("**Other options:** " + "; ".join(
            f"{o['place']} ({o['rating']}, {o['window']})" for o in f["other_options"]) + ".")
    return "\n\n".join(parts)


def write_answer(facts):
    nf = narrative_facts(facts)
    mode, note, raw = "template", "", ""
    try:
        raw = llm_narrative(nf)
        ok, why = verify(raw, nf)
        if ok:
            narrative, mode = raw, "slm"
        else:
            narrative, note = template_narrative(facts), why
    except Exception as e:
        narrative, note = template_narrative(facts), f"model error: {type(e).__name__}"
    return dict(text=render(facts, narrative), mode=mode, note=note, raw=raw)