import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")  # populate os.environ from .env if present; real env vars win
DB_PATH = ROOT / "gaming_chatter.db"
DB_URL = f"sqlite:///{DB_PATH}"
SOURCES_YAML = ROOT / "sources.yaml"
TEMPLATES_DIR = ROOT / "app" / "templates"
STATIC_DIR = ROOT / "app" / "static"

# Ollama configuration. Override any of these via environment variables.
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_ENRICH_MODEL = os.environ.get("OLLAMA_ENRICH_MODEL", "qwen2.5:7b")
OLLAMA_EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")
OLLAMA_NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "8192"))
OLLAMA_KEEP_ALIVE = os.environ.get("OLLAMA_KEEP_ALIVE", "24h")
# Hard cap on body chars sent to enrich/embed (~6000 tokens). Anything longer is truncated.
ENRICH_BODY_CHAR_CAP = int(os.environ.get("ENRICH_BODY_CHAR_CAP", "24000"))
# Minimum body length to bother enriching. Below this we mark the row 'skipped'
# (typically Reddit link-only posts that point at articles we scrape elsewhere).
ENRICH_BODY_CHAR_MIN = int(os.environ.get("ENRICH_BODY_CHAR_MIN", "200"))

# Anthropic API configuration (per-item enrichment via Haiku 4.5; lock-override 2026-05-12).
# Key is read by the SDK from ANTHROPIC_API_KEY env var directly; we don't import it here.
ANTHROPIC_ENRICH_MODEL = os.environ.get("ANTHROPIC_ENRICH_MODEL", "claude-haiku-4-5")
ANTHROPIC_TIMEOUT = float(os.environ.get("ANTHROPIC_TIMEOUT", "120"))

# Clustering. Cosine similarity on normalized fp32 embeddings, connected-components.
# 0.85 picked after editorial review of the 908-item corpus on 2026-05-07 — see DECISIONS.md.
CLUSTER_THRESHOLD = float(os.environ.get("CLUSTER_THRESHOLD", "0.85"))
CLUSTER_MIN_SIZE = int(os.environ.get("CLUSTER_MIN_SIZE", "2"))
# Cap how many member items we feed into the label-generation prompt.
CLUSTER_LABEL_SAMPLE = int(os.environ.get("CLUSTER_LABEL_SAMPLE", "8"))
