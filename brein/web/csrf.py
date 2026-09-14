"""CSRF protection for cookie-authenticated form submissions.

The JSON API authenticates with a Bearer token that a cross-site form cannot
attach, so it needs no CSRF token. The server-rendered ``<form method="post">``
pages are different: they authenticate with the ``brein_access_token`` cookie,
which the browser sends on cross-site requests, and several of them are
destructive (delete instance, reset Emby sessions).

The scheme is double-submit: a random token is issued in a readable cookie and
echoed back in a hidden form field, and the two must match. An attacker on
another origin can cause the cookie to be *sent* but cannot read it to populate
the field. ``SameSite=Lax`` on the auth cookie already blocks the common case;
this is the defence-in-depth layer behind it.
"""

import secrets
from urllib.parse import parse_qs

from starlette.requests import Request

COOKIE_NAME = "brein_csrf"
FORM_FIELD = "csrf_token"
HEADER_NAME = "X-CSRF-Token"

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

# Unsafe requests that legitimately carry no CSRF token:
#   /token      — login, no session exists yet
#   /api/setup  — first-admin creation, no session exists yet
#   /refresh    — driven by fetch() from our own JS; authenticated by the
#                 refresh cookie and it only rotates tokens
_EXEMPT_PATHS = frozenset({"/token", "/api/setup", "/refresh"})


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_for(request: Request) -> str:
    """Return this request's CSRF token, minting one if the cookie is absent.

    Cached on ``request.state`` so a single response issues a single token.
    """
    cached = getattr(request.state, "csrf_token", None)
    if cached:
        return cached
    token = request.cookies.get(COOKIE_NAME) or new_token()
    request.state.csrf_token = token
    return token


def should_issue_token(request: Request) -> bool:
    """True when this response should carry a CSRF cookie.

    Any authenticated caller needs one, not just a page that renders a Jinja
    form: the Next frontend authenticates with the same cookie and echoes the
    token back as a header, and it never renders a template.
    """
    from brein.web.auth import ACCESS_TOKEN_COOKIE_NAME

    if COOKIE_NAME in request.cookies:
        return False
    return ACCESS_TOKEN_COOKIE_NAME in request.cookies


def requires_csrf(request: Request) -> bool:
    """True when this request must present a matching CSRF token.

    Only cookie-authenticated, state-changing requests qualify. A request
    carrying an ``Authorization`` header is using the Bearer API and is not
    reachable by a cross-site form.
    """
    if request.method.upper() in _SAFE_METHODS:
        return False
    if request.url.path in _EXEMPT_PATHS:
        return False
    if request.headers.get("authorization"):
        return False
    from brein.web.auth import ACCESS_TOKEN_COOKIE_NAME

    return ACCESS_TOKEN_COOKIE_NAME in request.cookies


async def submitted_token(request: Request) -> str:
    """Read the token from the header, falling back to a form field.

    The body is read with ``request.body()``, never ``request.form()``.
    Starlette's BaseHTTPMiddleware only replays a body that ``body()`` cached;
    ``form()`` drains the stream without caching it, so the handler downstream
    would receive an empty body and reject its own request as malformed.
    """
    header = request.headers.get(HEADER_NAME)
    if header:
        return header

    content_type = request.headers.get("content-type", "")
    if not content_type.startswith("application/x-www-form-urlencoded"):
        # multipart is not parsed here: no endpoint takes a multipart write, and
        # buffering an upload in middleware to find one field is not worth it.
        # Those callers send the header instead.
        return ""

    try:
        raw = await request.body()
    except Exception:
        return ""
    values = parse_qs(raw.decode("utf-8", "replace"))
    submitted = values.get(FORM_FIELD, [""])[0]
    return submitted


def tokens_match(submitted: str, cookie: str) -> bool:
    if not submitted or not cookie:
        return False
    return secrets.compare_digest(submitted, cookie)
