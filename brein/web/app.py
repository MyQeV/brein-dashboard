"""FastAPI app: static UI and API for services."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable


from fastapi import FastAPI, HTTPException, Request

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from brein.web import csrf
from brein.web.rate_limit import is_trusted_proxy, limiter

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from brein import cache as brein_cache
from brein import config as brein_config
from brein import db as brein_db
from brein.web.routers import auth as auth_router
from brein.web.routers import database as database_router
from brein.web.routers import dashboard as dashboard_router
from brein.web.routers import emby as emby_router
from brein.web.routers import image as image_router
from brein.web.routers import plex as plex_router
from brein.web.routers import instances as instances_router
from brein.web.routers import calendar as calendar_router
from brein.web.routers import now_playing as now_playing_router
from brein.web.routers.now_playing import (
    NOW_PLAYING_CACHE_KEY,
    broadcast_now_playing,
    refresh_now_playing_state,
)
from brein.extensions import load_extensions
from brein.web.routers import radarr as radarr_router
from brein.web.routers import sabnzbd as sabnzbd_router
from brein.web.routers import downloads as downloads_router
from brein.web.routers import tasks as tasks_router
from brein.integrations.api import emby as emby_api
from brein.integrations.websockets import registry as ws_registry
from brein.store import instances as store_instances
from brein.web.routers import services as services_router
from brein.web.routers import settings as settings_router
from brein.web.routers import sonarr as sonarr_router
from brein.web.routers import user_preferences as user_preferences_router

from brein.web.routers import users_import as users_import_router
from brein.store import users as store_users
from brein.web import auth as web_auth
from brein.jobs.emby_users_sync import run_emby_users_sync_instance
from brein.jobs.scheduled_task_reconciler import reconcile as reconcile_scheduled_tasks
from brein.jobs.scheduled_task_runner import scheduled_task_runner_loop
from brein.store import scheduled_tasks as store_scheduled_tasks

from brein import logging_setup as _logging_setup

_logging_setup.setup_logging()
log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"


async def _on_emby_playback_event() -> None:
    """Called when Emby pushes a WebSocket event; refresh and broadcast to WS clients."""
    try:
        data = await refresh_now_playing_state()
        await brein_cache.set_cached(NOW_PLAYING_CACHE_KEY, data)
        await broadcast_now_playing(data)
        n = len(data.get("items") or [])
        log.debug("Now-playing broadcast after Emby event: %d items to clients", n)
    except Exception as e:
        log.warning("Now-playing broadcast after Emby event: %s", e)


async def _auto_create_admin() -> int:
    """Create the first admin user from env vars if no users exist. Returns user count."""

    user_count = await store_users.count_users()
    if user_count > 0:
        return user_count
    admin_user = os.environ.get("BREIN_ADMIN_USERNAME", "").strip()
    admin_pass = os.environ.get("BREIN_ADMIN_PASSWORD", "").strip()
    if admin_user and admin_pass:
        from brein.web.password_policy import validate_password_for_user

        try:
            validate_password_for_user(admin_pass, admin_user)
        except ValueError as e:
            log.warning("BREIN_ADMIN_PASSWORD does not meet policy: %s", e)
            return 0
        try:
            hashed = web_auth.get_password_hash(admin_pass)
            await store_users.create_user(
                username=admin_user,
                hashed_password=hashed,
                is_admin=True,
            )
            log.info("Auto-created admin user '%s' from env vars.", admin_user)
            return 1
        except Exception as exc:
            log.warning("Failed to auto-create admin user: %s", exc)
    return 0


def _make_on_user_event(iid: int) -> Callable[..., Any]:
    async def _on_emby_user_event() -> None:
        await run_emby_users_sync_instance(iid)

    return _on_emby_user_event


async def _start_listener_for_instance(instance_id: int) -> asyncio.Task | None:
    """Start the right WebSocket listener for one instance, if it wants one.

    Returns None when the instance is inactive, unconfigured, or of a service
    that has no live listener — the caller treats that as "nothing to run".
    """
    from brein.integrations.websockets import plex as plex_ws

    instances = await store_instances.list_instances()
    row = next(
        (i for i in instances if i.get("id") == instance_id),
        None,
    )
    if row is None or not row.get("is_configured") or not row.get("active", True):
        return None

    cfg = await store_instances.get_instance_connection_config(instance_id)
    if not cfg:
        return None
    service_type, base_url, api_key = cfg
    if not base_url or not api_key:
        return None

    if service_type == "emby":
        return asyncio.create_task(
            emby_api.run_emby_websocket_listener(
                base_url,
                api_key,
                _on_emby_playback_event,
                device_id="brein",
                instance_id=instance_id,
                on_user_event=_make_on_user_event(instance_id),
            )
        )
    if service_type == "plex":
        return asyncio.create_task(
            plex_ws.run_plex_notification_listener(base_url, api_key, instance_id)
        )
    return None


async def _start_all_ws_listeners() -> None:
    """Start a listener for every instance that should have one."""
    ws_registry.configure(_start_listener_for_instance)
    for inst in await store_instances.list_instances():
        instance_id = inst.get("id")
        if instance_id is None:
            continue
        task = await _start_listener_for_instance(int(instance_id))
        if task is not None:
            ws_registry.track(int(instance_id), task)


async def _cancel_task(task: asyncio.Task | None) -> None:
    """Cancel a task and wait for it to finish, ignoring CancelledError."""
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB, start background tasks, clean up on shutdown."""
    await brein_db.init_db()
    brein_config._warn_if_no_secret()
    brein_config._warn_if_no_database_url()

    from brein.db import get_session_factory
    from brein.store import system_settings as store_system_settings

    factory = get_session_factory()
    async with factory() as _ss_session:
        await store_system_settings.apply_to_config(_ss_session)

    await _auto_create_admin()
    await _start_all_ws_listeners()

    async with factory() as _sched_session:
        await reconcile_scheduled_tasks(_sched_session)
        await store_scheduled_tasks.reap_orphan_running_runs(_sched_session)
        await _sched_session.commit()
    scheduler_task = asyncio.create_task(scheduled_task_runner_loop())

    try:
        yield
    finally:
        await ws_registry.stop_all()
        await _cancel_task(scheduler_task)
        from brein.integrations.api.base import close_http_client

        await close_http_client()
        await brein_db.close_engine()


