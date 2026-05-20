import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from app.config import STATIC_DIR
from app.db.init import init_db
from app.routers import about, clusters, dashboard, enrich, eval as eval_router, pipeline, reports, sentiment, sources

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app_: FastAPI):
    init_db()
    # Fail-fast nav validator: every route name in NAV_ITEMS_BASE must resolve,
    # so renaming a router function without updating chrome.py crashes at boot
    # rather than 500-ing later at first nav render.
    from app.services.chrome import EXTRA_NAV_ROUTES, NAV_ITEMS_BASE
    missing = []
    for item in NAV_ITEMS_BASE:
        try:
            app_.url_path_for(item["route"])
        except Exception:
            missing.append(item["route"])
    for route in EXTRA_NAV_ROUTES:
        try:
            app_.url_path_for(route)
        except Exception:
            missing.append(route)
    if missing:
        raise RuntimeError(
            f"Nav routes not registered: {missing!r}. "
            f"Check NAV_ITEMS_BASE / EXTRA_NAV_ROUTES in app/services/chrome.py vs router function names."
        )
    yield


app = FastAPI(title="gaming-chatter", lifespan=lifespan, root_path=os.getenv("GC_ROOT_PATH", ""))


# Static files as a regular route, not app.mount().
#
# DO NOT add app.mount(...) calls while root_path is set. Starlette's Mount
# sets the child scope's root_path to outer_root_path + mount_path. Any sub-app
# that strips its own root_path from incoming paths (StaticFiles included) then
# breaks for proxy-stripped requests: the strip is a no-op and the sub-app
# resolves the wrong location. Use FastAPI routes instead. See DECISIONS
# 2026-05-15 for the full rationale.
#
# name="static" keeps {{ request.url_for('static', path=…) }} working unchanged.
_STATIC_ROOT = STATIC_DIR.resolve()


@app.get("/static/{path:path}", name="static", include_in_schema=False)
def serve_static(path: str):
    target = (STATIC_DIR / path).resolve()
    if not str(target).startswith(str(_STATIC_ROOT)):
        raise HTTPException(404)
    if not target.is_file():
        raise HTTPException(404)
    return FileResponse(target)


app.include_router(dashboard.router)
app.include_router(sources.router)
app.include_router(enrich.router)
app.include_router(clusters.router)
app.include_router(reports.router)
app.include_router(about.router)
app.include_router(pipeline.router)
app.include_router(sentiment.router)
app.include_router(eval_router.router)
