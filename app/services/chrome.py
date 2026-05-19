"""Shared shell chrome — nav items + path-aware is_active flag.

Phase 3c.7: routes that render the `.gc-shell` layout (Home/`/`, Dashboard,
Clusters, Sources) all need the same sidebar nav. Centralizing the nav
definition here keeps a single source of truth.
"""
from __future__ import annotations

from sqlalchemy import func
from sqlmodel import Session, select
from starlette.requests import Request

from app.db.models import Source

# (id, label, icon, route_name) — `route_name` is the FastAPI route name used
# with request.url_for(...) so links resolve correctly under a path prefix
# (e.g. Tailscale Funnel mounted at /gaming-chatter).
NAV_ITEMS_BASE = [
    {"id": "weekly",    "label": "Weekly read-out", "icon": "newspaper", "route": "reports_view"},
    {"id": "stories",   "label": "Stories",         "icon": "list",      "route": "dashboard"},
    {"id": "clusters",  "label": "Clusters",        "icon": "shapes",    "route": "clusters_view"},
    {"id": "sources",   "label": "Sources",         "icon": "rss",       "route": "list_sources"},
    {"id": "about",     "label": "About",           "icon": "info",      "route": "about"},
]

# Phase 3c.19 — source-failure UI banner threshold. A source is considered
# "erroring" once `Source.error_count > 3`; the alert banner at the top of
# every full-page render counts these and links to /sources.
FAILING_SOURCE_ERROR_THRESHOLD = 3


def failing_sources_count(session: Session) -> int:
    """Return the number of sources with error_count above the threshold.

    Used by the alert banner partial (`_alert_banner.html`) included in
    `shell_base.html` and `reports.html`. Returns 0 when the table is empty
    or all sources are healthy — the partial renders nothing in that case.
    """
    stmt = select(func.count(Source.id)).where(
        Source.error_count > FAILING_SOURCE_ERROR_THRESHOLD
    )
    result = session.exec(stmt).first()
    if result is None:
        return 0
    # SQLModel's exec on a select(func.count(...)) returns a scalar int directly.
    return int(result or 0)


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
