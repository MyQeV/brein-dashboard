"""ServiceConfig CRUD and service metadata registry."""

from collections.abc import Mapping
from typing import Any

from sqlalchemy import text

from brein.db import get_session_factory


def service_meta() -> dict[str, dict[str, Any]]:
    from brein.extensions import load_extensions

    return {
        sid: {"name": st.name, "category": st.category, "default_port": st.default_port}
        for sid, st in load_extensions().service_types.items()
    }


class _MetaView(Mapping[str, dict[str, Any]]):
    """`SERVICE_META` stays importable; it reads the registry on access.

    Only the three primitives `Mapping` requires are implemented — `get`,
    `items`, `keys`, `values`, `__contains__` and `__eq__` come from the ABC
    and are correct by construction. A plain `dict` subclass instead would
    silently fall through to the (permanently empty) base dict for anything
    it doesn't override, e.g. `.copy()`, `repr()`, `==` or `json.dumps`.
    """

    def __getitem__(self, key: str) -> dict[str, Any]:
        return service_meta()[key]

    def __iter__(self):
        return iter(service_meta())

    def __len__(self) -> int:
        return len(service_meta())


# Known service types: id -> { name, category, default_port }; reads the
# extension registry (brein.extensions) on every access so it always
# reflects core + whatever brein.extras registers.
SERVICE_META: Mapping[str, dict[str, Any]] = _MetaView()


async def get_config(service_id: str) -> dict[str, Any] | None:
    """Return stored config for service_id or None."""
    if service_id not in SERVICE_META:
        return None
    async with get_session_factory()() as session:
        result = await session.execute(
            text(
                "SELECT base_url, api_key FROM service_config WHERE service_id = :sid"
            ),
            {"sid": service_id},
        )
        row = result.mappings().fetchone()
        return dict(row) if row else None


async def set_config(service_id: str, base_url: str, api_key: str) -> None:
    """Save config for service_id."""
    if service_id not in SERVICE_META:
        raise ValueError(f"Unknown service_id: {service_id}")
    async with get_session_factory()() as session:
        await session.execute(
            text(
                "INSERT INTO service_config (service_id, base_url, api_key)"
                " VALUES (:service_id, :base_url, :api_key)"
                " ON CONFLICT (service_id) DO UPDATE SET"
                " base_url = EXCLUDED.base_url, api_key = EXCLUDED.api_key"
            ),
            {
                "service_id": service_id,
                "base_url": base_url.strip(),
                "api_key": api_key,
            },
        )
        await session.commit()


async def list_services() -> list[dict[str, Any]]:
    """Return list of known services with has_config set."""
    async with get_session_factory()() as session:
        result = await session.execute(text("SELECT service_id FROM service_config"))
        configured = {row[0] for row in result.fetchall()}
    return [
        {
            "id": sid,
            "name": meta["name"],
            "category": meta["category"],
            "has_config": sid in configured,
        }
        for sid, meta in SERVICE_META.items()
    ]
