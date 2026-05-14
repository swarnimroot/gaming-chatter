"""GET /stories — Stories: raw items with live HTMX search + week/section filters.

Phase 3c.7 — moved from `/` to `/dashboard`, re-skinned to `shell_base.html`,
gained `?q=` text filter.
Phase 3c.9 — renamed to "Stories" in the UI; results now scoped to items
published in the trailing 7 days (no row cap, all matching items render).
Phase 3c.10 — URL renamed `/dashboard` → `/stories` to match the nav label.
Phase 3c.11 — added `?week_id=` and `?section=` dropdown filters matching the
clusters page. Defaults: week_id="" → last 7 days; section="" → no filter.
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_
from sqlmodel import Session, col, select

from app.config import TEMPLATES_DIR
from app.db.models import Enrichment, Item, Source
from app.db.session import get_session
from app.services.chrome import nav_items_for
from app.services.reports import available_weeks, iso_week_bounds
from app.services.sections import (
    SECTION_OPTIONS,
    items_in_section,
    section_label_for,
)

router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

_WINDOW_DAYS = 7


def _source_kind(s: Source) -> str:
    """Derive a pill kind from the source row — same rule as reports.py."""
    if s.type == "youtube":
        return "youtube"
    if "reddit.com" in (s.url_or_handle or "") or s.name.startswith("r/"):
        return "subreddit"
    return "outlet"


def _build_list_context(
    session: Session,
    q: str,
    week_id: str,
    section: str,
) -> dict:
    """Build the items-list context. Filters applied in order:
       1. published_at window (week_id or last-7-days default)
       2. section (item belongs to a cluster in the requested editorial section)
       3. q (title/TLDR/source.name ILIKE)"""

    # 1. Time window.
    if week_id:
        try:
            start, end = iso_week_bounds(week_id)
        except (ValueError, IndexError):
            # Invalid week id — fall back to last 7 days.
            start = datetime.utcnow() - timedelta(days=_WINDOW_DAYS)
            end = None
            week_id = ""  # signal back to template that the filter was ignored
    else:
        start = datetime.utcnow() - timedelta(days=_WINDOW_DAYS)
        end = None

    stmt = (
        select(Item)
        .where(Item.published_at >= start)
        .order_by(Item.published_at.desc().nullslast())
    )
    if end is not None:
        stmt = stmt.where(Item.published_at < end)

    # 2. Section filter.
    if section:
        wk_ids = available_weeks(session)
        section_item_ids = items_in_section(session, wk_ids, section)
        if section_item_ids is None or len(section_item_ids) == 0:
            # No items match this section.
            return {
                "items": [],
                "sources_by_id": {},
                "enrichments_by_item": {},
                "q": q,
                "week_id": week_id,
                "section": section,
            }
        stmt = stmt.where(col(Item.id).in_(list(section_item_ids)))

    # 3. Text search.
    if q:
        pattern = f"%{q.strip()}%"
        matching_enr_ids = select(Enrichment.item_id).where(Enrichment.tldr.ilike(pattern))
        matching_src_ids = select(Source.id).where(Source.name.ilike(pattern))
        stmt = stmt.where(
            or_(
                Item.title.ilike(pattern),
                col(Item.id).in_(matching_enr_ids),
                col(Item.source_id).in_(matching_src_ids),
            )
        )

    items = session.exec(stmt).all()
    sources_rows = session.exec(select(Source)).all()
    sources_by_id = {
        s.id: {"name": s.name, "kind": _source_kind(s)}
        for s in sources_rows if s.id is not None
    }

    item_ids = [it.id for it in items if it.id is not None]
    enrichments_by_item: dict[int, Enrichment] = {}
    if item_ids:
        rows = session.exec(
            select(Enrichment).where(col(Enrichment.item_id).in_(item_ids))
        ).all()
        enrichments_by_item = {e.item_id: e for e in rows}

    return {
        "items": items,
        "sources_by_id": sources_by_id,
        "enrichments_by_item": enrichments_by_item,
        "q": q,
        "week_id": week_id,
        "section": section,
    }


@router.get("/stories")
def dashboard(
    request: Request,
    q: str = "",
    week_id: str = "",
    section: str = "",
    session: Session = Depends(get_session),
):
    """Stories list — full page, or fragment for HTMX live-search swap."""
    ctx = _build_list_context(session, q, week_id, section)

    # HTMX live-search returns just the list fragment.
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request, "_dashboard_list.html", ctx)

    # Dropdown options.
    wk_ids = available_weeks(session)
    week_options = [("", f"Last {_WINDOW_DAYS} days")] + [(w, w) for w in wk_ids]

    ctx.update({
        "nav_items": nav_items_for("stories"),
        "total_count": len(ctx["items"]),
        "window_days": _WINDOW_DAYS,
        "section_options": SECTION_OPTIONS,
        "section_label": section_label_for(section),
        "week_options": week_options,
    })
    return templates.TemplateResponse(request, "dashboard.html", ctx)
