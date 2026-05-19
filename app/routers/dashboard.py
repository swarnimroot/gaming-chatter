"""GET /stories — Stories: raw items with live HTMX search + date-range/section/region filters.

Phase 3c.7 — moved from `/` to `/dashboard`, re-skinned to `shell_base.html`,
gained `?q=` text filter.
Phase 3c.9 — renamed to "Stories" in the UI; results now scoped to items
published in the trailing 7 days (no row cap, all matching items render).
Phase 3c.10 — URL renamed `/dashboard` → `/stories` to match the nav label.
Phase 3c.11 — added `?week_id=` and `?section=` dropdown filters matching the
clusters page. Defaults: week_id="" → last 7 days; section="" → no filter.
Phase 3c.17 — week_id dropdown replaced with `?from=YYYY-MM-DD&to=YYYY-MM-DD`
date-range picker (flatpickr). `?week_id=` still parsed as a back-compat shim
for /reports footer links.
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_
from sqlmodel import Session, col, select

from app.config import TEMPLATES_DIR
from app.db.models import Enrichment, Item, Source
from app.db.session import get_session
from app.services.chrome import failing_sources_count, nav_items_for
from app.services.reports import available_weeks, parse_date_range
from app.services.sections import (
    SECTION_OPTIONS,
    items_in_section,
    section_label_for,
)

router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

_DEFAULT_WINDOW_DAYS = 7

_REGION_ALLOWED = {"americas", "europe", "asia"}


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
    date_range: dict,
    section: str,
    region: str,
) -> dict:
    """Build the items-list context. Filters applied in order:
       1. published_at window (from date_range — defaults to last 7 days)
       2. section (item belongs to a cluster in the requested editorial section)
       3. region (item's enrichment.region_focus contains the requested tag)
       4. q (title/TLDR/source.name ILIKE)"""

    start, end = date_range["start"], date_range["end"]

    stmt = (
        select(Item)
        .where(Item.published_at >= start, Item.published_at < end)
        .order_by(Item.published_at.desc().nullslast())
    )

    # 2. Section filter.
    if section:
        wk_ids = available_weeks(session)
        section_item_ids = items_in_section(session, wk_ids, section)
        if section_item_ids is None or len(section_item_ids) == 0:
            return {
                "items": [],
                "sources_by_id": {},
                "enrichments_by_item": {},
                "q": q,
                "section": section,
                "region": region,
                "date_range": date_range,
            }
        stmt = stmt.where(col(Item.id).in_(list(section_item_ids)))

    # 3. Region filter — strict tag match against Enrichment.region_focus.
    if region in _REGION_ALLOWED:
        region_item_ids = select(Enrichment.item_id).where(
            Enrichment.region_focus.ilike(f"%{region}%")
        )
        stmt = stmt.where(col(Item.id).in_(region_item_ids))

    # 4. Text search.
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
        "section": section,
        "region": region,
        "date_range": date_range,
    }


def _preset_links(now: datetime | None = None) -> list[dict]:
    """Server-rendered date-range presets. Each item: {label, from, to} as
    'YYYY-MM-DD' strings. Template emits them as buttons that pop into the
    hidden from/to inputs and fire the HTMX swap via a custom event."""
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


@router.get("/stories")
def dashboard(
    request: Request,
    q: str = "",
    week_id: str = "",   # back-compat shim for /reports footer links predating 3c.17
    section: str = "",
    region: str = "",
    from_: str = Query("", alias="from"),
    to: str = "",
    session: Session = Depends(get_session),
):
    """Stories list — full page, or fragment for HTMX live-search swap."""
    date_range = parse_date_range(from_, to, week_id, _DEFAULT_WINDOW_DAYS)
    region_norm = region if region in _REGION_ALLOWED else ""
    ctx = _build_list_context(session, q, date_range, section, region_norm)

    # HTMX live-search returns just the list fragment.
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request, "_dashboard_list.html", ctx)

    ctx.update({
        "nav_items": nav_items_for(request, "stories"),
        "total_count": len(ctx["items"]),
        "section_options": SECTION_OPTIONS,
        "section_label": section_label_for(section),
        "presets": _preset_links(),
        "failing_sources_count": failing_sources_count(session),
    })
    return templates.TemplateResponse(request, "dashboard.html", ctx)
