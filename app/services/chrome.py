"""Shared shell chrome — nav items + path-aware is_active flag.

Phase 3c.7: routes that render the `.gc-shell` layout (Home/`/`, Dashboard,
Clusters, Sources) all need the same sidebar nav. Centralizing the nav
definition here keeps a single source of truth.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlmodel import Session, select
from starlette.requests import Request

from app.db.models import RunLog, Source

# (id, label, icon, route_name) — `route_name` is the FastAPI route name used
# with request.url_for(...) so links resolve correctly under a path prefix
# (e.g. Tailscale Funnel mounted at /gaming-chatter).
NAV_ITEMS_BASE = [
    {"id": "weekly",    "label": "Weekly read-out", "icon": "newspaper", "route": "reports_view"},
    {"id": "stories",   "label": "Stories",         "icon": "list",      "route": "dashboard"},
    {"id": "clusters",  "label": "Clusters",        "icon": "shapes",    "route": "clusters_view"},
    {"id": "sentiment", "label": "Sentiment",       "icon": "activity",  "route": "sentiment_view"},
    {"id": "sources",   "label": "Sources",         "icon": "rss",       "route": "list_sources"},
    {"id": "runs",      "label": "Runs",            "icon": "gauge",     "route": "runs_view"},
    {"id": "about",     "label": "About",           "icon": "info",      "route": "about"},
]

# Phase 3c.26 — `/eval` is rendered separately at the bottom of the sidebar
# nav (boundary'd button, not a peer of the main nav items). Listed here so
# the boot-time route validator still catches a missing/renamed eval_view.
EXTRA_NAV_ROUTES = ["eval_view"]

# Source health is driven by RunLog RECENCY, not the cumulative, never-decaying
# Source.error_count (which kept flagging sources that had already recovered —
# see DECISIONS 2026-06-09). SOURCE_VOLUME_WINDOW_DAYS is the "produced anything
# lately?" window — 14d (not 7) so a legitimately low-volume source like VG247
# (now ~weekly, an IGN brand) isn't flagged "silent" on a normal quiet stretch;
# only a sustained 2-week drought trips it. _LATEST_WINDOW_DAYS is how far back
# we look for a source's most recent ingest attempt before calling it idle.
SOURCE_VOLUME_WINDOW_DAYS = 14
_SOURCE_LATEST_WINDOW_DAYS = 30

# Verdicts the alert banner + /runs grid treat as "needs attention".
_UNHEALTHY_VERDICTS = {"error", "silent"}

# Stable sort order for the grid — problems first.
_VERDICT_ORDER = {"error": 0, "silent": 1, "ok": 2, "idle": 3, "disabled": 4}


def source_health(session: Session) -> list[dict]:
    """Per-source ingest health from RunLog recency. One dict per source.

    The single source of truth shared by `failing_sources_count()` (the alert
    banner) and the /runs source-health grid. Verdicts:

      disabled — Source.enabled is False
      error    — the source's most recent ingest attempt failed (status='error')
      silent   — it ran during the volume window but produced 0 new items
                 across the whole window (the "feed fetches but extracts
                 nothing" silent death — the "all green yet <1000 mentions" case)
      idle     — no ingest run within the latest window (unknown; e.g. scheduler
                 off and never manually triggered) — NOT counted as failing
      ok       — ran recently and produced items
    """
    now = datetime.utcnow()
    vol_cutoff = now - timedelta(days=SOURCE_VOLUME_WINDOW_DAYS)
    latest_cutoff = now - timedelta(days=_SOURCE_LATEST_WINDOW_DAYS)

    sources = session.exec(select(Source).order_by(Source.name)).all()

    # Pull recent per-source ingest RunLogs once and reduce in Python — cheaper
    # than a correlated subquery per source, and small (≈ sources × days rows).
    runs = session.exec(
        select(RunLog)
        .where(RunLog.job_type == "ingest")
        .where(RunLog.source_id.is_not(None))
        .where(RunLog.started_at > latest_cutoff)
        .order_by(RunLog.started_at.desc())
    ).all()

    latest_by_src: dict[int, RunLog] = {}
    runs_window: dict[int, int] = {}
    items_window: dict[int, int] = {}
    for r in runs:
        sid = r.source_id
        if sid not in latest_by_src:          # desc order => first seen is newest
            latest_by_src[sid] = r
        if r.started_at > vol_cutoff:
            runs_window[sid] = runs_window.get(sid, 0) + 1
            items_window[sid] = items_window.get(sid, 0) + (r.items_processed or 0)

    out: list[dict] = []
    for s in sources:
        latest = latest_by_src.get(s.id)
        rw = runs_window.get(s.id, 0)
        iw = items_window.get(s.id, 0)
        if not s.enabled:
            verdict = "disabled"
        elif latest is None:
            verdict = "idle"
        elif latest.status == "error":
            verdict = "error"
        elif rw > 0 and iw == 0:
            verdict = "silent"
        else:
            verdict = "ok"
        out.append({
            "id": s.id,
            "name": s.name,
            "type": s.type,
            "verdict": verdict,
            "last_status": latest.status if latest else None,
            "last_started_at": latest.started_at if latest else None,
            "last_items": latest.items_processed if latest else None,
            "items_window": iw,
            "runs_window": rw,
            "last_error": (latest.error if latest and latest.status == "error" else None) or s.last_error,
        })
    out.sort(key=lambda h: (_VERDICT_ORDER.get(h["verdict"], 9), h["name"].lower()))
    return out


def failing_sources_count(session: Session) -> int:
    """Number of sources currently unhealthy by RECENCY — most recent ingest
    errored, or ran all week yet produced nothing. Replaces the old cumulative
    `error_count > 3` rule (never decayed → cried wolf on recovered sources).

    Used by the alert banner partial (`_alert_banner.html`) on every full-page
    render. Returns 0 when all sources are healthy — the partial then renders
    nothing.
    """
    return sum(
        1 for h in source_health(session) if h["verdict"] in _UNHEALTHY_VERDICTS
    )


def nav_items_for(request: Request, active_id: str) -> list[dict]:
    """Return the nav list with hrefs resolved via request.url_for and
    is_active set on the matching item."""
    return [
        {
            "id": n["id"],
            "label": n["label"],
            "icon": n["icon"],
            "href": str(request.url_for(n["route"])),
            "is_active": n["id"] == active_id,
        }
        for n in NAV_ITEMS_BASE
    ]
