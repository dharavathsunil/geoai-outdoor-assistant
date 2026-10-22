import os
from huggingface_hub import hf_hub_download
from llama_cpp import Llama

# The GGUF file is served from our own Hugging Face model repo
# (an unmodified copy of Qwen's official Q4_K_M quantisation of Qwen2.5-1.5B-Instruct).
REPO = "dharavathsunil/geoai-outdoor-slm"
FILE = "qwen2.5-1.5b-instruct-q4_k_m.gguf"

_llm = None


def get_llm():
    global _llm
    if _llm is None:
        try:
            path = hf_hub_download(REPO, FILE, local_files_only=True)
        except Exception:
            path = hf_hub_download(REPO, FILE)
        _llm = Llama(model_path=path, n_ctx=4096,
                     n_threads=min(8, os.cpu_count() or 4),
                     n_gpu_layers=0, verbose=False)
    return _llm