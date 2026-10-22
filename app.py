import threading
import time

from fastapi import FastAPI, Query
from pydantic import BaseModel

import assistant
from llm import get_llm

app = FastAPI(
    title="GeoAI Outdoor Activity Assistant",
    description="Where and when to head outdoors: live weather, air quality and OpenStreetMap context, "
                "with a small open language model (Qwen2.5-1.5B-Instruct, Q4 GGUF).",
    version="0.1",
)

_lock = threading.Lock()   # the local model handles one request at a time
_ready = False


class Ask(BaseModel):
    question: str


@app.on_event("startup")
def warm_up():
    global _ready
    get_llm()          # load the model once, so users never wait for it
    _ready = True


def _answer(question: str):
    question = (question or "").strip()
    if len(question) < 3:
        return {"question": question, "needs_input": True,
                "answer": "Please ask a question, for example: 'Where can I run tomorrow evening near Koregaon Park?'",
                "sources": assistant.SOURCES}
    if len(question) > 500:
        question = question[:500]
    t0 = time.time()
    with _lock:
        try:
            return assistant.run(question)
        except Exception as e:
            return {"question": question, "needs_input": False,
                    "answer": "Sorry, something went wrong while preparing your answer. Please try again.",
                    "error": type(e).__name__, "seconds": round(time.time() - t0, 1),
                    "sources": assistant.SOURCES}


@app.post("/ask")
def ask_post(body: Ask):
    return _answer(body.question)


@app.get("/ask")
def ask_get(q: str = Query(..., description="Your question")):
    return _answer(q)


@app.get("/health")
def health():
    return {"status": "ok" if _ready else "loading", "model": "Qwen2.5-1.5B-Instruct (Q4_K_M GGUF)"}


@app.get("/")
def root():
    return {
        "name": "GeoAI Outdoor Activity Assistant",
        "usage": "POST /ask with {\"question\": \"...\"}  or  GET /ask?q=...",
        "docs": "/docs",
        "attribution": "Map data © OpenStreetMap contributors; weather and air quality by Open-Meteo",
    }   