"""FastAPI entry point for the DD Report Generator."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config import CORS_ORIGINS
from db import init_db
from services.task_manager import task_manager
from routers import report, settings, tasks
from routers.auth_router import router as auth_router
from routers.tools import router as tools_router
from routers.intake import router as intake_router

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Startup: initialize database.
    init_db()
    repaired = await task_manager.mark_abandoned_intake_tasks_failed()
    if repaired:
        log.warning("Marked %s abandoned intake tasks as failed during startup", repaired)

    yield

    # Shutdown: cleanup if needed
    log.info("Shutting down...")


app = FastAPI(title="DD Report Generator", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(report.router, prefix="/api/report", tags=["report"])
app.include_router(settings.router, prefix="/api/settings", tags=["settings"])
app.include_router(tools_router, prefix="/api/tools", tags=["tools"])
app.include_router(tasks.router, prefix="/api/tasks", tags=["tasks"])
app.include_router(intake_router, prefix="/api/intake", tags=["intake"])


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "1.3-china"}


FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if FRONTEND_DIST.exists():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_frontend(full_path: str):
        requested = FRONTEND_DIST / full_path
        if full_path and requested.exists() and requested.is_file():
            return FileResponse(str(requested))
        return FileResponse(str(FRONTEND_DIST / "index.html"))
