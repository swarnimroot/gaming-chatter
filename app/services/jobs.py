"""Phase 4 — orchestrator job functions wrapping the existing pipeline pieces.

These are the entry points scheduled by APScheduler (when SCHEDULER_ENABLED is
set) AND called directly by the manual-trigger endpoints in
`app/routers/runs.py`. They do NOT reimplement any business logic — they
sequence existing functions (`ingest.ingest_all`, `enrich.enrich_pending`,
`enrich.embed_pending`, `article_fetch.fetch_skipped_bodies`,
`cluster.cluster_window_incremental`, `synthesis.synthesize_week`,
`backfill_region.run`, `refresh_pcgamer_releases.run`,
`refresh_ign_releases.run`) and persist a JobRun row per invocation.

Each orchestrator writes ONE parent `JobRun` row with `status='running'` at
start, then updates the same row on completion with `status`, `finished_at`,
`duration_seconds`, `message`, and `details_json` (per-step counts).
Per-step granular logging continues to flow through the existing `RunLog`
table (one row per ingest source, per enrich batch, etc.) — JobRun is purely
the higher-level orchestrator log.

Threading model: orchestrators acquire a single global `threading.RLock` so a
manual trigger never races with the scheduler / startup catch-up firing the
same job. Callers that hit the lock are recorded as `status='skipped'`.
"""
from __future__ import annotations

import json
import logging
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from sqlmodel import Session, select

from app.db.models import Enrichment, JobRun, WeeklyReport
from app.db.session import engine
from app.services import cost

log = logging.getLogger(__name__)

# Single global lock — only one orchestrator job (across all kinds) runs at a
# time. Scheduled, startup-catchup, and manual triggers all compete for the
# same lock so the pipeline can't trample itself. RLock so a single thread can
# re-enter (a manual trigger calling a wrapper that calls into a sub-step that
# also locks).
_JOB_LOCK = threading.RLock()


# ---------------------------------------------------------------------------
# JobRun helpers
# ---------------------------------------------------------------------------

