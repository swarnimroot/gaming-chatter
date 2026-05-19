"""GET /clusters — cluster inspection view with live HTMX search.

Phase 3c.7 — re-skinned to shell_base.html and gained a `?q=` filter that
matches against cluster.label (case-insensitive).
Phase 3c.10 — editorial-section overlay: each cluster gets a chip showing
where it landed in the weekly synthesis (Biggest / MM / Risks / Community /
Esports / Drama / Watch / Not surfaced), and a `?section=` dropdown filter.
Phase 3c.11 — section helpers extracted to `app/services/sections.py`;
added a `?week_id=` dropdown alongside section + search.
"""
import json

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, col, select

from app.config import TEMPLATES_DIR
from app.db.models import Cluster, Item, Source
from app.db.session import get_session
from app.services.chrome import nav_items_for
from app.services.cluster import cluster_window
from app.services.reports import available_weeks
from app.services.sections import (
    SECTION_OPTIONS,
    cluster_regions,
    load_synthesis_section_map,
    section_label_for,
)

router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

_REGION_ALLOWED = {"americas", "europe", "asia"}


def _source_kind(s: Source) -> str:
    if s.type == "youtube":
        return "youtube"
    if "reddit.com" in (s.url_or_handle or "") or s.name.startswith("r/"):
        return "subreddit"
    return "outlet"


def _build_clusters_context(session: Session, week_id: str, q: str, section: str, region: str) -> dict:
    """Run the clusters query (optionally filtered by q) and enrich members.

    Default (empty week_id): show per-ISO-week clusters from every week, ordered
    by score desc — excludes the legacy `week_id='all'` partition. Explicit
    `?week_id=all` still works for opting in to the legacy set.
    """
    stmt = (
        select(Cluster)
        .order_by(Cluster.score.desc().nulls_last(), Cluster.member_count.desc())
    )
    if week_id:
        stmt = stmt.where(Cluster.week_id == week_id)
    else:
        stmt = stmt.where(Cluster.week_id != "all")
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

    # Build section overlay for the weeks represented in the result set.
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
        cluster_sections = section_map.get(c.id, [])  # list (possibly empty)
        # Apply section filter — match if ANY of the cluster's sections matches.
        if section:
            if section == "not_surfaced":
                if cluster_sections:
                    continue
            else:
                if not any(s["section"] == section for s in cluster_sections):
                    continue
        # Apply region filter — cluster appears if ANY member carries that tag.
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

    # Week dropdown: "All weeks" + each non-legacy week_id with clusters.
    wk_ids = available_weeks(session)
    week_options = [("", "All weeks")] + [(w, w) for w in wk_ids]

    return {
        "clusters": enriched,
        "sources_by_id": sources_by_id,
        "week_id": week_id,
        "q": q,
        "section": section,
        "section_label": section_label_for(section),
        "section_options": SECTION_OPTIONS,
        "week_options": week_options,
        "region": region,
    }


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
    week_id: str = "",
    q: str = "",
    section: str = "",
    region: str = "",
    session: Session = Depends(get_session),
):
    """Clusters list — full page or HTMX fragment."""
    region_norm = region if region in _REGION_ALLOWED else ""
    ctx = _build_clusters_context(session, week_id, q, section, region_norm)

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request, "_clusters_list.html", ctx)

    ctx.update({
        "nav_items": nav_items_for(request, "clusters"),
        "total_count": len(ctx["clusters"]),
    })
    return templates.TemplateResponse(request, "clusters.html", ctx)
