from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from . import __version__
from .db import init_db

STATIC = Path(__file__).parent / "static"

_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Content-Security-Policy": "default-src 'self'; style-src 'self'; frame-ancestors 'none'",
    "Cache-Control": "no-store",
}


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    password = os.environ.get("DEMO_PASSWORD")
    if os.environ.get("DEMO_MODE", "").lower() in ("1", "true", "yes") and password:
        from .db import SessionLocal
        from .demo import bootstrap_demo
        with SessionLocal() as session:
            bootstrap_demo(session, password)
    yield


def create_app(secret_key: str | None = None) -> FastAPI:
    from .handover_web import router as handover_router
    from .web import router

    key = secret_key or os.environ.get("SECRET_KEY")
    if not key:
        # No fixed key: sessions simply end when the server restarts. Safe, never a default.
        import secrets
        key = secrets.token_urlsafe(32)

    app = FastAPI(
        title="Handover",
        description="Evidence-linked, permission-aware knowledge handover.",
        version=__version__,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        for k, v in _HEADERS.items():
            response.headers.setdefault(k, v)
        return response

    app.add_middleware(
        SessionMiddleware, secret_key=key, same_site="lax", max_age=8 * 3600,
        https_only=os.environ.get("COOKIE_SECURE", "").lower() in ("1", "true", "yes"),
    )
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    app.include_router(router)
    app.include_router(handover_router)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, exc):
        if exc.status_code in (301, 302, 303, 307):
            return RedirectResponse((exc.headers or {}).get("Location", "/"), status_code=exc.status_code)
        from .web import templates
        return templates.TemplateResponse(
            request, "error.html", {"user": None, "csrf": "", "flash": None,
                                    "code": exc.status_code, "message": exc.detail},
            status_code=exc.status_code)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
