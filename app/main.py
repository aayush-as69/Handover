from __future__ import annotations

import hmac
import logging
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from . import __version__
from .config import Settings
from . import metrics
from .security import client_ip
from .throttle import RateLimiter
from .db import check_ready, get_session, init_db

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
    init_db(settings.migrate_on_startup)
    from .db import SessionLocal as _Session
    from .jobs import recover_interrupted, requeue_stale
    with _Session() as _s:
        # Thread mode: nothing survives a restart. Queue mode: workers outlive the web process,
        # so only jobs whose worker went quiet are put back.
        (requeue_stale if settings.job_mode == "queue" else recover_interrupted)(_s)
    if settings.demo_mode and settings.demo_password:
        from .db import SessionLocal
        from .demo import bootstrap_demo
        with SessionLocal() as session:
            bootstrap_demo(session, settings.demo_password)
    yield


SESSION_HOURS = 8
_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}   # bounds metric labels


def create_app(secret_key: str | None = None, config: Settings | None = None) -> FastAPI:
    from .handover_web import router as handover_router
    from .insights_web import router as insights_router
    from .web import router
    from .workspace_web import router as workspace_router
    from .bulk_web import router as bulk_router
    from .discuss_web import router as discuss_router

    cfg = config or Settings()
    for w in cfg.validate():                       # production problems raise ConfigError here
        log.warning(w)
    key = secret_key or cfg.secret_key
    if not key:
        # No fixed key: sessions simply end when the server restarts. Safe, never a default.
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
        # Optional origin lock: the CDN injects this secret header on every proxied request.
        # Render's direct *.onrender.com URL stays usable only for public liveness/readiness.
        if cfg.edge_shared_secret and path not in ("/health", "/ready"):
            supplied = request.headers.get("x-handover-origin-key", "")
            if not hmac.compare_digest(supplied, cfg.edge_shared_secret):
                return PlainTextResponse("Use the public application domain.", status_code=403)
        if path not in ("/health", "/ready", "/metrics") and not path.startswith("/static/"):
            ip = client_ip(request, cfg.trust_proxy, cfg.edge_shared_secret)
            ok = general.allow(ip)
            limiter = "general"
            if ok and path == "/login" and request.method == "POST":
                ok = logins.allow(ip)
                limiter = "login"
            if not ok:
                metrics.inc("handover_rate_limited_total", limiter=limiter)
                return PlainTextResponse("Too many requests. Wait a minute and try again.",
                                         status_code=429, headers={"Retry-After": "60"})
        return await call_next(request)

    @app.middleware("http")
    async def observe(request, call_next):
        """Outermost: time every request and count it by route template, never by raw URL."""
        started = time.perf_counter()
        request_id = request.headers.get("x-request-id", "")[:64] or secrets.token_hex(8)
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        except SQLAlchemyError:
            metrics.inc("handover_db_errors_total", where="request")
            raise
        finally:
            route = request.scope.get("route")
            template = getattr(route, "path", None) or ("/static" if request.url.path.startswith("/static/") else "unmatched")
            seconds = time.perf_counter() - started
            if template not in ("/metrics",):
                metrics.inc("handover_requests_total", method=request.method if request.method in _METHODS else "OTHER", route=template,
                            status=f"{status // 100}xx")
                metrics.observe("handover_request_seconds", seconds, route=template)
                metrics.log_request(request.method, template, status, seconds, request_id)

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        for k, v in _HEADERS.items():
            response.headers.setdefault(k, v)
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable" if request.url.query.startswith("v=") else "public, max-age=300"
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
    app.include_router(workspace_router)
    app.include_router(bulk_router)
    app.include_router(discuss_router)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, exc):
        if exc.status_code in (301, 302, 303, 307):
            return RedirectResponse((exc.headers or {}).get("Location", "/"), status_code=exc.status_code)
        from .web import templates
        return templates.TemplateResponse(
            request, "error.html", {"user": None, "csrf": "", "flash": None,
                                    "code": exc.status_code, "message": exc.detail},
            status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        """Anything unforeseen: log the detail for operators, show the person nothing internal."""
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        from .web import templates
        return templates.TemplateResponse(
            request, "error.html", {"user": None, "csrf": "", "flash": None, "code": 500,
                                    "message": "Something went wrong on our side. Nothing was lost; try again."},
            status_code=500)

    @app.get("/health")
    def health() -> dict:
        """Liveness: the process is up. Says nothing about the database."""
        return {"status": "ok", "version": __version__}

    @app.get("/metrics")
    def metrics_endpoint(request: Request, format: str = "text", session: Session = Depends(get_session)):
        """Counts and latency for operators. Needs METRICS_TOKEN as a bearer token, or an admin session."""
        token = cfg.metrics_token
        auth = request.headers.get("authorization", "")
        ok = bool(token) and hmac.compare_digest(auth, f"Bearer {token}")
        if not ok:
            from .enums import Role
            from .web import current_user
            user = current_user(request, session)
            ok = user is not None and user.role == Role.admin
        if not ok:
            return PlainTextResponse("Not found.", status_code=404)
        jobs = metrics.job_counts(session)
        if format == "json":
            return JSONResponse(metrics.render_json(jobs))
        return PlainTextResponse(metrics.render_text(jobs), media_type="text/plain; version=0.0.4")

    @app.get("/ready")
    def ready(session: Session = Depends(get_session)):
        """Readiness: the database answers and the schema is current. 503 otherwise."""
        ok, reason = check_ready(session.get_bind())
        return JSONResponse({"status": reason}, status_code=200 if ok else 503)

    return app


app = create_app()
