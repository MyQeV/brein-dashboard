"""Regression tests for the security and correctness fixes.

These run without a database. Where a request legitimately reaches the
database (because it passed every gate we are testing), the assertion is that
the response is *not* the rejection we are guarding against, rather than a
specific success code.
"""

import time
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from brein.web import csrf
from brein.web.auth import ACCESS_TOKEN_COOKIE_NAME, REFRESH_TOKEN_COOKIE_NAME
from brein.web.schemas import User

CSRF_REJECTED = 403

# A cookie-authenticated write with a JSON body: the kind of request the Next
# frontend makes on every page, and the one the CSRF middleware exists for.
PREFERENCE_URL = "/api/user/preferences/theme"
SET_PREFERENCE = "brein.web.routers.user_preferences.store.set_preference"
GET_PREFERENCES = "brein.web.routers.user_preferences.store.get_all"


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


def test_cookie_authed_write_without_csrf_token_is_rejected(client):
    with patch(SET_PREFERENCE, new_callable=AsyncMock) as store:
        r = client.put(
            PREFERENCE_URL,
            json={"value": "dark"},
            cookies={ACCESS_TOKEN_COOKIE_NAME: "session-cookie"},
        )
    assert _is_csrf_rejection(r)
    store.assert_not_awaited()


def test_mismatched_csrf_token_is_rejected(client):
    with patch(SET_PREFERENCE, new_callable=AsyncMock) as store:
        r = client.put(
            PREFERENCE_URL,
            json={"value": "dark"},
            headers={csrf.HEADER_NAME: "not-the-cookie"},
            cookies={
                ACCESS_TOKEN_COOKIE_NAME: "session-cookie",
                csrf.COOKIE_NAME: csrf.new_token(),
            },
        )
    assert _is_csrf_rejection(r)
    store.assert_not_awaited()


def test_matching_csrf_header_reaches_the_handler(client):
    """The header path is the one the frontend uses; the request must reach
    the store, not merely avoid the 403."""
    token = csrf.new_token()
    with patch(SET_PREFERENCE, new_callable=AsyncMock) as store:
        r = client.put(
            PREFERENCE_URL,
            json={"value": "dark"},
            headers={csrf.HEADER_NAME: token},
            cookies={
                ACCESS_TOKEN_COOKIE_NAME: "session-cookie",
                csrf.COOKIE_NAME: token,
            },
        )
    assert r.status_code == 204, r.text
    store.assert_awaited_once_with("1", "theme", "dark")


def test_matching_csrf_form_field_passes_the_middleware(client):
    """The form-field fallback. No JSON route takes a form, so the handler
    answers 422 — which is the router validating the body, past the CSRF
    check, not the middleware refusing it."""
    token = csrf.new_token()
    r = client.put(
        PREFERENCE_URL,
        data={csrf.FORM_FIELD: token},
        cookies={
            ACCESS_TOKEN_COOKIE_NAME: "session-cookie",
            csrf.COOKIE_NAME: token,
        },
    )
    assert r.status_code == 422, r.text


def test_bearer_authenticated_api_call_is_exempt(client):
    """A cross-site form cannot set an Authorization header, so the Bearer API
    needs no token — and requiring one would break every API client."""
    with patch(SET_PREFERENCE, new_callable=AsyncMock) as store:
        r = client.put(
            PREFERENCE_URL,
            json={"value": "dark"},
            headers={"Authorization": "Bearer irrelevant"},
        )
    assert r.status_code == 204, r.text
    store.assert_awaited_once()


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


def test_safe_methods_are_never_challenged(client):
    with patch(GET_PREFERENCES, new_callable=AsyncMock, return_value={"a": 1}):
        r = client.get(
            "/api/user/preferences",
            cookies={ACCESS_TOKEN_COOKIE_NAME: "session-cookie"},
        )
    assert r.status_code == 200
    assert r.json() == {"a": 1}


