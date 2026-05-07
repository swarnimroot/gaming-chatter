"""Ingest pipeline: scrapers-lib → raw_items + items, with dedup + run logging."""
from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
from datetime import datetime
from typing import Any

from sqlmodel import Session, select

from app.db.models import Item, RawItem, RunLog, Source
from app.db.session import engine
from app.services.scrapers import fetch_source

log = logging.getLogger(__name__)


def _slugify(name: str) -> str:
    s = "".join(c.lower() if c.isalnum() else "-" for c in name)
    return "-".join(p for p in s.split("-") if p) or "src"


def _fingerprint(title: str) -> str:
    return hashlib.md5(title.strip().lower().encode("utf-8")).hexdigest()


def _to_payload(mention: Any) -> str:
    """Serialize a RawMention to JSON. Falls back to str() for unknown types."""
    if dataclasses.is_dataclass(mention):
        d = dataclasses.asdict(mention)
    elif hasattr(mention, "__dict__"):
        d = dict(mention.__dict__)
    else:
        d = {"repr": repr(mention)}
    return json.dumps(d, default=str, ensure_ascii=False)


def ingest_source(session: Session, source: Source) -> dict:
    """Run a single source. Returns counts + any error message.

    On error: sets source.last_error / error_count and returns early.
    On success: clears error state, updates last_fetched_at.
    """
    started = datetime.utcnow()
    run = RunLog(job_type="ingest", source_id=source.id, status="running", started_at=started)
    session.add(run)
    session.commit()
    session.refresh(run)

    try:
        slug = _slugify(source.name)
        mentions = fetch_source(source.type, source.url_or_handle, slug)
    except Exception as e:  # noqa: BLE001 — we want to capture every failure mode
        msg = f"{type(e).__name__}: {e}"
        source.last_error = msg
        source.error_count = (source.error_count or 0) + 1
        run.status = "error"
        run.completed_at = datetime.utcnow()
        run.error = msg
        session.add(source)
        session.add(run)
        session.commit()
        log.warning("ingest %s failed: %s", source.name, msg)
        return {"fetched": 0, "new": 0, "skipped": 0, "error": msg}

    fetched = len(mentions)
    existing = set(
        session.exec(
            select(RawItem.external_id).where(RawItem.source_id == source.id)
        ).all()
    )

    new_count = 0
    skipped = 0
    for m in mentions:
        ext_id = getattr(m, "mention_id", None)
        if not ext_id:
            skipped += 1
            continue
        if ext_id in existing:
            skipped += 1
            continue

        title = (getattr(m, "source_title", None) or "(untitled)").strip() or "(untitled)"
        url = getattr(m, "source_url", None) or ""
        body = getattr(m, "raw_text", None)
        author = getattr(m, "author", None)
        published = getattr(m, "published_at", None)

        raw = RawItem(
            source_id=source.id,
            external_id=ext_id,
            raw_payload=_to_payload(m),
        )
        session.add(raw)
        session.flush()

        item = Item(
            source_id=source.id,
            raw_item_id=raw.id,
            title=title,
            url=url,
            body_text=body,
            author=author,
            published_at=published,
            fingerprint=_fingerprint(title),
        )
        session.add(item)
        existing.add(ext_id)
        new_count += 1

    source.last_fetched_at = started
    source.last_error = None
    source.error_count = 0
    run.status = "ok"
    run.items_processed = new_count
    run.completed_at = datetime.utcnow()
    session.add(source)
    session.add(run)
    session.commit()

    log.info("ingest %s: fetched=%d new=%d skipped=%d", source.name, fetched, new_count, skipped)
    return {"fetched": fetched, "new": new_count, "skipped": skipped, "error": None}


def ingest_all() -> dict:
    """Run every enabled source sequentially in a fresh session.

    Designed to be called from a BackgroundTask, so it owns its session.
    """
    totals = {"fetched": 0, "new": 0, "skipped": 0, "errors": 0}
    with Session(engine) as session:
        sources = session.exec(select(Source).where(Source.enabled == True)).all()  # noqa: E712
        for s in sources:
            r = ingest_source(session, s)
            totals["fetched"] += r["fetched"]
            totals["new"] += r["new"]
            totals["skipped"] += r["skipped"]
            if r["error"]:
                totals["errors"] += 1
    log.info(
        "ingest_all done: fetched=%d new=%d skipped=%d errors=%d",
        totals["fetched"], totals["new"], totals["skipped"], totals["errors"],
    )
    return totals
