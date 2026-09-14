"""User preferences API: load and save per-user key/value settings."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from brein.store import user_preferences as store
from brein.web import auth as web_auth
from brein.web.schemas import User

router = APIRouter()
CurrentUser = Annotated[User, Depends(web_auth.get_current_active_user)]

# Guard against runaway storage
_MAX_KEY_LEN = 128
_MAX_VALUE_LEN = 65_536


class PrefValue(BaseModel):
    value: Any


@router.get("/api/user/preferences")
async def get_preferences(current_user: CurrentUser) -> dict[str, Any]:
    """Return all preferences for the authenticated user."""
    return await store.get_all(current_user.id)


@router.delete("/api/user/preferences", status_code=204)
async def delete_preferences_by_prefix(
    prefix: str,
    current_user: CurrentUser,
) -> None:
    """Delete all preferences whose key starts with prefix."""
    if len(prefix) > _MAX_KEY_LEN:
        raise HTTPException(status_code=400, detail="Prefix too long")
    await store.delete_by_prefix(current_user.id, prefix)


@router.delete("/api/user/preferences/{key}", status_code=204)
async def delete_preference(
    key: str,
    current_user: CurrentUser,
) -> None:
    """Delete a single preference."""
    await store.delete_preference(current_user.id, key)


@router.put("/api/user/preferences/{key}", status_code=204)
async def set_preference(
    key: str,
    body: PrefValue,
    current_user: CurrentUser,
) -> None:
    """Upsert a single preference for the authenticated user."""
    if len(key) > _MAX_KEY_LEN:
        raise HTTPException(status_code=400, detail="Key too long")
    import json

    if len(json.dumps(body.value)) > _MAX_VALUE_LEN:
        raise HTTPException(status_code=400, detail="Value too large")
    await store.set_preference(current_user.id, key, body.value)
