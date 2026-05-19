"""GET /clusters — cluster inspection view with live HTMX search.

Phase 3c.7 — re-skinned to shell_base.html and gained a `?q=` filter that
matches against cluster.label (case-insensitive).
Phase 3c.10 — editorial-section overlay: each cluster gets a chip showing
where it landed in the weekly synthesis (Biggest / MM / Risks / Community /
Esports / Drama / Watch / Not surfaced), and a `?section=` dropdown filter.
Phase 3c.11 — section helpers extracted to `app/services/sections.py`;
added a `?week_id=` dropdown alongside section + search.
Phase 3c.17 — week_id dropdown replaced with `?from=YYYY-MM-DD&to=YYYY-MM-DD`
date-range picker. Cluster filter semantic: include cluster if ANY member
item's published_at falls in the picked range. `?week_id=` still parsed as a
back-compat shim for /reports footer links.
"""
import json
from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, col, select

from app.config import TEMPLATES_DIR
from app.db.models import Cluster, Item, Source
from app.db.session import get_session
from app.services.chrome import failing_sources_count, nav_items_for
from app.services.cluster import cluster_window
from app.services.reports import parse_date_range
from app.services.sections import (
    SECTION_OPTIONS,
    cluster_regions,
    clusters_with_items_in_range,
    load_synthesis_section_map,
    section_label_for,
)

router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

_DEFAULT_WINDOW_DAYS = 30

_REGION_ALLOWED = {"americas", "europe", "asia"}


def _source_kind(s: Source) -> str:
    if s.type == "youtube":
        return "youtube"
    if "reddit.com" in (s.url_or_handle or "") or s.name.startswith("r/"):
        return "subreddit"
    return "outlet"


def _build_clusters_context(
    session: Session,
    date_range: dict,
    q: str,
    section: str,
    region: str,
) -> dict:
    """Run the clusters query and enrich members.

    Date-range filter: a cluster appears if ANY of its member items has a
    `published_at` in [date_range.start, date_range.end). Computed via
    `clusters_with_items_in_range` (sections.py).
    """
    in_range_ids = clusters_with_items_in_range(
        session, date_range["start"], date_range["end"]
    )

    stmt = (
        select(Cluster)
        .where(Cluster.week_id != "all")
        .order_by(Cluster.score.desc().nulls_last(), Cluster.member_count.desc())
    )
    if in_range_ids:
        stmt = stmt.where(col(Cluster.id).in_(list(in_range_ids)))
    else:
        # Empty intersection → no clusters in range. Short-circuit to empty
        # result while keeping the rest of the pipeline running (so the
        # template still renders region tabs, view toggle, etc.).
        stmt = stmt.where(Cluster.id == -1)
    if q:
        stmt = stmt.where(Cluster.label.ilike(f"%{q.strip()}%"))

    clusters_rows = session.exec(stmt).all()

    all_member_ids: set[int] = set()
    cluster_member_ids: list[list[int]] = []
    for c in clusters_rows:
        try:
            ids = json.loads(c.member_item_ids or "[]")
        except json.JSONDecodeError:
            ids = []
        cluster_member_ids.append(ids)
        all_member_ids.update(ids)

    items_by_id: dict[int, Item] = {}
    sources_by_id: dict[int, dict] = {}
    if all_member_ids:
        items = session.exec(
            select(Item).where(col(Item.id).in_(list(all_member_ids)))
        ).all()
        items_by_id = {it.id: it for it in items if it.id is not None}
        source_ids = {it.source_id for it in items}
        if source_ids:
            sources = session.exec(
                select(Source).where(col(Source.id).in_(list(source_ids)))
            ).all()
            sources_by_id = {
                s.id: {"name": s.name, "kind": _source_kind(s)}
                for s in sources if s.id is not None
            }

    # Section overlay for the weeks represented in the result set.
    weeks_in_result = {c.week_id for c in clusters_rows if c.week_id and c.week_id != "all"}
    section_map = load_synthesis_section_map(session, list(weeks_in_result))

    # Region overlay — only when a region filter is active.
    region_map: dict[int, set[str]] = {}
    if region in _REGION_ALLOWED:
        region_map = cluster_regions(
            session, [c.id for c in clusters_rows if c.id is not None]
        )

    enriched = []
    for c, member_ids in zip(clusters_rows, cluster_member_ids):
        cluster_sections = section_map.get(c.id, [])
        if section:
            if section == "not_surfaced":
                if cluster_sections:
                    continue
            else:
                if not any(s["section"] == section for s in cluster_sections):
                    continue
        if region in _REGION_ALLOWED:
            if region not in region_map.get(c.id, set()):
                continue
        members = []
        seen_sources: set[int] = set()
        for iid in member_ids:
            it = items_by_id.get(iid)
            if it is None:
                continue
            members.append(it)
            seen_sources.add(it.source_id)
        members.sort(key=lambda it: it.published_at or it.id, reverse=True)
        enriched.append({
            "cluster": c,
            "members": members,
            "source_count": len(seen_sources),
            "sections": cluster_sections,
        })

    return {
        "clusters": enriched,
        "sources_by_id": sources_by_id,
        "q": q,
        "section": section,
        "section_label": section_label_for(section),
        "section_options": SECTION_OPTIONS,
        "region": region,
        "date_range": date_range,
    }


def _preset_links(now: datetime | None = None) -> list[dict]:
    """Date-range presets — mirrors dashboard router (same shape)."""
    now = now or datetime.utcnow()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    fmt = "%Y-%m-%d"
    this_monday = today - timedelta(days=today.isoweekday() - 1)
    return [
        {"label": "Last 7d",
         "from": (today - timedelta(days=6)).strftime(fmt),
         "to":   today.strftime(fmt)},
        {"label": "Last 30d",
         "from": (today - timedelta(days=29)).strftime(fmt),
         "to":   today.strftime(fmt)},
        {"label": "This week",
         "from": this_monday.strftime(fmt),
         "to":   today.strftime(fmt)},
        {"label": "All time",
         "from": "2020-01-01",
         "to":   today.strftime(fmt)},
    ]


@router.post("/clusters/run")
def clusters_run(
    request: Request,
    bg: BackgroundTasks,
    week_id: str = "all",
    sync: bool = False,
):
    if sync:
        return JSONResponse(cluster_window(week_id=week_id))
    bg.add_task(cluster_window, week_id=week_id)
    return RedirectResponse(
        f"{request.url_for('clusters_view')}?week_id={week_id}",
        status_code=303,
    )


@router.get("/clusters")
def clusters_view(
    request: Request,
    week_id: str = "",   # back-compat shim for /reports footer links predating 3c.17
    q: str = "",
    section: str = "",
    region: str = "",
    from_: str = Query("", alias="from"),
    to: str = "",
    session: Session = Depends(get_session),
):
    """Clusters list — full page or HTMX fragment."""
    date_range = parse_date_range(from_, to, week_id, _DEFAULT_WINDOW_DAYS)
    region_norm = region if region in _REGION_ALLOWED else ""
    ctx = _build_clusters_context(session, date_range, q, section, region_norm)

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request, "_clusters_list.html", ctx)

    ctx.update({
        "nav_items": nav_items_for(request, "clusters"),
        "total_count": len(ctx["clusters"]),
        "presets": _preset_links(),
        "failing_sources_count": failing_sources_count(session),
    })
    return templates.TemplateResponse(request, "clusters.html", ctx)
