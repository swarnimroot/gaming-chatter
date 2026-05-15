from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.services.enrich import embed_pending, enrich_pending

router = APIRouter()


@router.post("/enrich/pending")
def enrich_pending_route(
    request: Request,
    bg: BackgroundTasks,
    limit: Optional[int] = None,
    retry_failed: bool = False,
    sync: bool = False,
):
    """Enrich items lacking an Enrichment row.

    sync=true blocks and returns counts (used for the sanity gate).
    Otherwise queues a background task and redirects to dashboard.
    """
    if sync:
        return JSONResponse(enrich_pending(limit=limit, retry_failed=retry_failed))
    bg.add_task(enrich_pending, limit=limit, retry_failed=retry_failed)
    return RedirectResponse(request.url_for("reports_view"), status_code=303)


@router.post("/embed/pending")
def embed_pending_route(
    request: Request,
    bg: BackgroundTasks,
    limit: Optional[int] = None,
    sync: bool = False,
):
    if sync:
        return JSONResponse(embed_pending(limit=limit))
    bg.add_task(embed_pending, limit=limit)
    return RedirectResponse(request.url_for("reports_view"), status_code=303)
