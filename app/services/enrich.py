"""Enrichment orchestration: scan items lacking enrichment, call Ollama, persist.

Two phases run separately so we don't swap models per-item:
  enrich_pending() → uses enrich model on all pending items
  embed_pending()  → uses embed model on all enriched items lacking embedding
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from sqlmodel import Session, col, select

from app.config import ENRICH_BODY_CHAR_MIN
from app.db.models import Enrichment, Item, RunLog, Source
from app.db.session import engine
from app.services.ollama import (
    EnrichmentData,
    embed_text,
    enrich_item,
    extract_video_id,
    fetch_youtube_transcript,
)

log = logging.getLogger(__name__)


def _body_for_enrichment(session: Session, item: Item) -> tuple[str, str]:
    """Return (body_text, source_label) for the prompt.

    YouTube items: pull transcript on-demand. If unavailable, fall back to
    whatever body_text was captured at ingest (usually title/description).
    """
    source = session.get(Source, item.source_id)
    label = source.name if source else "unknown"
    if source and source.type == "youtube":
        vid = extract_video_id(item.url)
        if vid:
            transcript = fetch_youtube_transcript(vid)
            if transcript:
                return transcript, label
        log.info("youtube transcript empty for item=%s; falling back to title/body", item.id)
    return (item.body_text or ""), label


def _persist_ok(session: Session, item_id: int, data: EnrichmentData) -> None:
    existing = session.exec(
        select(Enrichment).where(Enrichment.item_id == item_id)
    ).first()
    payload = {
        "tldr": data.tldr,
        "entities": json.dumps(data.entities.model_dump(), ensure_ascii=False),
        "category": data.category,
        "sentiment_score": data.sentiment_score,
        "sentiment_summary": data.sentiment_summary,
        "status": "ok",
        "error": None,
    }
    if existing:
        for k, v in payload.items():
            setattr(existing, k, v)
        existing.created_at = datetime.utcnow()
        session.add(existing)
    else:
        session.add(Enrichment(item_id=item_id, **payload))


def _persist_failed(session: Session, item_id: int, error: str) -> None:
    err = error[:500]
    existing = session.exec(
        select(Enrichment).where(Enrichment.item_id == item_id)
    ).first()
    if existing:
        existing.status = "failed"
        existing.error = err
        existing.created_at = datetime.utcnow()
        session.add(existing)
    else:
        session.add(Enrichment(item_id=item_id, status="failed", error=err))


def _persist_skipped(session: Session, item_id: int, reason: str) -> None:
    existing = session.exec(
        select(Enrichment).where(Enrichment.item_id == item_id)
    ).first()
    if existing:
        existing.status = "skipped"
        existing.error = reason
        existing.created_at = datetime.utcnow()
        session.add(existing)
    else:
        session.add(Enrichment(item_id=item_id, status="skipped", error=reason))


def enrich_pending(limit: Optional[int] = None, retry_failed: bool = False) -> dict:
    """Enrich items lacking an Enrichment row (or retry failed ones).

    Items are processed newest-first. Returns counts dict.
    """
    started = datetime.utcnow()
    totals = {"attempted": 0, "ok": 0, "failed": 0, "skipped": 0}

    with Session(engine) as session:
        run = RunLog(job_type="enrich", status="running", started_at=started)
        session.add(run)
        session.commit()
        session.refresh(run)

        existing_pairs = session.exec(
            select(Enrichment.item_id, Enrichment.status)
        ).all()
        if retry_failed:
            skip_ids = {iid for iid, status in existing_pairs if status == "ok"}
        else:
            skip_ids = {iid for iid, _ in existing_pairs}

        items = session.exec(
            select(Item).order_by(Item.published_at.desc().nullslast())
        ).all()
        items = [it for it in items if it.id not in skip_ids]
        if limit:
            items = items[:limit]

        for item in items:
            totals["attempted"] += 1
            body, label = _body_for_enrichment(session, item)
            if len(body or "") < ENRICH_BODY_CHAR_MIN:
                _persist_skipped(session, item.id, f"body too short ({len(body or '')} chars)")
                totals["skipped"] += 1
                session.commit()
                continue
            try:
                data = enrich_item(item.title, body, label)
                _persist_ok(session, item.id, data)
                totals["ok"] += 1
            except Exception as e:  # noqa: BLE001
                msg = f"{type(e).__name__}: {e}"
                _persist_failed(session, item.id, msg)
                totals["failed"] += 1
                log.warning("enrich failed for item=%s: %s", item.id, msg)
            session.commit()

        run.status = "ok"
        run.items_processed = totals["ok"]
        run.completed_at = datetime.utcnow()
        if totals["failed"]:
            run.error = f"{totals['failed']} failed, {totals['skipped']} skipped"
        session.add(run)
        session.commit()

    log.info("enrich_pending done: %s", totals)
    return totals


def embed_pending(limit: Optional[int] = None) -> dict:
    """Compute embeddings for OK enrichments lacking an embedding.

    Embeds the tldr (focused) — that's what we'll cluster on later.
    """
    started = datetime.utcnow()
    totals = {"attempted": 0, "ok": 0, "failed": 0}

    with Session(engine) as session:
        run = RunLog(job_type="embed", status="running", started_at=started)
        session.add(run)
        session.commit()
        session.refresh(run)

        rows = session.exec(
            select(Enrichment).where(
                Enrichment.status == "ok",
                col(Enrichment.embedding).is_(None),
            )
        ).all()
        if limit:
            rows = rows[:limit]

        for enr in rows:
            totals["attempted"] += 1
            try:
                vec = embed_text(enr.tldr or "")
                enr.embedding = vec
                session.add(enr)
                totals["ok"] += 1
            except Exception as e:  # noqa: BLE001
                totals["failed"] += 1
                log.warning("embed failed for enrichment=%s: %s", enr.id, e)
            session.commit()

        run.status = "ok"
        run.items_processed = totals["ok"]
        run.completed_at = datetime.utcnow()
        if totals["failed"]:
            run.error = f"{totals['failed']} embeddings failed"
        session.add(run)
        session.commit()

    log.info("embed_pending done: %s", totals)
    return totals
