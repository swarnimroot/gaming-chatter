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

from app.db.models import JobRun
from app.db.session import engine

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
        return run.id


def _finish_run(
    run_id: int,
    status: str,
    message: Optional[str] = None,
    details: Optional[dict] = None,
) -> None:
    """Patch the JobRun row in place with terminal status + details."""
    with Session(engine) as session:
        run = session.get(JobRun, run_id)
        if run is None:
            log.warning("_finish_run: JobRun id=%s vanished mid-run", run_id)
            return
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


def _current_iso_week_id() -> str:
    iso = datetime.utcnow().isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _previous_iso_week_id() -> str:
    iso = (datetime.utcnow() - timedelta(days=7)).isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


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

        # Step 5 — enrich second pass over newly-fetched items. Only worth
        # running if step 4 actually fetched bodies; otherwise skip the
        # whole-corpus re-scan.
        af = details.get("article_fetch") or {}
        if isinstance(af, dict) and af.get("fetched", 0) > 0:
            try:
                details["enrich_after_fetch"] = enrich_pending(retry_failed=True)
            except Exception as e:  # noqa: BLE001
                details["enrich_after_fetch"] = {"error": f"{type(e).__name__}: {e}"}
                log.warning("enrich_after_fetch failed (non-blocking): %s", e)
        else:
            details["enrich_after_fetch"] = {"skipped": "no new bodies fetched"}

        # Step 6 — backfill_region (non-blocking)
        try:
            # Importing the script as a module — sys.path already has repo root
            # under uvicorn since the project lives at the cwd.
            _ensure_repo_on_path()
            from scripts import backfill_region
            details["backfill_region"] = backfill_region.run()
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
        log.info("=== run_daily_pipeline done: %s ===", overall_message)
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

def run_weekly_extension(triggered_by: str = "scheduler") -> dict:
    """Monday-morning extension: cluster previous-week + synthesize previous-week
    + refresh PC Gamer + IGN release calendars.

    "Previous week" = the ISO week ending the day before today (so a Monday run
    targets the week that just closed).
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

        prev = _previous_iso_week_id()
        log.info("=== run_weekly_extension start (prev=%s, triggered_by=%s) ===", prev, triggered_by)

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
        log.info("=== run_weekly_extension done: %s ===", overall_message)
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

# Catch-up windows. A daily_pipeline finished more than 24h ago is considered
# "overdue" and we fire one immediately on boot. The weekly_extension cron is
# Monday 07:30; if today is Mon/Tue/Wed and the last weekly_extension finished
# more than 8 days ago (or never ran), we fire one too.
_DAILY_OVERDUE_HOURS = 24
_WEEKLY_OVERDUE_DAYS = 8
_WEEKLY_CATCHUP_WEEKDAYS = {0, 1, 2}  # Monday=0..Wednesday=2 (python weekday())


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


def _is_weekly_overdue(now: datetime) -> tuple[bool, str]:
    if now.weekday() not in _WEEKLY_CATCHUP_WEEKDAYS:
        return False, f"weekday={now.weekday()} outside catch-up window"
    last = _last_run("weekly_extension")
    if last is None:
        return True, "no prior weekly_extension run"
    age = now - last.started_at
    if age > timedelta(days=_WEEKLY_OVERDUE_DAYS):
        return True, f"last weekly_extension started {age.days}d ago"
    return False, f"last weekly_extension {age.days}d ago — not overdue"


def run_startup_catchup() -> dict:
    """Fire any overdue daily / weekly jobs in background threads.

    Called from the FastAPI lifespan hook ONLY when SCHEDULER_ENABLED is set.
    Returns a dict for inspection (mostly useful in tests / debug). Each
    decision is also recorded as a JobRun row with `triggered_by='startup_catchup'`
    when the underlying orchestrator runs.
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

    weekly_due, weekly_reason = _is_weekly_overdue(now)
    decisions["weekly"] = {"overdue": weekly_due, "reason": weekly_reason}
    if weekly_due:
        log.info("startup_catchup: firing weekly_extension — %s", weekly_reason)
        # Tiny delay-driven offset: weekly waits for daily to acquire the lock
        # first if both fire on the same boot. Both threads block on _JOB_LOCK
        # so this is just an ordering hint, not a correctness requirement.
        def _delayed_weekly():
            import time as _t
            _t.sleep(2.0)
            run_weekly_extension(triggered_by="startup_catchup")
        t = threading.Thread(target=_delayed_weekly, name="startup_catchup_weekly", daemon=True)
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
