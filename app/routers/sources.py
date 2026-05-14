from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_
from sqlmodel import Session, select

from app.config import TEMPLATES_DIR
from app.db.models import Source
from app.db.session import get_session
from app.services.chrome import nav_items_for
from app.services.enrich import enrich_pending
from app.services.ingest import ingest_all, ingest_source

router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _source_kind(s: Source) -> str:
    if s.type == "youtube":
        return "youtube"
    if "reddit.com" in (s.url_or_handle or "") or s.name.startswith("r/"):
        return "subreddit"
    return "outlet"


def _build_sources_context(session: Session, q: str) -> dict:
    """Run the sources query (optionally filtered by q) and shape for template."""
    stmt = select(Source).order_by(Source.type, Source.name)
    if q:
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(Source.name.ilike(pattern), Source.url_or_handle.ilike(pattern))
        )
    rows = session.exec(stmt).all()
    sources = [
        {
            "id": s.id,
            "name": s.name,
            "type": s.type,
            "url_or_handle": s.url_or_handle,
            "enabled": s.enabled,
            "last_fetched_at": s.last_fetched_at,
            "error_count": s.error_count,
            "last_error": s.last_error,
            "kind": _source_kind(s),
        }
        for s in rows
    ]
    return {"sources": sources, "q": q}


@router.get("/sources")
def list_sources(
    request: Request,
    q: str = "",
    session: Session = Depends(get_session),
):
    ctx = _build_sources_context(session, q)

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request, "_sources_list.html", ctx)

    # Full-table count (unfiltered) for the header meta line.
    all_rows = session.exec(select(Source)).all()
    ctx.update({
        "nav_items": nav_items_for("sources"),
        "total_count": len(all_rows),
        "enabled_count": sum(1 for s in all_rows if s.enabled),
    })
    return templates.TemplateResponse(request, "sources.html", ctx)


@router.post("/sources/{source_id}/ingest")
def ingest_one(
    source_id: int,
    session: Session = Depends(get_session),
):
    source = session.get(Source, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="source not found")
    ingest_source(session, source)
    return RedirectResponse("/sources", status_code=303)


@router.post("/sources/ingest-all")
def ingest_all_route(bg: BackgroundTasks):
    bg.add_task(ingest_all)
    bg.add_task(enrich_pending)
    return RedirectResponse("/sources", status_code=303)