def test_a_cookie_authenticated_get_is_issued_a_csrf_cookie(client):
    """The frontend never renders a template, so the middleware is the only
    place a browser that has the session cookie but no token gets one."""
    with patch(GET_PREFERENCES, new_callable=AsyncMock, return_value={}):
        r = client.get(
            "/api/user/preferences",
            cookies={ACCESS_TOKEN_COOKIE_NAME: "session-cookie"},
        )
    assert r.status_code == 200
    assert csrf.COOKIE_NAME in r.cookies


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
        # IPv4-mapped IPv6 connects to the same loopback.
        "http://[::ffff:127.0.0.1]:8080",
        # "This host" — routes to a local interface on most stacks.
        "http://0.0.0.0:8080",
        "http://[::]:8080",
        # IPv6 link-local, the counterpart of 169.254/16.
        "http://[fe80::1]:8080",
    ],
)
async def test_blocked_addresses_are_rejected(url):
    from brein.integrations.api.base import _is_ssrf_risk_url

    assert await _is_ssrf_risk_url(url) is True


@pytest.mark.asyncio
async def test_blocked_request_error_names_only_the_origin():
    """The full URL carries the API key for services that take it as a query
    parameter, and this message ends up in the log and the test reply."""
    from brein.integrations.api.base import SsrfBlockedError, new_http_client

    async with new_http_client(2.0) as client:
        with pytest.raises(SsrfBlockedError) as exc:
            await client.get("http://127.0.0.1:9/secret/path?apikey=hunter2")
    message = str(exc.value)
    assert "http://127.0.0.1:9" in message
    assert "secret" not in message
    assert "hunter2" not in message
    assert "?" not in message


def test_redirect_message_drops_the_query_string():
    """A server that echoes the request's query back in Location would put
    the API key in the connection-test reply."""
    from brein.integrations.api.base import redirect_message

    r = httpx.Response(
        301, headers={"location": "https://emby.example/System/Info?api_key=hunter2"}
    )
    message = redirect_message(r)
    assert "https://emby.example/System/Info" in message
    assert "hunter2" not in message
    assert "api_key" not in message


