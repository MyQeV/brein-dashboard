"""Auth: password hashing, JWT, OAuth2 scheme, get_current_user dependencies."""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash

from brein import config as brein_config
from brein.integrations.api import emby as emby_integration
from brein.integrations.api import jellyfin as jellyfin_integration
from brein.store import blacklist as store_blacklist
from brein.store import instances as store_instances
from brein.store import users as store_users
from brein.web.schemas import User

# pwdlib Argon2 (per FastAPI security tutorial)
password_hash = PasswordHash.recommended()
DUMMY_HASH = password_hash.hash("dummypassword")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)

ACCESS_TOKEN_COOKIE_NAME = "brein_access_token"
REFRESH_TOKEN_COOKIE_NAME = "brein_refresh_token"


async def get_token_cookie_or_bearer(
    request: Request,
    token_header: Annotated[str | None, Depends(oauth2_scheme_optional)],
) -> str:
    """Return JWT from Authorization header or from cookie (for full-page requests like /lookup)."""
    if token_header:
        return token_header
    token = request.cookies.get(ACCESS_TOKEN_COOKIE_NAME)
    if token:
        return token
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _user_from_row(row: dict) -> User:
    """Build a User schema instance from a database row dict."""
    return User(
        id=row["id"],
        username=row["username"],
        email=row.get("email"),
        full_name=row.get("full_name"),
        disabled=bool(row.get("disabled", 0)),
        is_admin=bool(row.get("is_admin", 0)),
        role=row.get("role") or "user",
    )


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify plain password against stored hash."""
    return password_hash.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash password for storage."""
    return password_hash.hash(password)


async def authenticate_user(
    username: str, password: str
) -> tuple[User | None, str | None]:
    """
    Authenticate by username/password.
    Returns (User, None) on success, (None, user_id) if password wrong, (None, None) if user not found
    or locked out after too many failures.
    Uses dummy hash when user not found to avoid timing attacks.
    For Emby/Jellyfin-linked users, credentials are verified against the media server API.
    """
    row = await store_users.get_user_by_username(username)
    if not row:
        verify_password(password, DUMMY_HASH)
        return None, None

    if store_users.login_locked(row):
        # Not a failure to record: the lockout is a fixed window after the
        # last counted failure, and attempts made during it must not extend
        # it. The password is not checked either, so the response is the same
        # as for an unknown user — a locked account is not announced.
        verify_password(password, DUMMY_HASH)
        return None, None

    user_id: str = row["id"]

    if row.get("emby_instance_id") and row.get("emby_username"):
        # Emby passthrough auth — verify against the Emby server.
        cfg = await store_instances.get_instance_connection_config(
            row["emby_instance_id"]
        )
        if not cfg:
            return None, user_id  # instance removed — deny login
        service_type, base_url, _ = cfg
        if service_type != "emby":
            return None, user_id  # instance type changed — deny login
        ok, _ = await emby_integration.authenticate_user(
            base_url, row["emby_username"], password
        )
        verify_password(password, DUMMY_HASH)  # constant-time padding
        if not ok:
            return None, user_id
    elif row.get("jellyfin_instance_id") and row.get("jellyfin_username"):
        # Jellyfin passthrough auth — verify against the Jellyfin server.
        cfg = await store_instances.get_instance_connection_config(
            row["jellyfin_instance_id"]
        )
        if not cfg:
            return None, user_id  # instance removed — deny login
        service_type, base_url, _ = cfg
        if service_type != "jellyfin":
            return None, user_id  # instance type changed — deny login
        ok, _ = await jellyfin_integration.authenticate_user(
            base_url, row["jellyfin_username"], password
        )
        verify_password(password, DUMMY_HASH)  # constant-time padding
        if not ok:
            return None, user_id
    else:
        if not verify_password(password, row["hashed_password"]):
            return None, user_id

    return _user_from_row(row), None


def create_access_token(
    data: dict,
    expires_delta: timedelta | None = None,
) -> str:
    """Create JWT with exp and jti (for blacklist on logout). data should include 'sub' (username)."""
    to_encode = data.copy()
    if "jti" not in to_encode:
        to_encode["jti"] = str(uuid.uuid4())
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode["exp"] = expire
    encoded_jwt = jwt.encode(
        to_encode,
        brein_config.SECRET_KEY,
        algorithm=brein_config.ALGORITHM,
    )
    return str(encoded_jwt)


async def get_user_from_token(token: str | None) -> User | None:
    """Decode JWT and load user from DB; return User if valid, else None. Used for WebSocket auth."""
    if not token or not brein_config.SECRET_KEY:
        return None
    try:
        payload = jwt.decode(
            token,
            brein_config.SECRET_KEY,
            algorithms=[brein_config.ALGORITHM],
        )
        username: str | None = payload.get("sub")
        if username is None:
            return None
        jti = payload.get("jti")
        if jti and await store_blacklist.is_blacklisted(jti):
            return None
        row = await store_users.get_user_by_username(username)
        if not row:
            return None
        return _user_from_row(row)
    except InvalidTokenError:
        return None


async def get_current_user(
    token: Annotated[str, Depends(get_token_cookie_or_bearer)],
) -> User:
    """Decode JWT, load user from DB; raise 401 if invalid or user missing.

    Accepts the token from either the Authorization header or the
    ``brein_access_token`` cookie. There used to be two parallel dependency
    hierarchies — bearer-only and cookie-or-bearer — and which one a route got
    was effectively arbitrary. Cookie-authenticated writes are covered by the
    CSRF middleware, so accepting both here costs nothing.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    user = await get_user_from_token(token)
    if user is None:
        raise credentials_exception
    return user


async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Require non-disabled user; raise 400 if disabled."""
    if current_user.disabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user",
        )
    return current_user


async def get_current_user_optional(
    token: Annotated[str | None, Depends(oauth2_scheme_optional)],
) -> User | None:
    """Return User if valid Bearer token present, else None (no 401)."""
    if not token:
        return None
    try:
        return await get_current_user(token)
    except HTTPException:
        return None


async def get_current_admin_user(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> User:
    """Require admin user; raise 403 if not admin."""
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin required",
        )
    return current_user


# Kept as names because routers import them, but they are now the same
# dependency: get_current_user accepts cookie or Bearer, so the "cookie_or_"
# variants no longer differ. Aliasing rather than duplicating means the two
# cannot drift apart again.
get_current_admin_user_cookie_or_bearer = get_current_admin_user


get_current_user_cookie_or_bearer = get_current_active_user
