from huggingface_hub import HfApi, snapshot_download, hf_hub_download

REPO = "dharavathsunil/geoai-outdoor-slm"
api = HfApi()
api.create_repo(REPO, repo_type="model", exist_ok=True, private=False)

CARD = '''---
license: apache-2.0
base_model: Qwen/Qwen2.5-1.5B-Instruct
library_name: transformers
pipeline_tag: text-generation
language: [en]
tags: [geoai, outdoor-activity, weather, air-quality, openstreetmap, qwen2, gguf]
---

# geoai-outdoor-slm

The language model behind the **GeoAI Outdoor Activity Assistant** (GeoAI Hackathon @ CSRE, IIT Bombay).

## Base model and changes
- **Base model:** [Qwen/Qwen2.5-1.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct) (1.5B parameters, Apache-2.0).
- **Changes:** none. The weights in this repository are an unmodified copy of the base model, with no fine-tuning.
- `qwen2.5-1.5b-instruct-q4_k_m.gguf` is the official 4-bit quantisation from
  [Qwen/Qwen2.5-1.5B-Instruct-GGUF](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF). It is the file the live assistant runs on CPU with llama.cpp.

## How the model is used
The assistant answers "where and when should I go outdoors" questions. The model has two narrow jobs:
1. **Parsing** a free-form question into JSON (activity, place, radius, profile) with schema-constrained decoding.
   Dates and times are resolved by plain code, and the place is checked against the question text.
2. **Phrasing** a 2-3 sentence summary from facts that were fetched live (weather, air quality, OpenStreetMap context).
   Every number and place name in the output is verified against those facts. If a check fails, a template sentence replaces the model text.

All recommendations, rankings and numbers come from live data and rule-based scoring, not from the model's memory.

## Intended use and limitations
- Intended for outdoor-activity advice in India as part of the full pipeline. Not a general-purpose assistant.
- Not medical advice. Do not use it alone for health decisions.
- A 1.5B model can phrase things awkwardly. That is why facts and numbers are rendered by code.

## Load it
```python
from transformers import AutoModelForCausalLM, AutoTokenizer
tok = AutoTokenizer.from_pretrained("dharavathsunil/geoai-outdoor-slm")
model = AutoModelForCausalLM.from_pretrained("dharavathsunil/geoai-outdoor-slm")
```
```python
from huggingface_hub import hf_hub_download
from llama_cpp import Llama
path = hf_hub_download("dharavathsunil/geoai-outdoor-slm", "qwen2.5-1.5b-instruct-q4_k_m.gguf")
llm = Llama(model_path=path, n_ctx=4096)
```

## Data and credits
Map data © OpenStreetMap contributors (Overpass API, Nominatim). Weather and air quality: Open-Meteo.
Base model by the Qwen team, Alibaba Cloud (Apache-2.0). Code written with the help of an AI coding assistant (Claude), as disclosed in the project README.
'''

print("1/4 downloading base model files...")
base = snapshot_download("Qwen/Qwen2.5-1.5B-Instruct",
                         ignore_patterns=["README.md", ".gitattributes", "*.md"])
print("2/4 uploading base model (about 3 GB)...")
api.upload_folder(folder_path=base, repo_id=REPO, repo_type="model")

print("3/4 uploading GGUF...")
gguf = hf_hub_download("Qwen/Qwen2.5-1.5B-Instruct-GGUF", "qwen2.5-1.5b-instruct-q4_k_m.gguf")
api.upload_file(path_or_fileobj=gguf, path_in_repo="qwen2.5-1.5b-instruct-q4_k_m.gguf",
                repo_id=REPO, repo_type="model")

print("4/4 uploading model card...")
api.upload_file(path_or_fileobj=CARD.encode("utf-8"), path_in_repo="README.md",
                repo_id=REPO, repo_type="model")
print("Done: https://huggingface.co/" + REPO)