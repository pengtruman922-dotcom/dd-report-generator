"""FastAPI entry point for DD Report Generator (v1.1 with chunker)."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import CORS_ORIGINS
from db import init_db
from routers import upload, report, settings, tasks
from routers.auth_router import router as auth_router
from routers.tools import router as tools_router
from services.task_manager import task_manager
from services.pipeline import run_pipeline

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Startup: Initialize database and recover tasks
    init_db()

    # Recover pending/running tasks
    log.info("Recovering pending tasks...")
    recovered = await task_manager.recover_tasks(run_pipeline)
    if recovered > 0:
        log.info(f"Successfully recovered {recovered} tasks")

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
app.include_router(upload.router, prefix="/api/upload", tags=["upload"])
app.include_router(report.router, prefix="/api/report", tags=["report"])
app.include_router(settings.router, prefix="/api/settings", tags=["settings"])
app.include_router(tools_router, prefix="/api/tools", tags=["tools"])
app.include_router(tasks.router, prefix="/api/tasks", tags=["tasks"])


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "1.3-china"}
