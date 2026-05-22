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
from app.services.anthropic import enrich_item, prescreen_yt_relevance
from app.services.ollama import (
    EnrichmentData,
    embed_text,
    extract_video_id,
    fetch_youtube_transcript,
)

log = logging.getLogger(__name__)


def _body_for_enrichment(session: Session, item: Item) -> tuple[str, str, Optional[str]]:
    """Return (body_text, source_label, prescreen_skip_reason).

    YouTube items: first run a Haiku pre-screen on title+description; if the
    video is judged non-gaming-relevant, return ("", label, reason) so the
    caller can persist `status='skipped'` without paying whisper-CPU cost.

    Otherwise pull transcript on-demand. If unavailable, fall back to whatever
    body_text was captured at ingest (usually title/description).

    The prescreen fails-open on API errors (returns relevant=True) so we don't
    lose items to transient Anthropic hiccups.
    """
    source = session.get(Source, item.source_id)
    label = source.name if source else "unknown"
    if source and source.type == "youtube":
        try:
            decision = prescreen_yt_relevance(item.title or "", item.body_text or "")
        except Exception as e:  # noqa: BLE001
            log.warning("yt prescreen failed for item=%s; proceeding as relevant: %s", item.id, e)
            decision = None
        if decision is not None and not decision.relevant:
            return "", label, f"yt prescreen: not gaming-related ({decision.reason})"

        vid = extract_video_id(item.url)
        if vid:
            transcript = fetch_youtube_transcript(vid)
            if transcript:
                return transcript, label, None
        log.info("youtube transcript empty for item=%s; falling back to title/body", item.id)
    return (item.body_text or ""), label, None


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
        "genres": json.dumps(data.genres) if data.genres else None,
        "platforms": json.dumps(data.platforms) if data.platforms else None,
        "event": data.event,
        "region_focus": ",".join(data.region_focus) if data.region_focus else None,
        "status": "ok",
        "error": None,
    }
    if existing:
        for k, v in payload.items():
            setattr(existing, k, v)
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


def enrich_pending(limit: Optional[int] = None, retry_failed: bool = False, force: bool = False) -> dict:
    """Enrich items lacking an Enrichment row (or retry failed ones).

    Items are processed newest-first. Returns counts dict.

    When force=True, processes ALL items (no skip-list), and preserves the
    existing 'ok' enrichment row if the re-enrich call fails instead of
    overwriting it with a failed row.
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
        ok_before = {iid for iid, status in existing_pairs if status == "ok"}
        if force:
            skip_ids: set[int] = set()
        elif retry_failed:
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
            body, label, prescreen_skip = _body_for_enrichment(session, item)
            if prescreen_skip:
                _persist_skipped(session, item.id, prescreen_skip)
                totals["skipped"] += 1
                session.commit()
                continue
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
                if force and item.id in ok_before:
                    totals["preserved"] = totals.get("preserved", 0) + 1
                    log.warning("re-enrich failed for item=%s; preserving existing ok row: %s", item.id, msg)
                else:
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
