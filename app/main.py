import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import STATIC_DIR
from app.db.init import init_db
from app.routers import about, clusters, dashboard, enrich, pipeline, reports, sources

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="gaming-chatter", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(dashboard.router)
app.include_router(sources.router)
app.include_router(enrich.router)
app.include_router(clusters.router)
app.include_router(reports.router)
app.include_router(about.router)
app.include_router(pipeline.router)
