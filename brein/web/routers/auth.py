"""Auth routes: token (login), refresh, users/me, one-time setup."""

import asyncio
import time
from datetime import timedelta
from typing import Annotated, Literal

from fastapi import (
    APIRouter,
    Body,
    Depends,
    Form,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm

from pydantic import BaseModel, Field

import jwt
from jwt.exceptions import InvalidTokenError

from brein import config as brein_config
from brein.store import blacklist as store_blacklist
from brein.store import refresh_tokens as store_refresh_tokens
from brein.store import users as store_users
from brein.web import auth as web_auth
from brein.web import csrf
from brein.web.on_login_tasks import run_on_login_tasks
from brein.web.password_policy import validate_password_for_user
from brein.web.rate_limit import get_client_ip, limiter
from brein.web.schemas import RefreshRequest, Token, User

router = APIRouter(tags=["auth"])

_setup_lock = asyncio.Lock()


class SetupRequest(BaseModel):
    """One-time setup: create first admin user."""

    username: str = Field(max_length=64)
    password: str = Field(max_length=256)
    email: str | None = Field(default=None, max_length=254)
    full_name: str | None = Field(default=None, max_length=128)


class CreateUserRequest(BaseModel):
    """Create user (admin only)."""

    username: str = Field(max_length=64)
    password: str = Field(max_length=256)
    email: str | None = Field(default=None, max_length=254)
    full_name: str | None = Field(default=None, max_length=128)
    is_admin: bool = False
    # role overrides is_admin when provided
    role: Literal["admin", "viewer", "user"] | None = None


class UpdateUserRoleStatusRequest(BaseModel):
    """Update another user's role and enabled state (admin only)."""

    role: Literal["admin", "viewer", "user"]
    disabled: bool = False


class UpdateProfileRequest(BaseModel):
    """Update current user profile (email, full_name only)."""

    email: str | None = None
    full_name: str | None = None


class ChangePasswordRequest(BaseModel):
    """Change current user password."""

    current_password: str
    new_password: str


class LogoutBody(BaseModel):
    """Optional body for logout: revoke refresh token."""

    refresh_token: str | None = None


def _parse_remember_me(value: str | None) -> bool:
    """Parse remember_me form value (checkbox sends 'on' or 'true' when checked)."""
    if value is None or not str(value).strip():
        return False
    return str(value).strip().lower() in ("true", "on", "1", "yes")


def _set_csrf_cookie(request: Request, response: Response) -> None:
    """Issue the CSRF token alongside the auth cookies.

    It has to be set here, not only by the middleware: the signed-in shell
    renders server-side, and those responses go Next-server-to-API, so their
    Set-Cookie headers never reach the browser. Without this, the first write
    after a fresh login has no token to send and is refused.
    """
    token = request.cookies.get(csrf.COOKIE_NAME) or csrf.new_token()
    response.set_cookie(
        key=csrf.COOKIE_NAME,
        value=token,
        path="/",
        # Readable by JS on purpose: the double-submit scheme needs the page to
        # echo it back. It is not a credential on its own.
        httponly=False,
        samesite="lax",
        secure=brein_config.COOKIE_SECURE,
    )


@router.post("/token", response_model=Token)
@limiter.limit("10/minute")
async def login_for_access_token(
    request: Request,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    remember_me: Annotated[str | None, Form()] = None,
) -> Token:
    """OAuth2 password flow: exchange username/password for access + refresh token."""
    if not brein_config.SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth not configured (SECRET_KEY missing)",
        )
    # Through the same resolver the rate limiter uses. `request.client.host`
    # is the immediate peer, which behind the frontend's rewrite proxy is
    # always the proxy — so every user's last_login_ip read as one container
    # address and a brute-force attempt looked like ordinary traffic.
    _ip = get_client_ip(request)
    _ua = request.headers.get("user-agent", "")
    user, failed_user_id = await web_auth.authenticate_user(
        form_data.username, form_data.password
    )
    if not user:
        if failed_user_id is not None:
            await store_users.record_login_failure(
                failed_user_id, ip=_ip, user_agent=_ua
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    await store_users.record_login_success(user.id, ip=_ip, user_agent=_ua)
    access_token_expires = timedelta(minutes=brein_config.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = web_auth.create_access_token(
        data={"sub": user.username},
        expires_delta=access_token_expires,
    )
    remember_me_bool = _parse_remember_me(remember_me)
    refresh_days = (
        brein_config.REFRESH_TOKEN_EXPIRE_DAYS
        if remember_me_bool
        else brein_config.REFRESH_TOKEN_EXPIRE_DAYS_SESSION
    )
    expires_at = time.time() + (refresh_days * 24 * 3600)
    refresh_plaintext, _ = await store_refresh_tokens.create(user.id, expires_at)
    run_on_login_tasks()
    content = {
        "access_token": access_token,
        "token_type": "bearer",
        "refresh_token": refresh_plaintext,
    }
    response = JSONResponse(content=content)
    cookie_max_age = brein_config.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    response.set_cookie(
        key=web_auth.ACCESS_TOKEN_COOKIE_NAME,
        value=access_token,
        max_age=cookie_max_age,
        path="/",
        httponly=True,
        samesite="lax",
        secure=brein_config.COOKIE_SECURE,
    )
    response.set_cookie(
        key=web_auth.REFRESH_TOKEN_COOKIE_NAME,
        value=refresh_plaintext,
        max_age=refresh_days * 24 * 3600,
        path="/",
        httponly=True,
        samesite="lax",
        secure=brein_config.COOKIE_SECURE,
    )
    _set_csrf_cookie(request, response)
    return response


@router.post("/refresh", response_model=Token)
@limiter.limit("20/minute")
async def refresh_access_token(
    request: Request,
    body: RefreshRequest | None = Body(default=None),
) -> Token:
    """Exchange a valid refresh token for a new access token. Rotates the refresh token."""
    if not brein_config.SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth not configured (SECRET_KEY missing)",
        )
    effective = body or RefreshRequest()
    refresh_plaintext = (
        request.cookies.get(web_auth.REFRESH_TOKEN_COOKIE_NAME)
        or (effective.refresh_token or "").strip()
    )
    if not refresh_plaintext:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token_info = await store_refresh_tokens.get_token_info(refresh_plaintext)
    if not token_info:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_id = str(token_info["user_id"])
    expires_at = float(token_info["expires_at"])
    row = await store_users.get_user_by_id(user_id)
    if not row or row.get("disabled"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or disabled",
            headers={"WWW-Authenticate": "Bearer"},
        )
    username = row.get("username") or ""
    # Rotate: create new token first, then revoke old one
    # Order matters: if create fails, old token remains valid (no session loss)
    new_refresh_plaintext, _ = await store_refresh_tokens.create(user_id, expires_at)
    await store_refresh_tokens.revoke_by_token(refresh_plaintext)
    access_token_expires = timedelta(minutes=brein_config.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = web_auth.create_access_token(
        data={"sub": username},
        expires_delta=access_token_expires,
    )
    content = {
        "access_token": access_token,
        "token_type": "bearer",
        "refresh_token": new_refresh_plaintext,
    }
    response = JSONResponse(content=content)
    cookie_max_age = brein_config.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    response.set_cookie(
        key=web_auth.ACCESS_TOKEN_COOKIE_NAME,
        value=access_token,
        max_age=cookie_max_age,
        path="/",
        httponly=True,
        samesite="lax",
        secure=brein_config.COOKIE_SECURE,
    )
    response.set_cookie(
        key=web_auth.REFRESH_TOKEN_COOKIE_NAME,
        value=new_refresh_plaintext,
        max_age=max(0, int(expires_at - time.time())),
        path="/",
        httponly=True,
        samesite="lax",
        secure=brein_config.COOKIE_SECURE,
    )
    _set_csrf_cookie(request, response)
    return response


@router.get("/users/me", response_model=User)
async def read_users_me(
    current_user: Annotated[User, Depends(web_auth.get_current_active_user)],
) -> User:
    """Return current authenticated user."""
    return current_user


@router.patch("/users/me", response_model=User)
async def update_profile(
    body: UpdateProfileRequest,
    current_user: Annotated[User, Depends(web_auth.get_current_active_user)],
) -> User:
    """Update current user profile (email, full_name). Username cannot be changed."""
    await store_users.update_user(
        current_user.id,
        email=body.email,
        full_name=body.full_name,
    )
    row = await store_users.get_user_by_id(current_user.id)
    if not row:
        raise HTTPException(status_code=500, detail="User not found")
    return web_auth._user_from_row(row)


@router.post("/users/me/change-password", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("5/minute")
async def change_password(
    request: Request,
    body: ChangePasswordRequest,
    current_user: Annotated[User, Depends(web_auth.get_current_active_user)],
) -> None:
    """Change current user password."""
    row = await store_users.get_user_by_id(current_user.id)
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    if not web_auth.verify_password(body.current_password, row["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )
    try:
        validate_password_for_user(
            body.new_password,
            username=current_user.username,
            full_name=row.get("full_name"),
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    hashed = web_auth.get_password_hash(body.new_password)
    await store_users.update_user(current_user.id, hashed_password=hashed)
    await store_refresh_tokens.revoke_all_for_user(current_user.id)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    token_header: Annotated[str | None, Depends(web_auth.oauth2_scheme_optional)],
    body: LogoutBody | None = None,
) -> Response:
    """Invalidate the access token (blacklist), clear auth cookie, and optionally revoke the refresh token."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    token = token_header or request.cookies.get(web_auth.ACCESS_TOKEN_COOKIE_NAME)
    if not brein_config.SECRET_KEY:
        raise credentials_exception
    if not token:
        response = Response(status_code=status.HTTP_204_NO_CONTENT)
        response.delete_cookie(
            web_auth.ACCESS_TOKEN_COOKIE_NAME,
            path="/",
            secure=brein_config.COOKIE_SECURE,
        )
        response.delete_cookie(
            web_auth.REFRESH_TOKEN_COOKIE_NAME,
            path="/",
            secure=brein_config.COOKIE_SECURE,
        )
        return response
    try:
        payload = jwt.decode(
            token,
            brein_config.SECRET_KEY,
            algorithms=[brein_config.ALGORITHM],
        )
    except InvalidTokenError:
        raise credentials_exception
    jti = payload.get("jti")
    exp = payload.get("exp")
    refresh_token_val = (body.refresh_token or "").strip() if body else ""
    if not refresh_token_val:
        refresh_token_val = request.cookies.get(web_auth.REFRESH_TOKEN_COOKIE_NAME, "")
    if jti is not None and exp is not None and refresh_token_val:
        await asyncio.gather(
            store_blacklist.add_to_blacklist(jti, float(exp)),
            store_refresh_tokens.revoke_by_token(refresh_token_val),
        )
    elif jti is not None and exp is not None:
        await store_blacklist.add_to_blacklist(jti, float(exp))
    elif refresh_token_val:
        await store_refresh_tokens.revoke_by_token(refresh_token_val)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(
        web_auth.ACCESS_TOKEN_COOKIE_NAME, path="/", secure=brein_config.COOKIE_SECURE
    )
    response.delete_cookie(
        web_auth.REFRESH_TOKEN_COOKIE_NAME, path="/", secure=brein_config.COOKIE_SECURE
    )
    return response


@router.post("/api/setup", status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def first_time_setup(request: Request, body: SetupRequest) -> dict:
    """Create first admin user when no users exist. Returns 403 once any user exists."""
    async with _setup_lock:
        if await store_users.count_users() != 0:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Setup already completed",
            )
        username = (body.username or "").strip()
        password = body.password or ""
        if not username:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="username is required",
            )
        try:
            validate_password_for_user(
                password, username=username, full_name=body.full_name
            )
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )
        try:
            hashed = web_auth.get_password_hash(password)
            await store_users.create_user(
                username=username,
                hashed_password=hashed,
                email=body.email,
                full_name=body.full_name,
                is_admin=True,
            )
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )
    return {
        "message": "Admin user created. You can now log in.",
        "username": username,
    }


def _user_dict_from_row(row: dict) -> dict:
    """Convert store user row to API user dict (no hashed_password)."""
    return {
        "id": row["id"],
        "username": row["username"],
        "email": row.get("email"),
        "full_name": row.get("full_name"),
        "disabled": bool(row.get("disabled", 0)),
        "is_admin": bool(row.get("is_admin", 0)),
        "role": row.get("role") or "user",
        "created_at": row.get("created_at"),
        "last_login_at": row.get("last_login_at"),
        "last_failed_login_at": row.get("last_failed_login_at"),
        "failed_login_attempts": row.get("failed_login_attempts") or 0,
        "last_login_ip": row.get("last_login_ip"),
    }


@router.get("/api/users")
async def list_users_api(
    current_user: Annotated[User, Depends(web_auth.get_current_admin_user)],
) -> dict:
    """List all users (admin only). Returns users without passwords."""
    rows = await store_users.list_users()
    return {"users": [_user_dict_from_row(r) for r in rows]}


@router.get("/api/users/{user_id}")
async def get_user_api(
    user_id: str,
    current_user: Annotated[User, Depends(web_auth.get_current_admin_user)],
) -> dict:
    """Return one user (admin only)."""
    row = await store_users.get_user_by_id(user_id)
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return _user_dict_from_row(row)


@router.patch("/api/users/{user_id}")
async def update_user_role_status_api(
    user_id: str,
    body: UpdateUserRoleStatusRequest,
    current_user: Annotated[User, Depends(web_auth.get_current_admin_user)],
) -> dict:
    """Update a user's role and enabled state (admin only).

    An admin cannot change their own role or disable themselves here: doing so
    is how an instance ends up with no administrator, and the mistake is not
    recoverable from the UI.
    """
    if current_user.id == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot change your own role or status.",
        )
    try:
        await store_users.update_user_role_status(
            user_id, role=body.role, disabled=body.disabled
        )
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(
            status_code=(404 if detail == "User not found" else 400), detail=detail
        ) from exc
    row = await store_users.get_user_by_id(user_id)
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return _user_dict_from_row(row)


@router.post("/api/users", status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def create_user_api(
    request: Request,
    body: CreateUserRequest,
    current_user: Annotated[User, Depends(web_auth.get_current_admin_user)],
) -> dict:
    """Create a new user (admin only)."""
    username = (body.username or "").strip()
    password = body.password or ""
    if not username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="username is required",
        )
    try:
        validate_password_for_user(
            password, username=username, full_name=body.full_name
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    try:
        hashed = web_auth.get_password_hash(password)
        await store_users.create_user(
            username=username,
            hashed_password=hashed,
            email=body.email,
            full_name=body.full_name,
            is_admin=body.is_admin,
            role=body.role,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    row = await store_users.get_user_by_username(username)
    if not row:
        raise HTTPException(status_code=500, detail="User created but not found")
    return _user_dict_from_row(dict(row))
