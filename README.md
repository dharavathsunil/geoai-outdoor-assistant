---
title: GeoAI Outdoor Assistant
emoji: 🌤️
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
license: apache-2.0
---

# GeoAI Outdoor Activity Assistant

Recommends where and when to head outdoors, using live weather, air quality and OpenStreetMap
context with a small open language model (Qwen2.5-1.5B-Instruct, 4-bit GGUF).

API: `POST /ask` with `{"question": "..."}`. Docs at `/docs`.

Map data © OpenStreetMap contributors. Weather and air quality: Open-Meteo.