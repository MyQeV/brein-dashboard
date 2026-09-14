"""Import Emby users as Brein viewer accounts."""

import re
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from brein.store import users as store_users
from brein.integrations import emby as emby_integration
from brein.integrations.api import jellyfin as jellyfin_integration
from brein.web import auth as web_auth
from brein.web.dependencies import require_instance_config
from brein.web.schemas import User

router = APIRouter(tags=["users-import"])

AdminUser = Annotated[User, Depends(web_auth.get_current_admin_user)]


def _media_integration(service_type: str):
    return jellyfin_integration if service_type == "jellyfin" else emby_integration


def _sanitize_username(name: str) -> str:
    """Convert an Emby display name to a valid Brein username.

    Rules: lowercase, replace spaces/hyphens with underscores, keep only
    alphanumeric and underscore characters, collapse repeated underscores,
    strip leading/trailing underscores.
    """
    s = (name or "").strip().lower()
    s = re.sub(r"[\s\-]+", "_", s)
    s = re.sub(r"[^a-z0-9_]", "", s)
    s = re.sub(r"_+", "_", s)
    s = s.strip("_")
    return s


def _unique_username(base: str, existing: set[str]) -> str | None:
    """Return a username not in *existing*. Returns None if base is empty."""
    if not base:
        return None
    candidate = base
    suffix = 2
    while candidate in existing:
        candidate = f"{base}_{suffix}"
        suffix += 1
        if suffix > 999:
            return None
    return candidate


class EmbyUserListItem(BaseModel):
    """Single Emby user row returned by GET /api/users/emby-users."""

    emby_name: str
    disabled_in_emby: bool
    already_imported: bool


class ImportFromEmbyRequest(BaseModel):
    """Body for POST /api/users/import-from-emby."""

    instance_id: int
    # Optional list of Emby display names to import; None means import all active.
    emby_names: list[str] | None = None


class ImportedUser(BaseModel):
    emby_name: str
    username: str


class SkippedUser(BaseModel):
    emby_name: str
    reason: str


class ImportResult(BaseModel):
    created: list[ImportedUser]
    skipped: list[SkippedUser]
    errors: list[dict]
    dry_run: bool


@router.get("/api/users/emby-users", response_model=list[EmbyUserListItem])
async def list_emby_users(
    instance_id: int,
    current_user: AdminUser,
) -> list[EmbyUserListItem]:
    """Return all Emby/Jellyfin users for an instance with import-eligibility flags."""
    service_type, base_url, api_key = await require_instance_config(instance_id)
    if service_type not in ("emby", "jellyfin"):
        raise HTTPException(
            status_code=400, detail="Instance is not an Emby or Jellyfin server"
        )
    ok, raw_users = await _media_integration(service_type).get_users(base_url, api_key)
    if not ok or raw_users is None:
        raise HTTPException(
            status_code=502, detail="Failed to fetch users from media server"
        )

    existing_usernames = await store_users.get_usernames_set()
    result: list[EmbyUserListItem] = []
    for emby_user in raw_users:
        if not isinstance(emby_user, dict):
            continue
        emby_name = (emby_user.get("Name") or "").strip()
        if not emby_name:
            continue
        policy = emby_user.get("Policy") or {}
        sanitized = _sanitize_username(emby_name)
        already_imported = sanitized in existing_usernames
        result.append(
            EmbyUserListItem(
                emby_name=emby_name,
                disabled_in_emby=bool(policy.get("IsDisabled")),
                already_imported=already_imported,
            )
        )
    return result


@router.post("/api/users/import-from-emby", response_model=ImportResult)
async def import_emby_users(
    body: ImportFromEmbyRequest,
    current_user: AdminUser,
) -> ImportResult:
    """Import selected Emby/Jellyfin users from the given instance as Brein viewer accounts.

    Users log in using their media server password (passthrough auth).
    Already-existing usernames and disabled accounts are skipped.
    """
    service_type, base_url, api_key = await require_instance_config(body.instance_id)
    if service_type not in ("emby", "jellyfin"):
        raise HTTPException(
            status_code=400, detail="Instance is not an Emby or Jellyfin server"
        )
    ok, raw_users = await _media_integration(service_type).get_users(base_url, api_key)
    if not ok or raw_users is None:
        raise HTTPException(
            status_code=502, detail="Failed to fetch users from media server"
        )

    reserved = await store_users.get_usernames_set()

    created: list[ImportedUser] = []
    skipped: list[SkippedUser] = []
    errors: list[dict] = []

    for emby_user in raw_users:
        if not isinstance(emby_user, dict):
            continue
        emby_name: str = (emby_user.get("Name") or "").strip()
        if not emby_name:
            skipped.append(SkippedUser(emby_name="(unnamed)", reason="no display name"))
            continue

        if body.emby_names is not None and emby_name not in body.emby_names:
            continue

        policy = emby_user.get("Policy") or {}
        if policy.get("IsDisabled"):
            skipped.append(
                SkippedUser(emby_name=emby_name, reason="account is disabled")
            )
            continue

        username = _unique_username(_sanitize_username(emby_name), reserved)
        if username is None:
            skipped.append(
                SkippedUser(
                    emby_name=emby_name,
                    reason="could not generate a unique username",
                )
            )
            continue

        try:
            placeholder_hash = web_auth.get_password_hash(secrets.token_hex(32))
            if service_type == "jellyfin":
                await store_users.create_user(
                    username=username,
                    hashed_password=placeholder_hash,
                    full_name=emby_name,
                    role=store_users.ROLE_VIEWER,
                    jellyfin_instance_id=body.instance_id,
                    jellyfin_username=emby_name,
                )
            else:
                await store_users.create_user(
                    username=username,
                    hashed_password=placeholder_hash,
                    full_name=emby_name,
                    role=store_users.ROLE_VIEWER,
                    emby_instance_id=body.instance_id,
                    emby_username=emby_name,
                )
            reserved.add(username)
            created.append(ImportedUser(emby_name=emby_name, username=username))
        except ValueError as exc:
            errors.append(
                {"emby_name": emby_name, "username": username, "error": str(exc)}
            )

    return ImportResult(
        created=created,
        skipped=skipped,
        errors=errors,
        dry_run=False,
    )
