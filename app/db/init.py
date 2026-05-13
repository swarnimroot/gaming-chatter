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
        if "genres" not in cols:
            conn.execute(text("ALTER TABLE enrichments ADD COLUMN genres TEXT"))
            log.info("migrated enrichments: added genres column")
        if "platforms" not in cols:
            conn.execute(text("ALTER TABLE enrichments ADD COLUMN platforms TEXT"))
            log.info("migrated enrichments: added platforms column")
        if "event" not in cols:
            conn.execute(text("ALTER TABLE enrichments ADD COLUMN event TEXT"))
            log.info("migrated enrichments: added event column")


def _migrate_games_columns() -> None:
    """Idempotent ALTER for columns added to games dim after Phase 3c.0.5.

    Phase 3c.1 adds release_date so the Releases card can render real dates.
    """
    with engine.begin() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(games)"))}
        if "release_date" not in cols:
            conn.execute(text("ALTER TABLE games ADD COLUMN release_date TEXT"))
            log.info("migrated games: added release_date column")


def _migrate_clusters_columns() -> None:
    """Idempotent ALTER for Phase 3b ranking columns.

    Existing rows get NULL until cluster_window re-runs for their week_id.
    """
    with engine.begin() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(clusters)"))}
        if "source_count" not in cols:
            conn.execute(text("ALTER TABLE clusters ADD COLUMN source_count INTEGER"))
            log.info("migrated clusters: added source_count column")
        if "latest_published_at" not in cols:
            conn.execute(text("ALTER TABLE clusters ADD COLUMN latest_published_at TIMESTAMP"))
            log.info("migrated clusters: added latest_published_at column")
        if "score" not in cols:
            conn.execute(text("ALTER TABLE clusters ADD COLUMN score REAL"))
            log.info("migrated clusters: added score column")


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    _migrate_enrichments_columns()
    _migrate_clusters_columns()
    _migrate_games_columns()
    inserted = seed_sources()
    log.info("db ready (seeded %d new sources)", inserted)
