"""The seam between core and the optional integrations.

Core registers its own service types here (`brein.core_services`); every
package named in `brein.extras.EXTRAS` registers its own through the same
object. Consumers (`app.py`, the service registry, the task registry, the
downloads router) read this instead of naming services, so a tree without
`brein/extras` still boots.
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol

if TYPE_CHECKING:
    from fastapi import APIRouter

    from brein.jobs.scheduled_task_registry import TaskType

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Tab:
    slug: str
    label: str
    admin_only: bool = False


@dataclass
class ServiceType:
    id: str
    name: str
    category: str
    default_port: int | None
    test_connection: Callable[[str, str], Awaitable[tuple[bool, str]]]
    icon: bool = True
    tabs: list[Tab] = field(default_factory=list)
    arr_tables: dict[str, Any] | None = None


@dataclass(frozen=True)
class DownloaderCapabilities:
    per_item_pause: bool
    queue_level_pause: bool
    history: Literal["list", "none"]


class UnsupportedOperation(Exception):
    """The downloader has no such action; the router answers 400 with the message."""


class Downloader(Protocol):
    capabilities: DownloaderCapabilities

    async def queue(
        self, base_url: str, api_key: str
    ) -> tuple[bool, dict[str, Any]]: ...
    async def history(
        self, base_url: str, api_key: str
    ) -> tuple[bool, list[dict[str, Any]]]: ...
    async def pause(
        self, base_url: str, api_key: str, item_id: str | None
    ) -> tuple[bool, str]: ...
    async def resume(
        self, base_url: str, api_key: str, item_id: str | None
    ) -> tuple[bool, str]: ...
    async def delete(
        self, base_url: str, api_key: str, item_id: str, remove_files: bool
    ) -> tuple[bool, str]: ...
    async def status(
        self, base_url: str, api_key: str
    ) -> tuple[bool, dict[str, Any]]: ...
    async def set_speed_limit(
        self, base_url: str, api_key: str, value: int
    ) -> tuple[bool, str]: ...


InstanceSettingsHook = Callable[[str, str, int | None], Awaitable[dict[str, Any]]]


class Extension:
    def __init__(self) -> None:
        self.service_types: dict[str, ServiceType] = {}
        self.routers: list[APIRouter] = []
        self.task_types: dict[str, TaskType] = {}
        self.models: list[type] = []
        self.downloaders: dict[str, Downloader] = {}
        self.instance_settings: dict[str, InstanceSettingsHook] = {}

    def add_service_type(self, service_type: ServiceType) -> None:
        self.service_types[service_type.id] = service_type

    def add_router(self, router: APIRouter) -> None:
        self.routers.append(router)

    def add_task_type(self, task_type: TaskType) -> None:
        self.task_types[task_type.key] = task_type

    def add_models(self, *tables: type) -> None:
        self.models.extend(tables)

    def add_downloader(self, service_id: str, downloader: Downloader) -> None:
        self.downloaders[service_id] = downloader

    def add_instance_settings(
        self, service_id: str, hook: InstanceSettingsHook
    ) -> None:
        self.instance_settings[service_id] = hook


_loaded: Extension | None = None


def load_extensions() -> Extension:
    """Core first, then every package listed in `brein.extras.EXTRAS`."""
    global _loaded
    if _loaded is not None:
        return _loaded
    ext = Extension()
    from brein import core_services

    core_services.register(ext)
    from brein import extras

    for name in extras.EXTRAS:
        module = importlib.import_module(f"brein.extras.{name}")
        module.register(ext)
        log.info("Loaded extra: %s", name)
    _loaded = ext
    return ext


def reset_extensions() -> None:
    """Tests only."""
    global _loaded
    _loaded = None
