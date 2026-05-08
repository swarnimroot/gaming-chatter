import logging

from sqlalchemy import text
from sqlmodel import SQLModel

from app.db import models  # noqa: F401 — register tables with metadata
from app.db.session import engine
from app.utils.yaml_loader import seed_sources

log = logging.getLogger(__name__)


def _migrate_enrichments_columns() -> None:
    """Idempotent ALTER for columns added after Phase 1.

    SQLModel.create_all only creates missing tables, not missing columns.
    Phase 2 added status/error to enrichments; older DBs need them backfilled.
    """
    with engine.begin() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(enrichments)"))}
        if "status" not in cols:
            conn.execute(text("ALTER TABLE enrichments ADD COLUMN status TEXT NOT NULL DEFAULT 'ok'"))
            log.info("migrated enrichments: added status column")
        if "error" not in cols:
            conn.execute(text("ALTER TABLE enrichments ADD COLUMN error TEXT"))
            log.info("migrated enrichments: added error column")


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    _migrate_enrichments_columns()
    inserted = seed_sources()
    log.info("db ready (seeded %d new sources)", inserted)
