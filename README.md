# GeoAI Outdoor Activity Assistant

GeoAI Hackathon @ CSRE, IIT Bombay. Solo submission by **Dharavath Sunil**, Department of Water Resources and Ocean Engineering, NITK Surathkal.

An assistant that tells you **where and when** to go for an outdoor activity, what to carry, what to watch for and when to avoid going. For every question it fetches live weather, air quality and OpenStreetMap context, scores several nearby places hour by hour for the specific person, and returns a recommendation backed by the data it used. The language model is a small open model, **Qwen2.5-1.5B-Instruct** (1.5B parameters).

## Live endpoint
| What | URL |
|---|---|
| Web page with map | https://<NGROK-DOMAIN>/ui |
| API docs (try it) | https://<NGROK-DOMAIN>/docs |
| Ask (GET) | https://<NGROK-DOMAIN>/ask?q=Where%20can%20I%20run%20tomorrow%20evening%20near%20Koregaon%20Park%3F |
| Ask (POST) | `POST https://<NGROK-DOMAIN>/ask` with `{"question": "..."}` |
| Health | https://<NGROK-DOMAIN>/health |

```bash
curl -X POST https://<NGROK-DOMAIN>/ask -H "Content-Type: application/json" \
  -d '{"question": "I have mild asthma, where is good for a morning walk near Powai in the next two days?"}'
```

Notes
- A reply takes about 10 to 25 seconds (live data fetching plus a CPU-run model).
- The endpoint is served from my laptop through a free ngrok tunnel. In a browser, ngrok may show a notice page once: click "Visit Site".
- Response fields: `answer` (text), `needs_input` (true when the assistant is asking you a question), `facts` (the exact data the answer is built from), `map` (ranked places with coordinates), `parsed`, `timings`, `sources`.

## How it works
1. **Understand the question.** The small model extracts activity, place, radius and personal profile as JSON using schema-constrained decoding. Dates and times are resolved by code from the question text. A place the model invents is rejected if it does not appear in the question. Missing place, unsupported activity, unknown place, a place outside India, or a date more than a week ahead gets a clarifying reply, not a guess.
2. **Fetch live data.** Geocoding, candidate venues from OpenStreetMap, hourly weather and air quality, sunrise and sunset. Nothing is supplied in advance.
3. **Geospatial context** for each venue: nearest major road (motorway, trunk, primary), industrial area, water body and green cover within 1 km. The compass bearing from the venue to each source is compared with the hourly wind direction to flag "downwind" hours, and peak traffic hours (07-10 and 17-20) are penalised more.
4. **Score place x hour** with rule-based limits per activity (heat, rain, wind, UV, air quality, daylight or golden hour). Personal profiles (asthma, senior, child, pregnancy) tighten the limits. The best window per place and the hours to avoid are computed, and poor scores are reported as "Not recommended", never as a recommendation.
5. **Write the answer.** Every number, place and time in the answer is rendered by code from the fetched facts. The small model only writes a 2 to 3 sentence summary from a minimal fact set, and that text is verified: numbers must exist in the facts, the recommended place must be named, and it must not contradict the rating. If the check fails, a template sentence is used instead.

So the answer never comes from the model's memory: the model cannot add weather, numbers or places that were not fetched.

## Supported activities (11)
Running or jogging, walking or nature walk, cycling, golf, cricket, football or five-a-side, tennis, hiking, picnic or park outing, outdoor events and gatherings (wedding, party, fair), and outdoor photography (golden-hour aware).

## Model
- **Base model:** [Qwen/Qwen2.5-1.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct), Apache-2.0, 1.5B parameters.
- **Fine-tuning:** none. The assistant relies on live data and rules, and the model is used for parsing and phrasing only.
- **Hugging Face repo:** https://huggingface.co/dharavathsunil/geoai-outdoor-slm (weights, the 4-bit GGUF used at runtime, model card, Apache-2.0).
- **Runtime:** the Q4_K_M GGUF file from that repo, run on CPU with llama-cpp-python.

## Data sources (all free and open, fetched live)
| Source | Used for |
|---|---|
| OpenStreetMap via the Overpass API | venues, roads, industrial areas, water, parks |
| Nominatim (OpenStreetMap) | geocoding place names |
| Photon (komoot, OpenStreetMap data) and Open-Meteo Geocoding | geocoding fallbacks when Nominatim is unavailable |
| Open-Meteo Forecast API | hourly temperature, feels-like, rain, wind, UV, sunrise and sunset |
| Open-Meteo Air Quality API | hourly US AQI, PM2.5, PM10 |
| OpenStreetMap tiles and Leaflet | map in the web page |

Map data (c) OpenStreetMap contributors. Responses to Overpass and geocoding are cached on disk to respect rate limits; weather and air quality are never cached.

## Run it yourself
Requires Python 3.11.
```bash
git clone https://github.com/<github-username>/geoai-outdoor-assistant.git
cd geoai-outdoor-assistant
python -m venv .venv
.venv\Scripts\activate            # Windows (use source .venv/bin/activate on Linux or macOS)
pip install -r requirements.txt
pip install llama-cpp-python --only-binary llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
uvicorn app:app --host 127.0.0.1 --port 8000
```
The model file downloads from the Hugging Face repo above on first start. Then open http://127.0.0.1:8000/ui. A single question can also be run with `python assistant.py "your question"`.

## Project structure
| File | Role |
|---|---|
| `app.py` | FastAPI endpoints (`/ask`, `/ui`, `/health`) |
| `assistant.py` | the pipeline from question to answer |
| `parser.py` | question parsing (model + rules + validation) |
| `data.py` | geocoding, weather, air quality |
| `places.py` | venues and geospatial context from OpenStreetMap |
| `scoring.py` | activity and profile rules, place x hour scoring |
| `writer.py` | answer rendering, model summary and verification |
| `llm.py` | loads the GGUF model |
| `ui.html` | web page with map |
| `upload_model.py` | script that created the Hugging Face model repo |

## Limitations
- Weather and air quality are one grid point per city, so places in the same city differ only by their surroundings. Air quality is modelled data, not ground sensors.
- Traffic is estimated from road type and peak hours, not live traffic, and travel time is not yet included.
- OpenStreetMap coverage varies by area, and a name can geocode to a neighbouring locality (the "Area searched" line shows what was used).
- A 1.5B model on CPU is slow and can phrase things awkwardly. This is why facts are rendered by code and the model text is verified.
- The endpoint runs on a laptop behind a free tunnel, so availability depends on that machine and its connection.
- Advice is general and is not medical advice.

## Disclosure
- Models: Qwen2.5-1.5B-Instruct (open weights) is the only language model in the running assistant.
- AI coding assistant: Claude (Anthropic) was used as a coding aid while building this project. No hosted large model is used anywhere in the running assistant.
- No answers are hard-coded, and nothing is answered from the model's memory instead of fetched data.

Licence: MIT (code). Model weights follow the Qwen Apache-2.0 licence.