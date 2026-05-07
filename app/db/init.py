import logging

from sqlmodel import SQLModel

from app.db import models  # noqa: F401 — register tables with metadata
from app.db.session import engine
from app.utils.yaml_loader import seed_sources

log = logging.getLogger(__name__)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    inserted = seed_sources()
    log.info("db ready (seeded %d new sources)", inserted)
