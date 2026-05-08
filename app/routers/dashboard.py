from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, col, select

from app.config import TEMPLATES_DIR
from app.db.models import Enrichment, Item, Source
from app.db.session import get_session

router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/")
def dashboard(request: Request, session: Session = Depends(get_session)):
    items = session.exec(
        select(Item).order_by(Item.published_at.desc().nullslast()).limit(50)
    ).all()
    sources_by_id = {
        s.id: s for s in session.exec(select(Source)).all()
    }
    item_ids = [it.id for it in items if it.id is not None]
    enrichments_by_item: dict[int, Enrichment] = {}
    if item_ids:
        rows = session.exec(
            select(Enrichment).where(col(Enrichment.item_id).in_(item_ids))
        ).all()
        enrichments_by_item = {e.item_id: e for e in rows}
    pending_count = session.exec(
        select(Item.id).where(
            col(Item.id).not_in(select(Enrichment.item_id))
        )
    ).all()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "items": items,
            "sources_by_id": sources_by_id,
            "enrichments_by_item": enrichments_by_item,
            "pending_count": len(pending_count),
        },
    )
