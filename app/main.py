from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.providers.langfuse import LangfuseProvider
from app.service import DashboardService


BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

providers = {}
if settings.langfuse_enabled:
    providers["langfuse"] = LangfuseProvider(settings)
service = DashboardService(settings, providers)

app = FastAPI(title="SPS Dashboard", docs_url="/api/docs", redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = (
        f"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        f"connect-src 'self'; frame-ancestors {settings.frame_ancestors}"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "providers": sorted(providers)}


@app.get("/api/config")
async def public_config():
    return {
        "title": settings.dashboard_title,
        "refresh_seconds": settings.refresh_seconds,
        "default_range": settings.default_range,
        "allowed_ranges": settings.allowed_ranges,
        "sources": sorted(providers),
    }


@app.get("/api/dashboard")
async def dashboard(
    range_name: str = Query(default=settings.default_range, alias="range"),
    source: str = Query(default="langfuse"),
):
    try:
        return await service.fetch(range_name=range_name, source=source)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Dashboard source failed: {exc}") from exc
