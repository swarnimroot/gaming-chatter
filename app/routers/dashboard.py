"""GET /dashboard — raw items table with live HTMX search.

Phase 3c.7 — moved from `/` to `/dashboard` (the weekly read-out claimed `/`),
re-skinned to extend `shell_base.html`, and gained a `?q=` text filter that
matches against item title / TLDR / source name.
"""
from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_
from sqlmodel import Session, col, select

from app.config import TEMPLATES_DIR
from app.db.models import Enrichment, Item, Source
from app.db.session import get_session
from app.services.chrome import nav_items_for
from app.services.reports import corpus_stats

router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

_ITEM_LIMIT = 50


def _source_kind(s: Source) -> str:
    """Derive a pill kind from the source row — same rule as reports.py."""
    if s.type == "youtube":
        return "youtube"
    if "reddit.com" in (s.url_or_handle or "") or s.name.startswith("r/"):
        return "subreddit"
    return "outlet"


def _build_list_context(session: Session, q: str) -> dict:
    """Run the query (optionally filtered by q) and prepare list context."""
    stmt = select(Item).order_by(Item.published_at.desc().nullslast())

    if q:
        pattern = f"%{q.strip()}%"
        # Filter items by title or TLDR (via enrichment join) or source.name.
        # SQLite LIKE is case-insensitive by default for ASCII, which is fine
        # for an internal admin search.
        matching_enr_ids = select(Enrichment.item_id).where(Enrichment.tldr.ilike(pattern))
        matching_src_ids = select(Source.id).where(Source.name.ilike(pattern))
        stmt = stmt.where(
            or_(
                Item.title.ilike(pattern),
                col(Item.id).in_(matching_enr_ids),
                col(Item.source_id).in_(matching_src_ids),
            )
        )

    items = session.exec(stmt.limit(_ITEM_LIMIT)).all()
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
    }


@router.get("/dashboard")
def dashboard(
    request: Request,
    q: str = "",
    session: Session = Depends(get_session),
):
    """Raw items table — full page, or fragment for HTMX live-search swap."""
    ctx = _build_list_context(session, q)

    # HTMX live-search returns just the list fragment.
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request, "_dashboard_list.html", ctx)

    # Full page render needs chrome context (sidebar, header counters).
    total_count = session.exec(select(Item.id)).all()
    pending_count = session.exec(
        select(Item.id).where(col(Item.id).not_in(select(Enrichment.item_id)))
    ).all()

    ctx.update({
        "nav_items": nav_items_for("dashboard"),
        "corpus_stats": corpus_stats(session),
        "total_count": len(total_count),
        "pending_count": len(pending_count),
    })
    return templates.TemplateResponse(request, "dashboard.html", ctx)
