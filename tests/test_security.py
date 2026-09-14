"""Regression tests for the security and correctness fixes.

These run without a database. Where a request legitimately reaches the
database (because it passed every gate we are testing), the assertion is that
the response is *not* the rejection we are guarding against, rather than a
specific success code.
"""

import httpx
import pytest

from brein.web import csrf
from brein.web.auth import ACCESS_TOKEN_COOKIE_NAME

CSRF_REJECTED = 403


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    )


def _is_csrf_rejection(response: httpx.Response) -> bool:
    if response.status_code != CSRF_REJECTED:
        return False
    try:
        return "CSRF" in (response.json().get("detail") or "")
    except Exception:
        return False


# ── CSRF ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cookie_authed_form_post_without_csrf_token_is_rejected(app):
    async with _client(app) as c:
        r = await c.post(
            "/settings/config",
            data={"anything": "1"},
            cookies={ACCESS_TOKEN_COOKIE_NAME: "session-cookie"},
        )
    assert _is_csrf_rejection(r)


@pytest.mark.asyncio
async def test_mismatched_csrf_token_is_rejected(app):
    async with _client(app) as c:
        r = await c.post(
            "/settings/config",
            data={csrf.FORM_FIELD: "not-the-cookie"},
            cookies={
                ACCESS_TOKEN_COOKIE_NAME: "session-cookie",
                csrf.COOKIE_NAME: csrf.new_token(),
            },
        )
    assert _is_csrf_rejection(r)


@pytest.mark.asyncio
async def test_matching_csrf_token_passes(app):
    token = csrf.new_token()
    async with _client(app) as c:
        r = await c.post(
            "/settings/config",
            data={csrf.FORM_FIELD: token},
            cookies={
                ACCESS_TOKEN_COOKIE_NAME: "session-cookie",
                csrf.COOKIE_NAME: token,
            },
        )
    assert not _is_csrf_rejection(r)


@pytest.mark.asyncio
async def test_bearer_authenticated_api_call_is_exempt(app):
    """A cross-site form cannot set an Authorization header, so the Bearer API
    needs no token — and requiring one would break every API client."""
    async with _client(app) as c:
        r = await c.put(
            "/api/services/sonarr/config",
            json={"base_url": "http://example.com", "api_key": "x"},
            headers={"Authorization": "Bearer irrelevant"},
        )
    assert not _is_csrf_rejection(r)


@pytest.mark.asyncio
async def test_login_is_exempt(app):
    """No session exists yet at login, so there is no token to present."""
    async with _client(app) as c:
        r = await c.post(
            "/token",
            data={
                "username": "someone",
                "password": "something",  # pragma: allowlist secret
            },
            cookies={ACCESS_TOKEN_COOKIE_NAME: "stale"},
        )
    assert not _is_csrf_rejection(r)


@pytest.mark.asyncio
async def test_safe_methods_are_never_challenged(app):
    async with _client(app) as c:
        r = await c.get("/login", cookies={ACCESS_TOKEN_COOKIE_NAME: "session-cookie"})
    assert not _is_csrf_rejection(r)


def test_token_for_reuses_the_existing_cookie():
    """Two renders in one browser must agree on the token, or the double-submit
    comparison fails on the second form."""

    class _Req:
        def __init__(self, cookies):
            self.cookies = cookies

            class _S:
                pass

            self.state = _S()

    existing = csrf.new_token()
    assert csrf.token_for(_Req({csrf.COOKIE_NAME: existing})) == existing
    minted = csrf.token_for(_Req({}))
    assert minted and minted != existing


# ── SSRF ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8080",
        "http://localhost:8080",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]:8080",
    ],
)
async def test_blocked_addresses_are_rejected(url):
    from brein.integrations.api.base import _is_ssrf_risk_url

    assert await _is_ssrf_risk_url(url) is True


@pytest.mark.asyncio
async def test_private_lan_addresses_are_allowed():
    """Users legitimately point Brein at a media server on their LAN."""
    from brein.integrations.api.base import _is_ssrf_risk_url

    assert await _is_ssrf_risk_url("http://192.168.1.10:8096") is False
    assert await _is_ssrf_risk_url("http://10.0.0.5:7878") is False


@pytest.mark.asyncio
async def test_ssrf_guard_does_not_block_the_event_loop():
    """The guard must resolve through the loop, not socket.gethostbyname."""
    import inspect

    from brein.integrations.api import base

    assert inspect.iscoroutinefunction(base._is_ssrf_risk_url)
    source = inspect.getsource(base._is_ssrf_risk_url)
    assert "getaddrinfo(" in source
    # The call, not the mention — the docstring names what it replaced.
    assert "gethostbyname(" not in source


@pytest.mark.asyncio
async def test_client_factory_blocks_requests_to_loopback():
    """The guard is attached to the client, so a call site cannot skip it."""
    from brein.integrations.api.base import SsrfBlockedError, new_http_client

    async with new_http_client(2.0) as client:
        with pytest.raises(SsrfBlockedError):
            await client.get("http://127.0.0.1:9/should-never-connect")


def test_integrations_never_construct_a_raw_client():
    """Every httpx client in the package must come from new_http_client()."""
    import pathlib

    pkg = pathlib.Path(__file__).resolve().parent.parent / "brein" / "integrations"
    offenders = [
        f"{path.relative_to(pkg.parent.parent)}:{i}"
        for path in pkg.rglob("*.py")
        for i, line in enumerate(path.read_text().splitlines(), 1)
        if "httpx.AsyncClient(" in line and "def new_http_client" not in line
    ]
    # base.py's factory is the single permitted construction site.
    offenders = [
        o for o in offenders if not o.startswith("brein/integrations/api/base.py")
    ]
    assert offenders == [], f"raw httpx.AsyncClient() at: {offenders}"


