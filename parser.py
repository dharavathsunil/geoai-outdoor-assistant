import json
import re
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from llm import get_llm

IST = ZoneInfo("Asia/Kolkata")
ACTIVITIES = ["running", "walking", "cycling", "golf", "cricket", "football",
              "tennis", "hiking", "picnic", "event", "photography"]
PROFILES = ["none", "asthma", "senior", "child", "pregnancy"]
TOD = {"morning": (5, 11), "afternoon": (12, 16), "evening": (16, 20),
       "night": (19, 23), "all_day": (5, 21)}

SCHEMA = {
    "type": "object",
    "properties": {
        "activity": {"type": "string", "enum": ACTIVITIES + ["other"]},
        "place": {"type": "string"},
        "radius_km": {"type": "number"},
        "day": {"type": "string"},
        "time_of_day": {"type": "string", "enum": ["", "morning", "afternoon", "evening", "night", "all_day"]},
        "hour": {"type": "integer"},
        "profile": {"type": "string", "enum": PROFILES},
    },
    "required": ["activity", "place", "radius_km", "day", "time_of_day", "hour", "profile"],
}

SYSTEM = """You extract fields from a user's question about an outdoor activity in India. Today is TODAY. Reply with JSON only.
Fields:
- activity: one of running, walking, cycling, golf, cricket, football, tennis, hiking, picnic, event (wedding, party, fair, gathering), photography. Use "other" if it is none of these.
- place: the city, area or landmark the user names. Empty string if none is named. Never guess one.
- radius_km: search radius in km if the user gives one, else 0.
- day: the day words as written (today, tomorrow, saturday, this weekend...), or empty string.
- time_of_day: morning, afternoon, evening, night, all_day, or empty string.
- hour: clock hour 0-23 if the user gives an exact time, else -1.
- profile: asthma, senior, child, pregnancy, or none. Use senior for elderly people or parents.
Examples:
Q: Any good place for a game of football on Friday evening near Salt Lake, Kolkata?
A: {"activity":"football","place":"Salt Lake, Kolkata","radius_km":0,"day":"friday","time_of_day":"evening","hour":-1,"profile":"none"}
Q: Is it safe for my grandmother to walk at 6 am?
A: {"activity":"walking","place":"","radius_km":0,"day":"","time_of_day":"morning","hour":6,"profile":"senior"}"""

ACTIVITY_REGEX = [
    ("hiking", r"\b(hike|hiking|trek|trekking|trail|nature walk)\b"),
    ("walking", r"\b(walk|walking|stroll)\b"),
    ("running", r"\b(run|running|jog|jogging)\b"),
    ("cycling", r"\b(cycl\w*|bike|biking|bicycle)\b"),
    ("golf", r"\bgolf\b"),
    ("cricket", r"\bcricket\b"),
    ("football", r"\b(football|soccer|five-a-side|5-a-side)\b"),
    ("tennis", r"\btennis\b"),
    ("picnic", r"\bpicnic\b"),
    ("photography", r"\b(photo\w*|sunset shots?)\b"),
    ("event", r"\b(wedding|party|birthday|fair|event|gathering|function)\b"),
]
PROFILE_REGEX = [
    ("asthma", r"\b(asthma\w*|copd|breathing (problem|issue)s?|wheez\w*)\b"),
    ("pregnancy", r"\b(pregnan\w*|expecting)\b"),
    ("child", r"\b(kid|kids|child|children|toddler|baby|school)\b"),
    ("senior", r"\b(senior|seniors|elderly|parents|grandparents?|grandmother|grandfather|old age)\b"),
]
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _model_json(question, now):
    llm = get_llm()
    sys_prompt = SYSTEM.replace("TODAY", now.strftime("%A, %d %B %Y"))
    out = llm.create_chat_completion(
        messages=[{"role": "system", "content": sys_prompt},
                  {"role": "user", "content": question}],
        response_format={"type": "json_object", "schema": SCHEMA},
        temperature=0.0, max_tokens=200,
    )
    try:
        return json.loads(out["choices"][0]["message"]["content"])
    except Exception:
        return {}


