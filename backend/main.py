"""FastAPI entry point for DD Report Generator (v1.1 with chunker)."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from db import init_db
from routers import upload, report, settings
from routers.auth_router import router as auth_router

app = FastAPI(title="DD Report Generator", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize database (create tables + seed admin)
init_db()

app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(upload.router, prefix="/api/upload", tags=["upload"])
app.include_router(report.router, prefix="/api/report", tags=["report"])
app.include_router(settings.router, prefix="/api/settings", tags=["settings"])


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "1.2-auth"}
