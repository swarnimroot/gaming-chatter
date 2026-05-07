from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "gaming_chatter.db"
DB_URL = f"sqlite:///{DB_PATH}"
SOURCES_YAML = ROOT / "sources.yaml"
TEMPLATES_DIR = ROOT / "app" / "templates"
STATIC_DIR = ROOT / "app" / "static"
