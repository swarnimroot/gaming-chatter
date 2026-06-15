"""/runs — Phase 4 job-run UI + manual trigger endpoints.

The page is always reachable (no env-gating on the UI itself). When
SCHEDULER_ENABLED is unset the page renders with a "Scheduler: disabled" chip
and only the manual-trigger buttons do anything — scheduled crons + startup
catch-up only run when the env flag is on.

Endpoints:
  GET  /runs                          Jinja page — table of last 50 JobRun rows + Run-now buttons
  POST /runs/trigger/{job_name}       Schedule the named job on BackgroundTasks; returns an HTMX fragment
  GET  /runs/details/{run_id}         Pretty-print details_json for the expand-row toggle
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlmodel import Session, select

from app.config import TEMPLATES_DIR
from app.db.models import Enrichment, Item, JobRun, RawItem
from app.db.session import get_session
from app.services import jobs as jobs_svc
from app.services.chrome import (
    SOURCE_VOLUME_WINDOW_DAYS,
    failing_sources_count,
    nav_items_for,
    source_health,
)
from app.services.reports import readout_weeks

router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
log = logging.getLogger(__name__)


# Manual-trigger whitelist. Maps the trigger URL slug to (callable, label,
# accepts_week_id, confirm_message). The confirm_message is shown in a
# browser confirm() dialog (HTMX hx-confirm) before the job fires — these
# all spend real time and/or Anthropic API money. Anything not in this dict
# is rejected with 400.
_TRIGGER_MAP: dict[str, tuple] = {
    "daily_pipeline":    (jobs_svc.run_daily_pipeline,    "Daily pipeline",      False,
        "Runs the full pipeline (ingest → enrich → cluster → synthesis). ~4–6 hours and spends Anthropic API money (Haiku + Opus). Continue?"),
    "weekly_extension":  (jobs_svc.run_weekly_extension,  "Weekly extension",    False,
        "Regenerates the weekly brief via Opus synthesis. ~5–10 min and spends Anthropic API money. Continue?"),
    "release_refresh":   (jobs_svc.run_release_refresh,   "Release refresh",     False,
        "Refreshes the game/platform release data. ~2–5 min, no LLM cost. Continue?"),
    "ingest_only":       (jobs_svc.run_ingest_only,       "Ingest only",         False,
        "Fetches fresh items from all sources. ~10 min, no LLM cost (Reddit feeds are rate-gated to 1/min to avoid 429s). Continue?"),
    "enrich_only":       (jobs_svc.run_enrich_only,       "Enrich + embed only", False,
        "Runs Haiku enrichment + embeddings over pending items (incl. Whisper transcription). ~3–5 hours and spends Anthropic API money. Continue?"),
    "cluster_only":      (jobs_svc.run_cluster_only,      "Cluster only",        True,
        "Re-clusters the selected week's items; new clusters get Sonnet labels (spends Anthropic API money). ~5–15 min. Continue?"),
    "synthesis_only":    (jobs_svc.run_synthesis_only,    "Synthesis only",      True,
        "Re-runs Opus synthesis for the selected week, overwriting its brief. ~5–10 min and spends Anthropic API money. Continue?"),
}


def _scheduler_enabled() -> bool:
    return os.environ.get("SCHEDULER_ENABLED", "").lower() in ("1", "true", "yes")


def _fmt_dt(dt: Optional[datetime]) -> str:
    if dt is None:
        return "—"
    return dt.strftime("%b %d, %H:%M:%S")


def _fmt_duration(d: Optional[float]) -> str:
    if d is None:
        return "—"
    if d < 60:
        return f"{d:.1f}s"
    if d < 3600:
        return f"{int(d // 60)}m {int(d % 60)}s"
    return f"{int(d // 3600)}h {int((d % 3600) // 60)}m"


# ── Health band (Phase 4 operator console) ──────────────────────────────────
# A scheduled job whose most-recent run is older than these is flagged "stale"
# even if that run succeeded — i.e. the cron silently stopped firing.
_DAILY_STALE_S = 25 * 3600
_WEEKLY_STALE_S = 8 * 86400


def _current_iso_week_id() -> str:
    iso = datetime.utcnow().isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _fmt_span(secs: float) -> str:
    """Compact duration like '45m' / '6h 12m' / '2d 9h'."""
    secs = int(max(0, secs))
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 86400:
        return f"{secs // 3600}h {(secs % 3600) // 60}m"
    return f"{secs // 86400}d {(secs % 86400) // 3600}h"


def _fmt_ago(dt: Optional[datetime]) -> str:
    if dt is None:
        return "never"
    return _fmt_span((datetime.utcnow() - dt).total_seconds()) + " ago"


def _next_run_secs(job_id: str) -> Optional[float]:
    """Seconds until the named APScheduler job next fires, or None when the
    scheduler isn't running (SCHEDULER_ENABLED off) or the job is absent.

    `app.main` is imported lazily — main.py imports this router at module load,
    so a top-level import would be circular."""
    import app.main as main_module

    sched = getattr(main_module, "_scheduler", None)
    if sched is None:
        return None
    job = sched.get_job(job_id)
    if job is None or job.next_run_time is None:
        return None
    # next_run_time is tz-aware; compare via epoch to dodge naive/aware math.
    return job.next_run_time.timestamp() - time.time()


def _job_health(session: Session, job_name: str, stale_after_s: int) -> dict:
    row = session.exec(
        select(JobRun)
        .where(JobRun.job_name == job_name)
        .order_by(JobRun.started_at.desc())
    ).first()
    last_dt = (row.finished_at or row.started_at) if row else None
    age_s = (datetime.utcnow() - last_dt).total_seconds() if last_dt else None
    next_s = _next_run_secs(job_name)
    return {
        "status": row.status if row else "none",
        "last_ago": _fmt_ago(last_dt),
        "stale": age_s is not None and age_s > stale_after_s,
        "next_in": _fmt_span(next_s) if next_s is not None else None,
    }


def _scalar_count(session: Session, stmt) -> int:
    result = session.exec(stmt).first()
    return int(result or 0)


def _build_health(session: Session) -> dict:
    """Top-of-page operator glance: scheduled-job status + next-run countdown
    + corpus freshness. Read-only; no pipeline side effects."""
    total_items = _scalar_count(session, select(func.count(Item.id)))
    enriched_ok = _scalar_count(
        session, select(func.count(Enrichment.id)).where(Enrichment.status == "ok")
    )
    newest = session.exec(select(func.max(RawItem.fetched_at))).first()

    synth_weeks = readout_weeks(session)  # newest ISO week first
    cur_week = _current_iso_week_id()

    return {
        "daily": _job_health(session, "daily_pipeline", _DAILY_STALE_S),
        "weekly": _job_health(session, "weekly_extension", _WEEKLY_STALE_S),
        "total_items": total_items,
        "enrich_pct": round(100.0 * enriched_ok / total_items, 1) if total_items else 0.0,
        "newest_ago": _fmt_ago(newest),
        "cur_week": cur_week,
        "cur_week_synth": cur_week in set(synth_weeks),
        "latest_synth": synth_weeks[0] if synth_weeks else None,
    }


def _cost_phase_title(details_json: Optional[str]) -> Optional[str]:
    """Compact per-phase $ summary for the Cost-column tooltip, e.g.
    'enrich $0.84 (343 calls) · region_tag $0.29 (309 calls)'. None when the
    row predates the per-phase meter (no _cost_by_phase key)."""
    if not details_json:
        return None
    try:
        by_phase = json.loads(details_json).get("_cost_by_phase")
    except (ValueError, TypeError):
        return None
    if not isinstance(by_phase, dict) or not by_phase:
        return None
    parts = [
        f"{phase} ${p.get('cost_usd', 0):.4f} ({p.get('calls', 0)} calls)"
        for phase, p in sorted(
            by_phase.items(), key=lambda kv: kv[1].get("cost_usd", 0), reverse=True
        )
    ]
    return " · ".join(parts)


def _build_rows(session: Session, limit: int = 50) -> list[dict]:
    rows = session.exec(
        select(JobRun).order_by(JobRun.started_at.desc()).limit(limit)
    ).all()
    out: list[dict] = []
    for r in rows:
        tokens_title = (
            f"{r.input_tokens:,} in / {r.output_tokens:,} out"
            if r.input_tokens is not None else None
        )
        phase_title = _cost_phase_title(r.details_json) if r.cost_usd is not None else None
        out.append({
            "id": r.id,
            "job_name": r.job_name,
            "triggered_by": r.triggered_by,
            "status": r.status,
            "started_at": _fmt_dt(r.started_at),
            "duration": _fmt_duration(r.duration_seconds),
            "message": (r.message or "")[:240],
            "has_details": bool(r.details_json),
            "cost": f"${r.cost_usd:.1f}" if r.cost_usd is not None else None,
            "tokens_title": (
                f"{phase_title} — {tokens_title}" if phase_title and tokens_title
                else tokens_title
            ),
        })
    return out


@router.get("/runs", name="runs_view")
def runs_view(request: Request, session: Session = Depends(get_session)):
    ctx = {
        "rows": _build_rows(session, limit=50),
        "health": _build_health(session),
        "sources": [
            {**h, "last_ago": _fmt_ago(h["last_started_at"])}
            for h in source_health(session)
        ],
        "source_window_days": SOURCE_VOLUME_WINDOW_DAYS,
        "scheduler_enabled": _scheduler_enabled(),
        "trigger_jobs": [
            {"slug": slug, "label": label, "accepts_week": accepts_week,
             "confirm": confirm}
            for slug, (_, label, accepts_week, confirm) in _TRIGGER_MAP.items()
        ],
        "nav_items": nav_items_for(request, "runs"),
        "failing_sources_count": failing_sources_count(session),
    }
    return templates.TemplateResponse(request, "runs.html", ctx)


@router.post("/runs/trigger/{job_name}", response_class=HTMLResponse)
def runs_trigger(
    job_name: str,
    bg: BackgroundTasks,
    week_id: Optional[str] = Form(default=None),
):
    entry = _TRIGGER_MAP.get(job_name)
    if entry is None:
        raise HTTPException(status_code=400, detail=f"unknown job_name: {job_name!r}")
    fn, label, accepts_week, _confirm = entry

    started = datetime.utcnow().strftime("%H:%M:%S")
    if accepts_week:
        wk = (week_id or "").strip() or None
        bg.add_task(fn, week_id=wk, triggered_by="manual")
        wk_note = f" (week={wk})" if wk else " (default week)"
    else:
        bg.add_task(fn, triggered_by="manual")
        wk_note = ""

    log.info("manual trigger queued: %s%s", job_name, wk_note)
    return HTMLResponse(
        f'<div id="run-status" class="gc-run-status gc-run-status--running">'
        f'Started "{label}"{wk_note} at {started}. '
        f'<a href="/runs">Refresh /runs</a> in a few seconds.'
        f'</div>'
    )


@router.post("/runs/trigger-scheduled/daily", response_class=HTMLResponse)
def runs_trigger_scheduled_daily(bg: BackgroundTasks):
    """Automated daily trigger for the Windows Task Scheduler poke
    (scripts/trigger_daily.ps1). Unlike the manual trigger above, this goes
    through jobs.run_daily_pipeline_scheduled, which dedups against the
    in-process APScheduler cron so two automated triggers can't double-spend
    the same night. Localhost-only app; no auth by design."""
    bg.add_task(jobs_svc.run_daily_pipeline_scheduled, triggered_by="schtask")
    log.info("schtask trigger queued: daily_pipeline (guarded)")
    return HTMLResponse("queued")


@router.get("/runs/details/{run_id}", response_class=HTMLResponse)
def runs_details(run_id: int, session: Session = Depends(get_session)):
    run = session.get(JobRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if not run.details_json:
        return HTMLResponse('<div class="gc-run-details gc-run-details--empty">No details.</div>')
    try:
        parsed = json.loads(run.details_json)
        pretty = json.dumps(parsed, indent=2, default=str)
    except (ValueError, TypeError):
        pretty = run.details_json  # fall back to raw
    return HTMLResponse(
        f'<div class="gc-run-details"><pre class="gc-run-details-pre">{_escape_html(pretty)}</pre></div>'
    )


def _escape_html(s: str) -> str:
    return (s.replace("&", "&amp;")
              .replace("<", "&lt;")
              .replace(">", "&gt;")
              .replace('"', "&quot;"))