app = FastAPI(title="Brein", version="0.1.0", lifespan=lifespan)
if os.environ.get("BREIN_DISABLE_RATE_LIMIT", "").strip().lower() in (
    "1",
    "true",
    "yes",
):
    limiter.enabled = False
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Redirect GET 401 on app pages to login with next= so user can log in and return."""
    if exc.status_code == 401 and request.method == "GET":
        path = request.url.path
        if path == "/profile":
            return RedirectResponse(url="/login?next=/profile", status_code=302)
    headers = getattr(exc, "headers", None) or {}
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=dict(headers),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Log full traceback for 500 errors."""
    log.exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error"},
    )


def _setup_gate_allowed(method: str, path: str) -> bool:
    """True if path is allowed when no users exist (setup mode)."""
    if method == "GET" and path == "/api/setup-status":
        return True
    if method == "POST" and path == "/api/setup":
        return True
    if method == "GET" and path.startswith("/static/"):
        return True
    return False


@app.get("/api/setup-status")
async def setup_status() -> dict:
    """Whether the instance still needs its first administrator.

    Unauthenticated on purpose, and it leaks nothing an unclaimed instance does
    not already reveal by redirecting to setup. The frontend needs it because
    its own auth gate only sees cookies: without this, a fresh install shows a
    login form that cannot succeed and nothing points at /setup.
    """
    from brein.store import users as store_users

    try:
        return {"setup_required": await store_users.count_users() == 0}
    except Exception:
        log.exception("Could not read the user count for setup status")
        raise HTTPException(status_code=503, detail="Service unavailable") from None


@app.middleware("http")
async def https_redirect_middleware(request: Request, call_next):
    """When FORCE_HTTPS is set, redirect HTTP to HTTPS (for production behind a proxy)."""
    if brein_config.FORCE_HTTPS:
        forwarded_proto = request.headers.get("X-Forwarded-Proto", "").strip().lower()
        if forwarded_proto != "https" and request.url.scheme != "https":
            # The proxy's host header is only trusted from a trusted proxy;
            # otherwise anyone could point the redirect at their own domain by
            # sending X-Forwarded-Host.
            host = request.url.netloc
            if is_trusted_proxy(request):
                host = request.headers.get("X-Forwarded-Host", host) or host
            path = request.url.path or "/"
            query = request.url.query
            url = f"https://{host}{path}"
            if query:
                url += f"?{query}"
            return RedirectResponse(url=url, status_code=301)
    return await call_next(request)


