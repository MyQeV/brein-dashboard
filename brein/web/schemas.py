"""Pydantic request bodies shared by web routers."""

from urllib.parse import urlparse

from pydantic import BaseModel, field_validator


class ServiceConfigBody(BaseModel):
    base_url: str = ""
    api_key: str = ""


class InstanceUpdateBody(BaseModel):
    host: str | None = None
    port: int | None = None
    api_key: str | None = None
    label: str | None = None
    external_url: str | None = None
    active: bool | None = None
    sort_order: int | None = None

    @field_validator("external_url")
    @classmethod
    def _external_url_is_a_web_address(cls, value: str | None) -> str | None:
        """Only http(s), because this value becomes an href for everyone.

        The pages that link to a media server render this URL for every
        viewer, so a `javascript:` address saved here would run in someone
        else's session when they clicked it — an admin reaching into other
        people's sessions. An allowlist rather than a denylist: `data:` and
        `vbscript:` are excluded by saying what is permitted.
        """
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            return trimmed
        parsed = urlparse(trimmed)
        if parsed.scheme.lower() not in ("http", "https"):
            raise ValueError("external_url must start with http:// or https://")
        return trimmed


class InstanceCreateBody(InstanceUpdateBody):
    """The connection may come along with the type: it is tested before it is stored."""

    service_type: str = ""


class InstanceProbeBody(BaseModel):
    """A connection to try before any instance exists."""

    service_type: str = ""
    host: str = ""
    port: int | None = None
    api_key: str = ""


class UsersPolicyBody(BaseModel):
    user_ids: list[str]
    enable_all_folders: bool | None = None
    enabled_folder_ids: list[str] | None = None


class UpdateUserRequest(BaseModel):
    name: str | None = None
    new_password: str | None = None
    is_administrator: bool | None = None
    enable_live_tv: bool | None = None
    enable_live_tv_management: bool | None = None
    max_simultaneous_streams: int | None = None
    enable_all_folders: bool | None = None
    enabled_folder_ids: list[str] | None = None
    is_hidden: bool | None = None
    is_hidden_remotely: bool | None = None
    is_hidden_from_unused_devices: bool | None = None
    is_disabled: bool | None = None
    remote_client_bitrate_limit: int | None = None
    auto_remote_quality: int | None = None


class BulkStatusRequest(BaseModel):
    user_ids: list[str]
    is_disabled: bool


# Auth: user and token models
class User(BaseModel):
    """User returned to client (no password)."""

    id: str
    username: str
    email: str | None = None
    full_name: str | None = None
    disabled: bool = False
    is_admin: bool = False
    # role: 'admin' | 'viewer' | 'user'
    role: str = "user"


class UserInDB(User):
    """User with hashed_password (internal)."""

    hashed_password: str


class Token(BaseModel):
    """OAuth2 token response (login). Cookie-flow responses carry only
    token_type; the tokens travel in the cookies."""

    access_token: str | None = None
    token_type: str
    refresh_token: str | None = None


class RefreshRequest(BaseModel):
    """Body for POST /refresh."""

    refresh_token: str | None = None
