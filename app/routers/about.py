"""GET /about — visual end-to-end pipeline explainer.

Beginner-friendly walkthrough of how Gaming Chatter goes from scraping news
sources to producing the weekly briefing. Rendered as a 5-stage infographic
plus a glossary, all on a single page (no scroll-death).
"""
from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from app.config import TEMPLATES_DIR
from app.db.session import get_session
from app.services.chrome import failing_sources_count, nav_items_for

router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/about")
def about(request: Request, session: Session = Depends(get_session)):
    return templates.TemplateResponse(
        request, "about.html",
        {
            "nav_items": nav_items_for(request, "about"),
            "failing_sources_count": failing_sources_count(session),
        },
    )
