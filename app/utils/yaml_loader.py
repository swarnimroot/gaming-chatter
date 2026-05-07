import yaml
from sqlmodel import Session, select

from app.config import SOURCES_YAML
from app.db.models import Source
from app.db.session import engine


def seed_sources() -> int:
    """Idempotent upsert of sources.yaml into the sources table.

    Returns the number of newly inserted rows.
    """
    if not SOURCES_YAML.exists():
        return 0

    with SOURCES_YAML.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    entries = data.get("sources", []) or []

    inserted = 0
    with Session(engine) as session:
        for e in entries:
            stype = e.get("type")
            handle = e.get("url") or e.get("handle")
            name = e.get("name")
            if not (name and stype and handle):
                continue

            existing = session.exec(
                select(Source).where(
                    Source.type == stype,
                    Source.url_or_handle == handle,
                )
            ).first()
            if existing:
                continue

            session.add(
                Source(
                    name=name,
                    type=stype,
                    url_or_handle=handle,
                    enabled=bool(e.get("enabled", True)),
                )
            )
            inserted += 1
        session.commit()
    return inserted
