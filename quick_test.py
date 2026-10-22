import sys
import requests

for q in sys.argv[1:]:
       r = requests.get("http://127.0.0.1:8000/ask", params={"q": q}, timeout=240).json()
       print(q, "->", r.get("seconds"), "s\n", r["answer"][:700], "\n")