def test_redirect_message_without_a_location():
    from brein.integrations.api.base import redirect_message

    assert "another URL" in redirect_message(httpx.Response(302))


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
    # The gate reads the user count from the test database, which may well
    # be empty, and the route reads the store; the answer under test is the
    # auth dependency's, so both are mocked.
    with (
        patch(
            "brein.web.app.store_users.count_users",
            new_callable=AsyncMock,
            return_value=1,
        ),
        patch(
            "brein.store.service_config.list_services",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        async with _client(app) as c:
            r = await c.get(
                "/api/services",
                cookies={ACCESS_TOKEN_COOKIE_NAME: "cookie-only-no-bearer"},
            )
    assert r.status_code == 200, r.text
    assert r.json() == {"services": []}


# ── User administration ──────────────────────────────────────────────────────


def test_admin_cannot_change_their_own_role(client):
    """Self-demotion is how an instance ends up with no administrator, and it
    is not recoverable from the UI. The guard lived only in the Jinja form
    handler; it has to hold on the JSON path too."""
    with patch(
        "brein.store.users.update_user_role_status", new_callable=AsyncMock
    ) as store:
        # The signed-in admin of the `client` fixture has id "1".
        r = client.patch("/api/users/1", json={"role": "user", "disabled": False})
    assert r.status_code == 400
    assert "cannot change your own role" in r.json()["detail"].lower()
    store.assert_not_awaited()


@pytest.mark.parametrize(
    "method, path",
    [
        ("GET", "/api/tasks"),
        ("GET", "/api/settings/system"),
        ("GET", "/api/users"),
        ("POST", "/api/users"),
        ("PATCH", "/api/users/someone"),
        ("PUT", "/api/instances/1"),
        ("DELETE", "/api/instances/1"),
        ("POST", "/api/instances/test"),
    ],
)
def test_admin_only_routes_refuse_a_signed_in_viewer(viewer_client, method, path):
    """A signed-in non-admin must get 403, not the route's own answer.

    The `client` fixture overrides the admin dependency itself, so it can
    never prove a route is admin-gated; this one only signs the viewer in.
    """
    r = viewer_client.request(method, path, json={})
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "Admin required"


def test_viewer_still_reaches_user_routes(viewer_client):
    with patch(GET_PREFERENCES, new_callable=AsyncMock, return_value={}):
        r = viewer_client.get("/api/user/preferences")
    assert r.status_code == 200


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


# ── Login ────────────────────────────────────────────────────────────────────

AUTHENTICATE = "brein.web.auth.authenticate_user"
LOGIN_FAILURE = "brein.store.users.record_login_failure"
LOGIN_SUCCESS = "brein.store.users.record_login_success"
CREATE_REFRESH = "brein.store.refresh_tokens.create"
ON_LOGIN = "brein.web.routers.auth.run_on_login_tasks"

LOGIN_FORM = {"username": "ada", "password": "hunter2"}  # pragma: allowlist secret


def _user(**overrides) -> User:
    fields = {
        "id": "u1",
        "username": "ada",
        "email": None,
        "full_name": None,
        "disabled": False,
        "is_admin": False,
        "role": "user",
    }
    return User(**{**fields, **overrides})


def _login(client, authenticated, **kwargs):
    with (
        patch(AUTHENTICATE, new_callable=AsyncMock, return_value=authenticated),
        patch(LOGIN_FAILURE, new_callable=AsyncMock) as failure,
        patch(LOGIN_SUCCESS, new_callable=AsyncMock),
        patch(
            CREATE_REFRESH, new_callable=AsyncMock, return_value=("rt-plain", "rt-id")
        ),
        patch(ON_LOGIN),
    ):
        r = client.post("/token", data=LOGIN_FORM, **kwargs)
    return r, failure


def test_disabled_user_is_refused_like_a_wrong_password(client):
    """A disabled account must not be told apart from a wrong password, and
    the attempt counts towards its lockout like any other failure."""
    disabled, failure = _login(client, (_user(disabled=True), None))
    wrong, wrong_failure = _login(client, (None, "u1"))

    assert disabled.status_code == wrong.status_code == 401
    assert disabled.json() == wrong.json()
    failure.assert_awaited_once_with("u1")
    wrong_failure.assert_awaited_once_with("u1")
    assert ACCESS_TOKEN_COOKIE_NAME not in disabled.cookies


def test_unknown_user_records_no_failure(client):
    r, failure = _login(client, (None, None))
    assert r.status_code == 401
    failure.assert_not_awaited()


def test_browser_login_keeps_the_tokens_in_the_cookies(client):
    """A browser sends Origin; script on the page must not be handed the
    tokens that httpOnly exists to keep from it."""
    r, _ = _login(client, (_user(), None), headers={"Origin": "http://testserver"})
    assert r.status_code == 200, r.text
    assert r.json() == {"token_type": "bearer"}
    assert r.cookies.get(ACCESS_TOKEN_COOKIE_NAME)
    assert r.cookies.get(REFRESH_TOKEN_COOKIE_NAME) == "rt-plain"
    # The first write after signing in needs a token to echo back.
    assert r.cookies.get(csrf.COOKIE_NAME)


def test_script_login_gets_the_tokens_in_the_body(client):
    r, _ = _login(client, (_user(), None))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["refresh_token"] == "rt-plain"


def _refresh(client, **kwargs):
    token_info = {"user_id": "u1", "expires_at": time.time() + 3600}
    row = {"id": "u1", "username": "ada", "disabled": False}
    with (
        patch(
            "brein.store.refresh_tokens.get_token_info",
            new_callable=AsyncMock,
            return_value=token_info,
        ),
        patch(
            "brein.store.users.get_user_by_id", new_callable=AsyncMock, return_value=row
        ),
        patch(
            "brein.store.refresh_tokens.rotate",
            new_callable=AsyncMock,
            return_value=("rt-next", "rt-next-id"),
        ) as rotate,
    ):
        r = client.post("/refresh", **kwargs)
    return r, rotate


def test_cookie_refresh_keeps_the_tokens_in_the_cookies(client):
    r, rotate = _refresh(client, cookies={REFRESH_TOKEN_COOKIE_NAME: "rt-plain"})
    assert r.status_code == 200, r.text
    assert r.json() == {"token_type": "bearer"}
    assert r.cookies.get(REFRESH_TOKEN_COOKIE_NAME) == "rt-next"
    assert r.cookies.get(ACCESS_TOKEN_COOKIE_NAME)
    assert r.cookies.get(csrf.COOKIE_NAME)
    rotate.assert_awaited_once()
    assert rotate.await_args.args[0] == "rt-plain"


def test_body_refresh_gets_the_tokens_in_the_body(client):
    r, _ = _refresh(client, json={"refresh_token": "rt-plain"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["refresh_token"] == "rt-next"
    assert body["access_token"]


def test_login_rate_limit_applies_when_enabled(client):
    """conftest disables the limiter; this turns it back on for one test to
    prove the decorator on /token is live, not decorative."""
    from brein.web.rate_limit import limiter

    limiter.enabled = True
    limiter.reset()
    try:
        codes = [_login(client, (None, None))[0].status_code for _ in range(11)]
    finally:
        limiter.enabled = False
        limiter.reset()
    assert codes[:10] == [401] * 10
    assert codes[10] == 429


# ── API docs ─────────────────────────────────────────────────────────────────


def test_api_docs_are_not_served_outside_dev(app, client):
    """The schema enumerates every route to anyone who asks, unauthenticated."""
    from brein import config as brein_config

    if brein_config.DEV:
        pytest.skip("BREIN_DEV is set; the docs are meant to be served")
    assert app.docs_url is None
    assert app.redoc_url is None
    assert app.openapi_url is None
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404, path


# ── WebSocket origin ─────────────────────────────────────────────────────────


def test_websocket_refuses_a_foreign_origin(client):
    """The session cookie rides along on an upgrade from any page, so a page
    on another site could otherwise open the feed as the signed-in user."""
    from starlette.websockets import WebSocketDisconnect

    client.cookies.set(ACCESS_TOKEN_COOKIE_NAME, "session-cookie")
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(
            "/ws/now-playing", headers={"origin": "http://evil.example"}
        ):
            pass
    assert exc.value.code == 1008


@pytest.mark.parametrize(
    "headers",
    [
        {"origin": "http://testserver"},
        {"origin": "https://testserver:3100"},
        {},
    ],
)
def test_websocket_accepts_a_matching_or_absent_origin(client, headers):
    with (
        patch(
            "brein.web.auth.get_user_from_token",
            new_callable=AsyncMock,
            return_value=_user(),
        ),
        patch(
            "brein.cache.get_cached", new_callable=AsyncMock, return_value={"items": []}
        ),
    ):
        with client.websocket_connect("/ws/now-playing", headers=headers) as ws:
            ws.send_json({"token": "t"})
            assert ws.receive_json() == {"items": []}


def test_origin_check_reads_the_forwarded_host():
    """Behind the frontend's rewrite proxy Host is the upstream target; the
    browser's host arrives in X-Forwarded-Host."""
    from brein.web.routers.now_playing import _origin_allowed

    class _Ws:
        def __init__(self, headers):
            self.headers = headers

    assert _origin_allowed(
        _Ws(
            {
                "origin": "https://brein.example",
                "host": "brein:8001",
                "x-forwarded-host": "brein.example:443, proxy.internal",
            }
        )
    )
    assert not _origin_allowed(
        _Ws({"origin": "https://evil.example", "host": "brein.example"})
    )
    assert not _origin_allowed(_Ws({"origin": "null", "host": "brein.example"}))


# ── Setup gate ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unclaimed_instance_answers_api_calls_with_401_not_a_redirect(app):
    """With no users yet, the gate must refuse API calls, not redirect them.

    /setup is a page the frontend serves; this API has no such route. A 302
    there sent the frontend's server-side fetches into the API's own 404,
    and the browser's session probe (POST /refresh) to a page that answered
    200 — so a fresh install crashed on its first request instead of landing
    on the setup form. 401 is the answer the frontend already understands:
    it goes to login, and login points at setup.
    """
    from unittest.mock import AsyncMock, patch

    with patch(
        "brein.web.app.store_users.count_users", new_callable=AsyncMock, return_value=0
    ):
        async with _client(app) as c:
            r = await c.get("/api/instances")
    assert r.status_code == 401
    assert "location" not in r.headers
    assert "setup" in (r.json().get("detail") or "").lower()
