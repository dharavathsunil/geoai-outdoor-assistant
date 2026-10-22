import time
import requests

URL = "http://127.0.0.1:8000/ask"
TESTS = [
    "Where can I run tomorrow evening near Koregaon Park?",
    "runing near puna tomorow morning",
    "Best time this weekend for a kids' cricket match within 15 km of Whitefield?",
    "I have mild asthma, where's good for a morning walk near Powai in the next two days?",
    "Is it okay to cycle to work at 8 AM?",
    "Planning an outdoor birthday party on Sunday afternoon in Pune, what should I keep in mind?",
    "Good place and time for golf on Saturday within 40 km of Andheri?",
    "Where can I take sunset photos this evening around Bandra?",
    "Is Saturday or Sunday better for a hike near Lonavala?",
    "When is it safe for my parents to walk outdoors tomorrow in Bengaluru?",
    "Outdoor tennis after work today near Hinjewadi, any good spots?",
    "I'm 7 months pregnant, can I walk in Indiranagar Bengaluru tomorrow morning?",
    "football with friends near Salt Lake Kolkata friday evening",
    "Where can I surf near Goa tomorrow?",
    "What is the capital of France?",
    "Run near Xyzzyville tomorrow morning",
    "Picnic near Mysuru next month",
    "Where can I run near Koregaon Park?",
    "cycling in London tomorrow",
]

lines = []
for q in TESTS:
    try:
        r = requests.get(URL, params={"q": q}, timeout=240).json()
        w = r.get("writer", {})
        text = r["answer"][:230].replace("\n", " ")
        line = (f"{q}\n   needs_input={r.get('needs_input')} | writer={w.get('mode', '-')} "
                f"{w.get('note', '')} | {r.get('seconds')} s\n   {text}")
    except Exception as e:
        line = f"{q}\n   FAILED: {type(e).__name__}: {e}"
    print(line + "\n")
    lines.append(line)

open("test_results.txt", "w", encoding="utf-8").write("\n\n".join(lines))