"""Pydantic models for service config and list."""

from pydantic import BaseModel


class ServiceConfigBody(BaseModel):
    base_url: str
    api_key: str


class ServiceConfigResponse(BaseModel):
    base_url: str
    api_key_masked: str  # e.g. "***" or last 4 chars


class ServiceInfo(BaseModel):
    id: str
    name: str
    category: str  # "media_servers" | "media_management" | "user_management"
    has_config: bool
