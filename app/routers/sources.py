from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.config import TEMPLATES_DIR
from app.db.models import Source
from app.db.session import get_session
from app.services.enrich import enrich_pending
from app.services.ingest import ingest_all, ingest_source

router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/sources")
def list_sources(request: Request, session: Session = Depends(get_session)):
    rows = session.exec(select(Source).order_by(Source.type, Source.name)).all()
    return templates.TemplateResponse(
        request,
        "sources.html",
        {"sources": rows},
    )


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
