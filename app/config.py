import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
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
