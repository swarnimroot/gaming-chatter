"""GET /about — visual end-to-end pipeline explainer.

Beginner-friendly walkthrough of how Gaming Chatter goes from scraping news
sources to producing the weekly briefing. Rendered as a 5-stage infographic
plus a glossary, all on a single page (no scroll-death).
"""
from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from app.config import TEMPLATES_DIR
from app.services.chrome import nav_items_for

router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/about")
def about(request: Request):
    return templates.TemplateResponse(
        request, "about.html",
        {"nav_items": nav_items_for(request, "about")},
    )
