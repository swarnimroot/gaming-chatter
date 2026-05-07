from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.config import TEMPLATES_DIR
from app.db.models import Item, Source
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
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"items": items, "sources_by_id": sources_by_id},
    )