def _start_run(job_name: str, triggered_by: str) -> int:
    """Insert a new JobRun row with status='running'. Returns the row id."""
    with Session(engine) as session:
        run = JobRun(
            job_name=job_name,
            started_at=datetime.utcnow(),
            status="running",
            triggered_by=triggered_by,
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        cost.open_run(run.id)
        return run.id


def _finish_run(
    run_id: int,
    status: str,
    message: Optional[str] = None,
    details: Optional[dict] = None,
) -> None:
    """Patch the JobRun row in place with terminal status + details."""
    # Always close the cost frame for this run (even if the row vanished) so a
    # leaked frame can't bleed into the next run on this thread.
    totals = cost.close_run(run_id)
    with Session(engine) as session:
        run = session.get(JobRun, run_id)
        if run is None:
            log.warning("_finish_run: JobRun id=%s vanished mid-run", run_id)
            return
        run.input_tokens = totals["input_tokens"]
        run.output_tokens = totals["output_tokens"]
        run.cost_usd = totals["cost_usd"]
        now = datetime.utcnow()
        run.finished_at = now
        run.status = status
        if run.started_at:
            run.duration_seconds = round((now - run.started_at).total_seconds(), 2)
        if message:
            run.message = message[:1000]
        if details is not None:
            try:
                run.details_json = json.dumps(details, default=str)
            except (TypeError, ValueError) as e:
                log.warning("_finish_run: details_json serialize failed: %s", e)
                run.details_json = json.dumps({"_serialize_error": str(e)})
        session.add(run)
        session.commit()


# ---------------------------------------------------------------------------
# Floor checks — turn silent partial-success into a visible 'degraded' status
# ---------------------------------------------------------------------------
# A step can finish WITHOUT raising yet still under-deliver: a source feed dies
# and ingest returns errors>0, a Haiku batch fails (enrich failed>0), or a
# non-blocking step (article_fetch / backfill_region / release refresh) errors
# and is swallowed. Pre-floor-checks all of these still showed status='ok' —
# the exact "all green but <1000 mentions" false positive. _evaluate_floors
# reads the per-step counts already in `details` and returns one warning per
# tripped floor; any warning downgrades an otherwise-ok run to 'degraded'.

# Steps the orchestrators wrap as {"error": "..."} on a swallowed exception.
_NONBLOCKING_STEPS = (
    "article_fetch", "enrich_after_fetch", "backfill_region",
    "release_refresh_pcgamer", "release_refresh_ign", "pcgamer", "ign",
)


def _evaluate_floors(details: dict) -> list[str]:
    """Return human-readable warnings for steps that completed but under-
    delivered. Empty list => the run met every floor. Reads only verified
    per-step keys (see app/services/{ingest,enrich,article_fetch}.py)."""
    warnings: list[str] = []

    # 1. Non-blocking steps that quietly errored (previously invisible).
    for step in _NONBLOCKING_STEPS:
        d = details.get(step)
        if isinstance(d, dict) and d.get("error"):
            warnings.append(f"{step} errored: {d['error']}")

    # 2. Ingest: any source that failed its fetch. The headline "<1000 mentions"
    #    signal — a dead feed returns errors>0 without raising.
    ing = details.get("ingest")
    if isinstance(ing, dict):
        if ing.get("errors", 0):
            warnings.append(f"ingest: {ing['errors']} source(s) errored")
        elif ing.get("fetched", None) == 0:
            warnings.append("ingest fetched 0 items (every source dry?)")

    # 3. Enrich / embed: per-item failures are tolerated mid-step but should
    #    still surface — a bad batch silently shrinks the enriched corpus.
    for step in ("enrich", "enrich_after_fetch", "embed"):
        d = details.get(step)
        if isinstance(d, dict) and d.get("failed", 0):
            warnings.append(f"{step}: {d['failed']} item(s) failed")

    return warnings


def _apply_floor_status(
    status: str, details: dict, message: Optional[str]
) -> tuple[str, Optional[str]]:
    """Downgrade an otherwise-'ok' run to 'degraded' when any floor check trips.
    'failed'/'skipped'/'running' pass through unchanged. The returned message
    keeps the success counts and appends what degraded it; the warning list is
    also stored under details['_warnings'] for the expand-row view."""
    if status != "ok":
        return status, message
    warnings = _evaluate_floors(details)
    if not warnings:
        return status, message
    details["_warnings"] = warnings
    suffix = "DEGRADED: " + "; ".join(warnings)
    return "degraded", (f"{message} | {suffix}" if message else suffix)


def reconcile_interrupted_runs() -> int:
    """Mark any JobRun still in 'running' as failed (interrupted). Returns count.

    This app is single-process, so a 'running' row observed from a fresh process
    can only be a run whose process exited before `_finish_run` — e.g. uvicorn
    was killed mid-pipeline. Left alone it makes the /runs health band report a
    phantom in-flight job: precisely the false positive the console must avoid.
    Called once from the FastAPI lifespan on every boot (regardless of
    SCHEDULER_ENABLED)."""
    with Session(engine) as session:
        rows = session.exec(select(JobRun).where(JobRun.status == "running")).all()
        if not rows:
            return 0
        now = datetime.utcnow()
        for run in rows:
            run.status = "failed"
            run.finished_at = now
            if run.started_at:
                run.duration_seconds = round((now - run.started_at).total_seconds(), 2)
            run.message = "interrupted — process exited before completion (auto-reconciled)"
            session.add(run)
        session.commit()
        log.info(
            "reconcile_interrupted_runs: marked %d stale 'running' row(s) as failed",
            len(rows),
        )
        return len(rows)


def _current_iso_week_id() -> str:
    iso = datetime.utcnow().isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _previous_iso_week_id() -> str:
    iso = (datetime.utcnow() - timedelta(days=7)).isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _previous_week_needs_synthesis() -> Optional[str]:
    """Return the previous ISO week id if it's closed but NOT yet synthesized,
    else None. Drives the weekly brief chained off each daily run (replaces the
    standalone weekly cron). Idempotent: once the week is synthesized, returns
    None so later dailies skip it."""
    from app.services.reports import iso_week_bounds

    prev = _previous_iso_week_id()
    week_start, _ = iso_week_bounds(prev)
    with Session(engine) as session:
        row = session.exec(
            select(WeeklyReport).where(WeeklyReport.week_start == week_start)
        ).first()
        if row and row.status == "synthesized":
            return None
        return prev


# ---------------------------------------------------------------------------
# Daily orchestrator
# ---------------------------------------------------------------------------

def run_daily_pipeline(triggered_by: str = "scheduler") -> dict:
    """Full daily pipeline: ingest -> enrich -> embed -> article_fetch ->
    enrich (newly-fetched) -> backfill_region -> cluster current week.

    Step semantics:
      - ingest: hard failure -> abort, no enrich/embed (no new items to chew).
      - enrich: continues even on per-item failures (existing behavior).
      - embed: continues even on per-item failures.
      - article_fetch: NON-BLOCKING. Failure here does NOT stop the run; we
        still cluster what we have.
      - enrich (second pass) - only runs if article_fetch fetched bodies.
      - backfill_region: NON-BLOCKING. Failure does NOT stop clustering.
      - cluster: clustering current ISO week incrementally.

    Returns a dict so the manual-trigger endpoints can show the counts.
    """
    if not _JOB_LOCK.acquire(blocking=False):
        log.warning("run_daily_pipeline: another job is running; skipping")
        run_id = _start_run("daily_pipeline", triggered_by)
        _finish_run(run_id, "skipped", message="another job already running")
        return {"skipped": True, "reason": "another job already running"}

    run_id = _start_run("daily_pipeline", triggered_by)
    run_started = datetime.utcnow()  # scopes the region step to THIS run's items
    details: dict[str, Any] = {}
    overall_status = "ok"
    overall_message: Optional[str] = None
    try:
        # Local imports — heavy modules stay out of app startup.
        from app.services.article_fetch import fetch_skipped_bodies
        from app.services.cluster import cluster_window_incremental
        from app.services.enrich import embed_pending, enrich_pending
        from app.services.ingest import ingest_all
        from app.services.reports import iso_week_bounds

        log.info("=== run_daily_pipeline start (triggered_by=%s) ===", triggered_by)

        # Step 1 — ingest
        try:
            details["ingest"] = ingest_all()
        except Exception as e:  # noqa: BLE001
            details["ingest"] = {"error": f"{type(e).__name__}: {e}"}
            overall_status = "failed"
            overall_message = f"ingest failed: {e}"
            return {"status": overall_status, "details": details, "message": overall_message}

        # Step 2 — enrich
        try:
            details["enrich"] = enrich_pending()
        except Exception as e:  # noqa: BLE001
            details["enrich"] = {"error": f"{type(e).__name__}: {e}"}
            overall_status = "failed"
            overall_message = f"enrich failed: {e}"

        # Step 3 — embed
        try:
            details["embed"] = embed_pending()
        except Exception as e:  # noqa: BLE001
            details["embed"] = {"error": f"{type(e).__name__}: {e}"}
            overall_status = "failed"
            overall_message = (overall_message or "") + f"; embed failed: {e}"

        # Step 4 — article_fetch (non-blocking)
        try:
            details["article_fetch"] = fetch_skipped_bodies()
        except Exception as e:  # noqa: BLE001
            details["article_fetch"] = {"error": f"{type(e).__name__}: {e}"}
            log.warning("article_fetch failed (non-blocking): %s", e)

        # Step 5 — re-enrich ONLY the items that just got article bodies (the ids
        # returned by step 4), not the whole skipped backlog. The old
        # retry_failed=True re-scanned every non-ok item each night, re-running
        # Whisper over the entire YouTube backlog (~55 min). See DECISIONS 2026-06-10.
        af = details.get("article_fetch") or {}
        fetched_ids = af.get("fetched_ids") if isinstance(af, dict) else None
        if fetched_ids:
            try:
                details["enrich_after_fetch"] = enrich_pending(item_ids=fetched_ids)
            except Exception as e:  # noqa: BLE001
                details["enrich_after_fetch"] = {"error": f"{type(e).__name__}: {e}"}
                log.warning("enrich_after_fetch failed (non-blocking): %s", e)
        else:
            details["enrich_after_fetch"] = {"skipped": "no new bodies fetched"}

        # Step 6 — backfill_region (non-blocking), SCOPED to this run's items.
        # backfill_region.run() with no args re-scans every region_focus IS NULL
        # row each night — but most items legitimately have no region, so they
        # stay NULL and get re-billed (~10k Haiku calls/night). Restricting to
        # enrichments created during THIS run keeps it to the day's new items.
        # The full-corpus backfill stays available as the manual script.
        # See DECISIONS 2026-06-10.
        try:
            _ensure_repo_on_path()
            from scripts import backfill_region
            with Session(engine) as _rs:
                new_region_ids = list(_rs.exec(
                    select(Enrichment.item_id).where(
                        Enrichment.created_at >= run_started,
                        Enrichment.region_focus.is_(None),
                        Enrichment.status == "ok",
                    )
                ).all())
            if new_region_ids:
                details["backfill_region"] = backfill_region.run(ids=new_region_ids)
            else:
                details["backfill_region"] = {"skipped": "no new enrichments to region-tag", "attempted": 0}
        except Exception as e:  # noqa: BLE001
            details["backfill_region"] = {"error": f"{type(e).__name__}: {e}"}
            log.warning("backfill_region failed (non-blocking): %s", e)

        # Step 7 — cluster current ISO week (incremental).
        curr = _current_iso_week_id()
        try:
            curr_start, curr_end = iso_week_bounds(curr)
            details["cluster_current"] = cluster_window_incremental(
                start=curr_start, end=curr_end, week_id=curr
            )
            details["cluster_current"]["week_id"] = curr
        except Exception as e:  # noqa: BLE001
            details["cluster_current"] = {"error": f"{type(e).__name__}: {e}", "week_id": curr}
            overall_status = "failed"
            overall_message = (overall_message or "") + f"; cluster failed: {e}"

        if overall_status == "ok":
            ing = details.get("ingest") or {}
            enr = details.get("enrich") or {}
            clu = details.get("cluster_current") or {}
            overall_message = (
                f"new={ing.get('new', 0)} "
                f"enriched_ok={enr.get('ok', 0)} "
                f"clusters_touched={clu.get('clusters_existing_touched', 0)} "
                f"clusters_new={clu.get('clusters_new_created', 0)}"
            )
        overall_status, overall_message = _apply_floor_status(
            overall_status, details, overall_message
        )

        # Chained weekly brief. Replaces the standalone weekly cron: once a week
        # closes, the first daily after it (which has just ingested that week's
        # tail) briefs it. Runs INSIDE the daily so it can't start before ingest
        # finishes, regardless of how long ingest takes; the RLock is re-entrant
        # so the same thread re-acquires it. Self-heals a missed run. Skipped if
        # the daily hard-failed (don't brief on incomplete ingest).
        if overall_status != "failed":
            wk = _previous_week_needs_synthesis()
            if wk:
                log.info("daily: week %s not synthesized — chaining weekly extension", wk)
                details["weekly_chained"] = run_weekly_extension(week_id=wk, triggered_by="chained")

        log.info("=== run_daily_pipeline done: status=%s %s ===", overall_status, overall_message)
        return {"status": overall_status, "details": details, "message": overall_message}
    except Exception as e:  # noqa: BLE001
        log.exception("run_daily_pipeline crashed")
        overall_status = "failed"
        overall_message = f"unhandled: {type(e).__name__}: {e}"
        return {"status": overall_status, "details": details, "message": overall_message}
    finally:
        _finish_run(run_id, overall_status, message=overall_message, details=details)
        _JOB_LOCK.release()


# ---------------------------------------------------------------------------
# Weekly orchestrator
# ---------------------------------------------------------------------------

def run_weekly_extension(week_id: Optional[str] = None, triggered_by: str = "scheduler") -> dict:
    """Cluster + synthesize a closed week, then refresh PC Gamer + IGN release
    calendars. `week_id` defaults to the previous ISO week (the manual-trigger
    case); the daily chain passes an explicit week. The brief is ready Monday
    morning because the Sunday-night daily (23:00 CST) chains this once the
    week's UTC boundary has already rolled over.
    """
    if not _JOB_LOCK.acquire(blocking=False):
        log.warning("run_weekly_extension: another job is running; skipping")
        run_id = _start_run("weekly_extension", triggered_by)
        _finish_run(run_id, "skipped", message="another job already running")
        return {"skipped": True, "reason": "another job already running"}

    run_id = _start_run("weekly_extension", triggered_by)
    details: dict[str, Any] = {}
    overall_status = "ok"
    overall_message: Optional[str] = None
    try:
        from app.services.cluster import cluster_window_incremental
        from app.services.reports import iso_week_bounds
        from app.services.synthesis import synthesize_week

        prev = week_id or _previous_iso_week_id()
        log.info("=== run_weekly_extension start (week=%s, triggered_by=%s) ===", prev, triggered_by)

        # Step 1 — cluster previous week (catch any late-arriving items).
        try:
            prev_start, prev_end = iso_week_bounds(prev)
            details["cluster_previous"] = cluster_window_incremental(
                start=prev_start, end=prev_end, week_id=prev
            )
            details["cluster_previous"]["week_id"] = prev
        except Exception as e:  # noqa: BLE001
            details["cluster_previous"] = {"error": f"{type(e).__name__}: {e}", "week_id": prev}
            overall_status = "failed"
            overall_message = f"cluster_previous failed: {e}"

        # Step 2 — synthesize previous week.
        try:
            with Session(engine) as session:
                res = synthesize_week(session, prev, force=True)
            details["synthesize_previous"] = {
                "week_id": prev,
                "model": res.get("model"),
                "from_cache": res.get("from_cache"),
            }
        except Exception as e:  # noqa: BLE001
            details["synthesize_previous"] = {"error": f"{type(e).__name__}: {e}", "week_id": prev}
            overall_status = "failed"
            overall_message = (overall_message or "") + f"; synthesize_previous failed: {e}"

        # Step 3 — refresh PC Gamer + IGN release calendars (non-blocking).
        try:
            _ensure_repo_on_path()
            from scripts import refresh_pcgamer_releases
            details["release_refresh_pcgamer"] = refresh_pcgamer_releases.run()
        except Exception as e:  # noqa: BLE001
            details["release_refresh_pcgamer"] = {"error": f"{type(e).__name__}: {e}"}
            log.warning("release_refresh_pcgamer failed (non-blocking): %s", e)

        try:
            _ensure_repo_on_path()
            from scripts import refresh_ign_releases
            details["release_refresh_ign"] = refresh_ign_releases.run()
        except Exception as e:  # noqa: BLE001
            details["release_refresh_ign"] = {"error": f"{type(e).__name__}: {e}"}
            log.warning("release_refresh_ign failed (non-blocking): %s", e)

        if overall_status == "ok":
            overall_message = f"synthesized prev={prev}"
        overall_status, overall_message = _apply_floor_status(
            overall_status, details, overall_message
        )
        log.info("=== run_weekly_extension done: status=%s %s ===", overall_status, overall_message)
        return {"status": overall_status, "details": details, "message": overall_message}
    except Exception as e:  # noqa: BLE001
        log.exception("run_weekly_extension crashed")
        overall_status = "failed"
        overall_message = f"unhandled: {type(e).__name__}: {e}"
        return {"status": overall_status, "details": details, "message": overall_message}
    finally:
        _finish_run(run_id, overall_status, message=overall_message, details=details)
        _JOB_LOCK.release()


# ---------------------------------------------------------------------------
# Standalone release-calendar refresh
# ---------------------------------------------------------------------------

def run_release_refresh(triggered_by: str = "manual") -> dict:
    """Refresh PC Gamer + IGN release calendars only (no clustering / synth)."""
    if not _JOB_LOCK.acquire(blocking=False):
        log.warning("run_release_refresh: another job is running; skipping")
        run_id = _start_run("release_refresh", triggered_by)
        _finish_run(run_id, "skipped", message="another job already running")
        return {"skipped": True, "reason": "another job already running"}

    run_id = _start_run("release_refresh", triggered_by)
    details: dict[str, Any] = {}
    overall_status = "ok"
    overall_message: Optional[str] = None
    try:
        _ensure_repo_on_path()
        try:
            from scripts import refresh_pcgamer_releases
            details["pcgamer"] = refresh_pcgamer_releases.run()
        except Exception as e:  # noqa: BLE001
            details["pcgamer"] = {"error": f"{type(e).__name__}: {e}"}
            overall_status = "failed"
            overall_message = f"pcgamer refresh failed: {e}"

        try:
            from scripts import refresh_ign_releases
            details["ign"] = refresh_ign_releases.run()
        except Exception as e:  # noqa: BLE001
            details["ign"] = {"error": f"{type(e).__name__}: {e}"}
            overall_status = "failed"
            overall_message = (overall_message or "") + f"; ign refresh failed: {e}"

        if overall_status == "ok":
            pc = details.get("pcgamer") or {}
            ig = details.get("ign") or {}
            overall_message = (
                f"pcgamer: new={pc.get('new', 0)} updated={pc.get('updated', 0)}; "
                f"ign: new={ig.get('new', 0)} updated={ig.get('updated', 0)}"
            )
        overall_status, overall_message = _apply_floor_status(
            overall_status, details, overall_message
        )
        return {"status": overall_status, "details": details, "message": overall_message}
    except Exception as e:  # noqa: BLE001
        log.exception("run_release_refresh crashed")
        overall_status = "failed"
        overall_message = f"unhandled: {type(e).__name__}: {e}"
        return {"status": overall_status, "details": details, "message": overall_message}
    finally:
        _finish_run(run_id, overall_status, message=overall_message, details=details)
        _JOB_LOCK.release()


# ---------------------------------------------------------------------------
# Granular manual wrappers (for the Run-now panel on /runs)
# ---------------------------------------------------------------------------

def run_ingest_only(triggered_by: str = "manual") -> dict:
    """Run ingest_all under a JobRun row. Manual trigger only."""
    if not _JOB_LOCK.acquire(blocking=False):
        run_id = _start_run("ingest_only", triggered_by)
        _finish_run(run_id, "skipped", message="another job already running")
        return {"skipped": True, "reason": "another job already running"}

    run_id = _start_run("ingest_only", triggered_by)
    details: dict[str, Any] = {}
    status = "ok"
    message: Optional[str] = None
    try:
        from app.services.ingest import ingest_all
        details["ingest"] = ingest_all()
        message = f"new={details['ingest'].get('new', 0)} errors={details['ingest'].get('errors', 0)}"
        status, message = _apply_floor_status(status, details, message)
        return {"status": status, "details": details, "message": message}
    except Exception as e:  # noqa: BLE001
        log.exception("run_ingest_only crashed")
        status = "failed"
        message = f"{type(e).__name__}: {e}"
        return {"status": status, "details": details, "message": message}
    finally:
        _finish_run(run_id, status, message=message, details=details)
        _JOB_LOCK.release()


def run_enrich_only(triggered_by: str = "manual") -> dict:
    """Run enrich_pending + embed_pending under a JobRun row."""
    if not _JOB_LOCK.acquire(blocking=False):
        run_id = _start_run("enrich_only", triggered_by)
        _finish_run(run_id, "skipped", message="another job already running")
        return {"skipped": True, "reason": "another job already running"}

    run_id = _start_run("enrich_only", triggered_by)
    details: dict[str, Any] = {}
    status = "ok"
    message: Optional[str] = None
    try:
        from app.services.enrich import embed_pending, enrich_pending
        details["enrich"] = enrich_pending()
        details["embed"] = embed_pending()
        message = (
            f"enrich_ok={details['enrich'].get('ok', 0)} "
            f"embed_ok={details['embed'].get('ok', 0)}"
        )
        status, message = _apply_floor_status(status, details, message)
        return {"status": status, "details": details, "message": message}
    except Exception as e:  # noqa: BLE001
        log.exception("run_enrich_only crashed")
        status = "failed"
        message = f"{type(e).__name__}: {e}"
        return {"status": status, "details": details, "message": message}
    finally:
        _finish_run(run_id, status, message=message, details=details)
        _JOB_LOCK.release()


def run_cluster_only(week_id: Optional[str] = None, triggered_by: str = "manual") -> dict:
    """Cluster a single ISO week incrementally. Defaults to current week."""
    if not _JOB_LOCK.acquire(blocking=False):
        run_id = _start_run("cluster_only", triggered_by)
        _finish_run(run_id, "skipped", message="another job already running")
        return {"skipped": True, "reason": "another job already running"}

    target_week = week_id or _current_iso_week_id()
    run_id = _start_run("cluster_only", triggered_by)
    details: dict[str, Any] = {"week_id": target_week}
    status = "ok"
    message: Optional[str] = None
    try:
        from app.services.cluster import cluster_window_incremental
        from app.services.reports import iso_week_bounds
        start, end = iso_week_bounds(target_week)
        details["cluster"] = cluster_window_incremental(start=start, end=end, week_id=target_week)
        message = (
            f"week={target_week} "
            f"appended={details['cluster'].get('items_appended_existing', 0)} "
            f"new_clusters={details['cluster'].get('clusters_new_created', 0)}"
        )
        return {"status": status, "details": details, "message": message}
    except Exception as e:  # noqa: BLE001
        log.exception("run_cluster_only crashed")
        status = "failed"
        message = f"{type(e).__name__}: {e}"
        return {"status": status, "details": details, "message": message}
    finally:
        _finish_run(run_id, status, message=message, details=details)
        _JOB_LOCK.release()


def run_synthesis_only(week_id: Optional[str] = None, triggered_by: str = "manual") -> dict:
    """Synthesize a single ISO week. Defaults to previous week (the typical
    Monday-morning manual target)."""
    if not _JOB_LOCK.acquire(blocking=False):
        run_id = _start_run("synthesis_only", triggered_by)
        _finish_run(run_id, "skipped", message="another job already running")
        return {"skipped": True, "reason": "another job already running"}

    target_week = week_id or _previous_iso_week_id()
    run_id = _start_run("synthesis_only", triggered_by)
    details: dict[str, Any] = {"week_id": target_week}
    status = "ok"
    message: Optional[str] = None
    try:
        from app.services.synthesis import synthesize_week
        with Session(engine) as session:
            res = synthesize_week(session, target_week, force=True)
        details["synthesis"] = {
            "week_id": target_week,
            "model": res.get("model"),
            "from_cache": res.get("from_cache"),
        }
        message = f"synthesized week={target_week} model={res.get('model')}"
        return {"status": status, "details": details, "message": message}
    except Exception as e:  # noqa: BLE001
        log.exception("run_synthesis_only crashed")
        status = "failed"
        message = f"{type(e).__name__}: {e}"
        return {"status": status, "details": details, "message": message}
    finally:
        _finish_run(run_id, status, message=message, details=details)
        _JOB_LOCK.release()


# ---------------------------------------------------------------------------
# Startup catch-up
# ---------------------------------------------------------------------------

# Catch-up window. A daily_pipeline that finished more than 24h ago is "overdue"
# and we fire one immediately on boot. The weekly brief no longer has its own
# catch-up: it's chained off the daily, so firing the overdue daily also briefs
# any unsynthesized closed week (see run_daily_pipeline).
_DAILY_OVERDUE_HOURS = 24


def _last_run(job_name: str) -> Optional[JobRun]:
    """Return the most recent JobRun row for `job_name`, or None."""
    with Session(engine) as session:
        row = session.exec(
            select(JobRun).where(JobRun.job_name == job_name).order_by(JobRun.started_at.desc())
        ).first()
        return row


def _is_daily_overdue(now: datetime) -> tuple[bool, str]:
    last = _last_run("daily_pipeline")
    if last is None:
        return True, "no prior daily_pipeline run"
    if last.finished_at is None:
        return True, f"prior daily_pipeline (id={last.id}) is interrupted (finished_at IS NULL)"
    age = now - last.started_at
    if age > timedelta(hours=_DAILY_OVERDUE_HOURS):
        return True, f"last daily_pipeline started {age.total_seconds()/3600:.1f}h ago"
    return False, f"last daily_pipeline {age.total_seconds()/3600:.1f}h ago — not overdue"


def run_startup_catchup() -> dict:
    """Fire an overdue daily job on boot (in a background thread). The daily
    chains the weekly brief itself, so there's no separate weekly catch-up.

    Called from the FastAPI lifespan hook ONLY when SCHEDULER_ENABLED is set.
    Returns a dict for inspection (mostly useful in tests / debug). The decision
    is also recorded as a JobRun row with `triggered_by='startup_catchup'` when
    the underlying orchestrator runs.
    """
    now = datetime.utcnow()
    decisions: dict[str, Any] = {}

    daily_due, daily_reason = _is_daily_overdue(now)
    decisions["daily"] = {"overdue": daily_due, "reason": daily_reason}
    if daily_due:
        log.info("startup_catchup: firing daily_pipeline — %s", daily_reason)
        t = threading.Thread(
            target=run_daily_pipeline,
            kwargs={"triggered_by": "startup_catchup"},
            name="startup_catchup_daily",
            daemon=True,
        )
        t.start()

    return decisions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_repo_on_path() -> None:
    """The `scripts/` directory is not a package on sys.path under uvicorn.
    Add the repo root so `from scripts import ...` works from the orchestrator.
    Idempotent — checks before appending.
    """
    repo_root = str(Path(__file__).resolve().parent.parent.parent)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