def resolve_when(question, now):
    text = question.lower()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    wd = today.weekday()
    d0 = d1 = today
    day_given = True

    found = []
    for i, name in enumerate(WEEKDAYS):
        if re.search(rf"\b({name}|{name[:3]})\b", text):
            off = (i - wd) % 7
            if off == 0 and re.search(r"\bnext\b", text):
                off = 7
            found.append(today + timedelta(days=off))

    if re.search(r"day after (tomorrow|tomorow|tommorow|tmrw)", text):
        d0 = d1 = today + timedelta(days=2)
    elif re.search(r"\b(tomorrow|tomorow|tommorow|tommorrow|tmrw|tmr)\b", text):
        d0 = d1 = today + timedelta(days=1)
    elif re.search(r"next (two|2) days", text):
        d0, d1 = today, today + timedelta(days=1)
    elif "weekend" in text:
        if wd == 6:
            d0 = d1 = today
        elif wd == 5:
            d0, d1 = today, today + timedelta(days=1)
        else:
            d0 = today + timedelta(days=5 - wd)
            d1 = d0 + timedelta(days=1)
    elif "next week" in text:
        d0 = today + timedelta(days=7 - wd)
        d1 = d0 + timedelta(days=6)
    elif found:
        d0, d1 = min(found), max(found)
    elif re.search(r"\b(today|tonight|this (morning|afternoon|evening))\b", text):
        pass
    else:
        day_given = False

    # exact hour, from the question text only
    m = re.search(r"\b(\d{1,2})(?::\d{2})?\s*(am|pm)\b", text)
    h = (int(m.group(1)) % 12 + (12 if m.group(2) == "pm" else 0)) if m else None

    # time of day, from the question text only
    tod = ""
    for key, pat in [("night", r"\b(tonight|night)\b"),
                     ("evening", r"\b(evening|sunset|after work)\b"),
                     ("morning", r"\b(morning|sunrise|dawn)\b"),
                     ("afternoon", r"\b(afternoon|noon|lunch)\b")]:
        if re.search(pat, text):
            tod = key
            break

    hour_range = (h, min(h + 2, 24)) if h is not None else (TOD[tod] if tod else None)

    if not day_given and hour_range is None:
        start, end, label = now, now + timedelta(hours=24), "the next 24 hours"
    else:
        start, end = d0, d1 + timedelta(days=1)
        label = d0.strftime("%A %d %b") if d0 == d1 else f"{d0.strftime('%a %d %b')} to {d1.strftime('%a %d %b')}"
        if not day_given:
            label = "today"
    return dict(start=start.isoformat(), end=end.isoformat(),
                hour_range=list(hour_range) if hour_range else None,
                label=label, past=end <= now)

GENERIC_PLACES = {"outdoors", "outdoor", "outside", "home", "work", "office", "nearby",
                  "near me", "here", "there", "me", "my area", "the area", "city", "town"}


def regex_place(question):
    m = re.search(
        r"\b(?i:near|in|around|at|of)\s+"
        r"((?:[A-Z][\w'.-]*)(?:\s+[A-Z][\w'.-]*)*"
        r"(?:,\s*[A-Z][\w'.-]*(?:\s+[A-Z][\w'.-]*)*)?)",
        question)
    return m.group(1).strip() if m else ""
def parse_query(question):
    now = datetime.now(IST).replace(tzinfo=None)
    q = question.lower()
    raw = _model_json(question, now)

    activity = raw.get("activity")
    if activity not in ACTIVITIES:
        activity = next((a for a, pat in ACTIVITY_REGEX if re.search(pat, q)), None)

    profile = raw.get("profile") if raw.get("profile") in PROFILES else "none"
    for p, pat in PROFILE_REGEX:
        if re.search(pat, q):
            profile = p
            break

    place = (raw.get("place") or "").strip()
    if place.lower() in GENERIC_PLACES or (
            place and not any(t in q for t in re.findall(r"\w+", place.lower()) if len(t) > 2)):
        place = ""                      # generic word or invented by the model: reject
    place = place or regex_place(question)

    radius = float(raw.get("radius_km") or 0)
    m = re.search(r"(\d+(?:\.\d+)?)\s*(km|kilomet)", q)
    if m:
        radius = float(m.group(1))
    radius = min(max(radius, 1.0), 40.0) if radius else 3.0

    when = resolve_when(question, now)
    if re.search(r"\bnext (month|year)\b|\bin (\d+|a|two|three|four) (weeks?|months?)\b", q):
        when["too_far"] = True
    status, clarify = "ok", None
    if activity is None:
        status = "unsupported"
        clarify = ("I can advise on running, walking, cycling, golf, cricket, football, tennis, hiking, "
                   "picnics, outdoor events and photography. Which of these are you planning?")
    elif not place:
        status = "need_place"
        clarify = "Which area or city should I look at? A neighbourhood or landmark name works best."
    elif when.get("too_far"):
        status = "need_time"
        clarify = "I can only forecast about a week ahead. Which day in the next few days should I check?"
    elif when["past"]:
        status = "need_time"
        clarify = "That time has already passed. Which upcoming day or time did you mean?"

    return dict(status=status, clarify=clarify, activity=activity, place=place,
                radius_km=radius, profile=profile, when=when)


if __name__ == "__main__":
    tests = [
        "Where can I run tomorrow evening near Koregaon Park?",
        "I have mild asthma, where's good for a morning walk near Powai in the next two days?",
        "Is it okay to cycle to work at 8 AM?",
        "Good place and time for golf on Saturday within 40 km of Andheri?",
        "Is Saturday or Sunday better for a hike near Lonavala?",
        "When is it safe for my parents to walk outdoors tomorrow in Bengaluru?",
        "Where can I play kabaddi tonight in Delhi?",
        "what's the weather like",
        "Planning an outdoor birthday party on Sunday afternoon in Pune, what should I keep in mind?",
        "Where can I take sunset photos this evening around Bandra?",
        "good tennis spots near hinjewadi after work today",
    ]
    for q in tests:
        t0 = time.time()
        r = parse_query(q)
        print(f"\nQ: {q}\n   ({time.time() - t0:.1f}s)")
        print("  ", json.dumps(r, ensure_ascii=False))
        