# ── Secrets and data exposure ────────────────────────────────────────────────


def test_secret_columns_cover_credentials_and_hashes():
    from brein.web.routers.database import SECRET_COLUMNS

    assert "api_key" in SECRET_COLUMNS
    assert "hashed_password" in SECRET_COLUMNS


def test_emby_websocket_url_encodes_credentials():
    """A key containing & or # previously split the query string."""
    from brein.integrations.api.emby import emby_websocket_url

    url = emby_websocket_url("http://emby.local:8096", "a&b#c+d", "dev id")
    assert "a&b#c+d" not in url
    assert "a%26b%23c%2Bd" in url
    assert url.count("?") == 1
    assert url.count("&") == 1  # only the separator before deviceId


def test_backup_dir_defaults_inside_the_mounted_volume(monkeypatch):
    """docker-compose mounts the data volume at /app/data; anything outside it
    is destroyed by the next image rebuild.

    conftest points BREIN_BACKUP_DIR at a temp dir, so the default has to be
    re-derived with the variable unset.
    """
    import importlib
    import pathlib

    from brein import config

    compose = (
        pathlib.Path(__file__).resolve().parent.parent / "docker-compose.yml"
    ).read_text()
    assert ":/app/data" in compose

    monkeypatch.delenv("BREIN_BACKUP_DIR", raising=False)
    try:
        reloaded = importlib.reload(config)
        assert reloaded.BACKUP_DIR == "/app/data/backups"
    finally:
        monkeypatch.undo()
        importlib.reload(config)


def test_backup_dir_honours_the_env_override(monkeypatch, tmp_path):
    """The override, not just that the default is truthy.

    `assert config.BACKUP_DIR` passed with the env read deleted entirely —
    the shipped default is always truthy.
    """
    import importlib

    from brein import config

    monkeypatch.setenv("BREIN_BACKUP_DIR", str(tmp_path / "backups"))
    importlib.reload(config)
    try:
        assert config.BACKUP_DIR == str(tmp_path / "backups")
    finally:
        monkeypatch.undo()
        importlib.reload(config)


# ── Unified auth hierarchy ───────────────────────────────────────────────────


def test_cookie_or_bearer_names_are_aliases_not_copies():
    """There were two parallel hierarchies and which one a route got was
    arbitrary — that is how `AdminUser` came to mean different things in
    different routers. Aliasing keeps them from drifting apart again."""
    from brein.web import auth

    assert auth.get_current_user_cookie_or_bearer is auth.get_current_active_user
    assert auth.get_current_admin_user_cookie_or_bearer is auth.get_current_admin_user


@pytest.mark.asyncio
async def test_bearer_only_routes_now_accept_the_session_cookie(app, monkeypatch):
    """A Next frontend authenticates with the httpOnly cookie, so the JSON API
    has to accept it. Writes stay CSRF-protected."""
    from brein.web import auth
    from brein.web.schemas import User

    async def _fake_user(token):
        return User(
            id="1",
            username="tester",
            email=None,
            full_name=None,
            disabled=False,
            is_admin=True,
            role="admin",
        )

    monkeypatch.setattr(auth, "get_user_from_token", _fake_user)
    async with _client(app) as c:
        r = await c.get(
            "/api/services",
            cookies={ACCESS_TOKEN_COOKIE_NAME: "cookie-only-no-bearer"},
        )
    assert r.status_code != 401, r.text


# ── User administration ──────────────────────────────────────────────────────


def test_admin_cannot_change_their_own_role():
    """Self-demotion is how an instance ends up with no administrator, and it
    is not recoverable from the UI. The guard lived only in the Jinja form
    handler; it has to hold on the JSON path too."""
    import inspect

    from brein.web.routers import auth as auth_router

    source = inspect.getsource(auth_router.update_user_role_status_api)
    assert "current_user.id == user_id" in source
    assert "cannot change your own role" in source.lower()


@pytest.mark.asyncio
async def test_user_admin_endpoints_require_admin(app):
    """Both new routes must be admin-gated, like their siblings."""
    async with _client(app) as c:
        get_response = await c.get("/api/users/someone")
        patch_response = await c.patch(
            "/api/users/someone", json={"role": "user", "disabled": False}
        )
    # Unauthenticated: 401. What must never happen is a 200.
    assert get_response.status_code != 200
    assert patch_response.status_code != 200


@pytest.mark.asyncio
async def test_form_posts_still_reach_their_handler_with_a_body(app):
    """The CSRF middleware must not consume the request body.

    Starlette's BaseHTTPMiddleware only replays a body cached by body();
    form() drains the stream without caching, so reading the token that way
    left the handler with an empty body and turned a valid request into a 422.
    """
    import inspect

    from brein.web import csrf as csrf_module

    source = inspect.getsource(csrf_module.submitted_token)
    assert "await request.body()" in source
    assert "await request.form()" not in source


@pytest.mark.asyncio
async def test_login_issues_a_csrf_cookie(app):
    """The signed-in shell renders server-side, so those Set-Cookie headers
    never reach the browser. Without issuing one at login, the first write
    after signing in has no token to send."""
    import inspect

    from brein.web.routers import auth as auth_router

    source = inspect.getsource(auth_router)
    assert "_set_csrf_cookie" in source
    assert source.count("_set_csrf_cookie(request, response)") >= 2