@app.middleware("http")
async def setup_gate_middleware(request: Request, call_next):
    """When no users exist, allow only setup-status, POST /api/setup and /static/*; else 401.

    401 rather than a redirect: /setup is a page the frontend serves, not a
    route here, and a 302 to it sent the frontend's own server-side fetches
    into this API's 404. The frontend already treats 401 as "go to login",
    and login sends an unclaimed instance on to the setup form.

    Fails closed. If the user count cannot be read the gate cannot know whether
    the instance is still unclaimed, and serving the app anyway would present a
    fresh install as a configured one. The database is unreachable in that case
    regardless, so 503 is both the safe and the accurate answer.
    """

    if _setup_gate_allowed(request.method, request.url.path):
        return await call_next(request)
    try:
        if await store_users.count_users() == 0:
            return JSONResponse({"detail": "Setup required"}, status_code=401)
    except Exception:
        log.exception("setup_gate_middleware could not read the user count")
        return JSONResponse(
            {"detail": "Service unavailable. Check the server logs for details."},
            status_code=503,
        )
    return await call_next(request)


@app.middleware("http")
async def csrf_middleware(request: Request, call_next):
    """Verify CSRF on cookie-authenticated writes; issue the token cookie.

    Bearer-authenticated API calls are skipped — a cross-site form cannot set
    an Authorization header — so this only guards the server-rendered forms.
    """
    if csrf.requires_csrf(request):
        submitted = await csrf.submitted_token(request)
        if not csrf.tokens_match(submitted, request.cookies.get(csrf.COOKIE_NAME, "")):
            log.warning("CSRF check failed for %s %s", request.method, request.url.path)
            return JSONResponse(
                {"detail": "Invalid or missing CSRF token. Reload the page and retry."},
                status_code=403,
            )

    # An authenticated caller needs a token whether or not a Jinja template
    # renders one. The Next frontend never renders Jinja, so without this it
    # would have no token to echo and every write would be refused.
    if csrf.should_issue_token(request):
        csrf.token_for(request)

    response = await call_next(request)

    # Issue the cookie whenever a token was minted for this request and the
    # browser does not already have it.
    token = getattr(request.state, "csrf_token", None)
    if token and request.cookies.get(csrf.COOKIE_NAME) != token:
        response.set_cookie(
            key=csrf.COOKIE_NAME,
            value=token,
            path="/",
            # Readable by JS on purpose: the double-submit scheme needs the
            # page to echo it back. It is not a credential on its own.
            httponly=False,
            samesite="lax",
            secure=brein_config.COOKIE_SECURE,
        )
    return response


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    headers = response.headers
    headers.setdefault("X-Content-Type-Options", "nosniff")
    headers.setdefault("X-Frame-Options", "DENY")
    headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=(), fullscreen=()",
    )
    csp = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob: https:; "
        "font-src 'self' data:; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "frame-ancestors 'none'; "
        "base-uri 'self';"
    )
    headers.setdefault("Content-Security-Policy", csp)
    if brein_config.FORCE_HTTPS:
        headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )
    return response


app.include_router(auth_router.router)
app.include_router(user_preferences_router.router)
app.include_router(database_router.router)
app.include_router(services_router.router)
app.include_router(instances_router.router)
app.include_router(radarr_router.router)
app.include_router(sabnzbd_router.router)
app.include_router(tasks_router.router)
app.include_router(downloads_router.router)
app.include_router(sonarr_router.router)
app.include_router(emby_router.router)
app.include_router(plex_router.router)
app.include_router(dashboard_router.router)
app.include_router(now_playing_router.router)
app.include_router(calendar_router.router)
app.include_router(settings_router.router)
app.include_router(image_router.router)
app.include_router(users_import_router.router)
for _extra_router in load_extensions().routers:
    app.include_router(_extra_router)

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Every page is served by the Next frontend; this app is the JSON API.
# The 39 Jinja page and fragment routes that used to live below here, and the
# helpers that only existed to build their template context, were removed once
# each surface had an equivalent under /api.
