from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from . import __version__
from .config import Settings
from .security import RateLimiter, client_ip
from .db import init_db

log = logging.getLogger("handover")
STATIC = Path(__file__).parent / "static"

_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Content-Security-Policy": "default-src 'self'; style-src 'self'; frame-ancestors 'none'",
    "Cache-Control": "no-store",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = app.state.cfg
    init_db()
    if settings.demo_mode and settings.demo_password:
        from .db import SessionLocal
        from .demo import bootstrap_demo
        with SessionLocal() as session:
            bootstrap_demo(session, settings.demo_password)
    yield


SESSION_HOURS = 8


def create_app(secret_key: str | None = None, config: Settings | None = None) -> FastAPI:
    from .handover_web import router as handover_router
    from .insights_web import router as insights_router
    from .web import router

    cfg = config or Settings()
    for w in cfg.validate():                       # production problems raise ConfigError here
        log.warning(w)
    key = secret_key or cfg.secret_key
    if not key:
        # No fixed key: sessions simply end when the server restarts. Safe, never a default.
        import secrets
        key = secrets.token_urlsafe(32)

    app = FastAPI(
        title="Handover",
        description="Evidence-linked, permission-aware knowledge handover.",
        version=__version__,
        lifespan=lifespan,
        # The interactive API docs and schema are for development only.
        docs_url=None if cfg.production else "/docs",
        redoc_url=None,
        openapi_url=None if cfg.production else "/openapi.json",
    )
    app.state.cfg = cfg

    general = RateLimiter(cfg.rate_limit_per_min)
    logins = RateLimiter(cfg.login_rate_per_min)
    app.state.limiters = (general, logins)

    @app.middleware("http")
    async def rate_limit(request, call_next):
        path = request.url.path
        if path != "/health" and not path.startswith("/static/"):
            ip = client_ip(request, cfg.trust_proxy)
            ok = general.allow(ip)
            if ok and path == "/login" and request.method == "POST":
                ok = logins.allow(ip)
            if not ok:
                return PlainTextResponse("Too many requests. Wait a minute and try again.",
                                         status_code=429, headers={"Retry-After": "60"})
        return await call_next(request)

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        for k, v in _HEADERS.items():
            response.headers.setdefault(k, v)
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "public, max-age=3600"
        if cfg.cookie_secure:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    app.add_middleware(
        SessionMiddleware, secret_key=key, session_cookie="handover_session", same_site="lax",
        max_age=SESSION_HOURS * 3600, https_only=cfg.cookie_secure,
    )
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    app.include_router(router)
    app.include_router(handover_router)
    app.include_router(insights_router)

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
