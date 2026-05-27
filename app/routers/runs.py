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
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.config import TEMPLATES_DIR
from app.db.models import JobRun
from app.db.session import get_session
from app.services import jobs as jobs_svc
from app.services.chrome import failing_sources_count, nav_items_for

router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
log = logging.getLogger(__name__)


# Manual-trigger whitelist. Maps the trigger URL slug to (callable, label,
# accepts_week_id). Anything not in this dict is rejected with 400.
_TRIGGER_MAP: dict[str, tuple] = {
    "daily_pipeline":    (jobs_svc.run_daily_pipeline,    "Daily pipeline",      False),
    "weekly_extension":  (jobs_svc.run_weekly_extension,  "Weekly extension",    False),
    "release_refresh":   (jobs_svc.run_release_refresh,   "Release refresh",     False),
    "ingest_only":       (jobs_svc.run_ingest_only,       "Ingest only",         False),
    "enrich_only":       (jobs_svc.run_enrich_only,       "Enrich + embed only", False),
    "cluster_only":      (jobs_svc.run_cluster_only,      "Cluster only",        True),
    "synthesis_only":    (jobs_svc.run_synthesis_only,    "Synthesis only",      True),
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


def _build_rows(session: Session, limit: int = 50) -> list[dict]:
    rows = session.exec(
        select(JobRun).order_by(JobRun.started_at.desc()).limit(limit)
    ).all()
    out: list[dict] = []
    for r in rows:
        out.append({
            "id": r.id,
            "job_name": r.job_name,
            "triggered_by": r.triggered_by,
            "status": r.status,
            "started_at": _fmt_dt(r.started_at),
            "duration": _fmt_duration(r.duration_seconds),
            "message": (r.message or "")[:240],
            "has_details": bool(r.details_json),
        })
    return out


@router.get("/runs", name="runs_view")
def runs_view(request: Request, session: Session = Depends(get_session)):
    ctx = {
        "rows": _build_rows(session, limit=50),
        "scheduler_enabled": _scheduler_enabled(),
        "trigger_jobs": [
            {"slug": slug, "label": label, "accepts_week": accepts_week}
            for slug, (_, label, accepts_week) in _TRIGGER_MAP.items()
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
    fn, label, accepts_week = entry

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
