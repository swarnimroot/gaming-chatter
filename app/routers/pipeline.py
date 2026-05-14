"""POST /pipeline/run-full — manual one-button pipeline trigger.

Runs the full chain in a background thread: ingest → enrich → embed →
cluster(current week + previous week to catch cross-week items) →
synthesize(current week).

A module-level `threading.Lock` prevents concurrent runs; a busy click
returns 409 so the user doesn't double-trigger.

Estimated cost ~$0.50-$0.70 per run (Haiku per-item + Sonnet labels + Opus
synthesis); runtime ~4-5 min depending on new-item volume.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import HTMLResponse
from sqlmodel import Session

from app.db.session import engine

router = APIRouter()
log = logging.getLogger(__name__)

_PIPELINE_LOCK = threading.Lock()


def _current_iso_week_id() -> str:
    iso = datetime.utcnow().isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _previous_iso_week_id() -> str:
    iso = (datetime.utcnow() - timedelta(days=7)).isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _pipeline_worker() -> None:
    """5-step pipeline: ingest → enrich → embed → cluster(prev+curr, incremental)
    → synth(curr, only if cluster changed).

    Phase 3c.11 — incremental clustering preserves existing cluster IDs so
    prior weeks' synthesis_json references stay valid. Synthesis is skipped
    when the current week's cluster set didn't materially change (no items
    appended to existing clusters, no new clusters created).

    Cluster runs for BOTH current and previous ISO weeks because newly-ingested
    items may have `published_at` falling in either window. Previous week is
    only appended to (no auto re-synth) — prior read-outs stay stable.
    """
    # Local imports — avoid loading heavy modules at app startup.
    from app.services.cluster import cluster_window_incremental
    from app.services.enrich import embed_pending, enrich_pending
    from app.services.ingest import ingest_all
    from app.services.synthesis import synthesize_week

    curr = _current_iso_week_id()
    prev = _previous_iso_week_id()
    log.info("=== pipeline run start (curr=%s, prev=%s) ===", curr, prev)
    try:
        log.info("[1/5] ingest_all…")
        r1 = ingest_all()
        log.info("ingest_all done: %s", r1)

        log.info("[2/5] enrich_pending…")
        r2 = enrich_pending()
        log.info("enrich_pending done: %s", r2)

        log.info("[3/5] embed_pending…")
        r3 = embed_pending()
        log.info("embed_pending done: %s", r3)

        # Cluster prev + curr incrementally. Compute week bounds for each so
        # only items in that week's [start, end) window are considered.
        from app.services.reports import iso_week_bounds
        prev_start, prev_end = iso_week_bounds(prev)
        curr_start, curr_end = iso_week_bounds(curr)

        log.info("[4/5] cluster_window_incremental prev=%s …", prev)
        r4a = cluster_window_incremental(start=prev_start, end=prev_end, week_id=prev)
        log.info("cluster_window_incremental prev done: %s", r4a)
        log.info("[4/5] cluster_window_incremental curr=%s …", curr)
        r4b = cluster_window_incremental(start=curr_start, end=curr_end, week_id=curr)
        log.info("cluster_window_incremental curr done: %s", r4b)

        # Skip synthesis if current week's cluster set didn't change.
        curr_changed = (r4b.get("items_appended_existing", 0) > 0
                        or r4b.get("clusters_new_created", 0) > 0)
        if not curr_changed:
            log.info("[5/5] synthesize_week SKIPPED — no cluster changes for %s", curr)
        else:
            log.info("[5/5] synthesize_week curr=%s …", curr)
            with Session(engine) as session:
                r5 = synthesize_week(session, curr, force=True)
            log.info("synthesize_week done: model=%s from_cache=%s",
                     r5.get("model"), r5.get("from_cache"))

        log.info("=== pipeline run done ===")
    except Exception:  # noqa: BLE001
        log.exception("pipeline run FAILED")


@router.post("/pipeline/run-full", response_class=HTMLResponse)
def pipeline_run(bg: BackgroundTasks):
    """Trigger the full pipeline as a background task.

    Returns a small HTML fragment that HTMX swaps over the button (hx-swap=outerHTML).
    """
    if not _PIPELINE_LOCK.acquire(blocking=False):
        return HTMLResponse(
            '<span class="gc-pipeline-status gc-pipeline-status--busy">'
            'Pipeline already running. Refresh in a few minutes.</span>',
            status_code=409,
        )

    def _worker_and_release():
        try:
            _pipeline_worker()
        finally:
            _PIPELINE_LOCK.release()

    bg.add_task(_worker_and_release)
    return HTMLResponse(
        '<span class="gc-pipeline-status">'
        'Running pipeline… refresh in ~5 min to see new data.</span>'
    )
