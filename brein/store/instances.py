"""AppInstance CRUD and connection config helpers."""

import logging
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import text

from brein.db import get_session_factory
from brein.store.service_config import SERVICE_META

log = logging.getLogger(__name__)


def _normalize_host_url(host: str) -> tuple[str, int | None, str]:
    """If host looks like http(s):// URL, parse and return (hostname, port or None, scheme). Else return (host, None, 'http')."""
    host = (host or "").strip()
    if not host or not host.startswith(("http://", "https://")):
        return (host, None, "http")
    parsed = urlparse(host)
    hostname = (parsed.hostname or "").strip()
    if not hostname:
        return (host, None, "http")
    port = parsed.port
    scheme = parsed.scheme if parsed.scheme in ("http", "https") else "http"
    return (hostname, port, scheme)


def build_base_url(
    host: str, port: int | None, service_type: str, scheme: str = "http"
) -> str:
    """Build base_url from host and port. Accepts host or full URL (http(s)://...); use SERVICE_META default_port if port is None."""
    host = (host or "").strip()
    if not host:
        return ""
    host, url_port, url_scheme = _normalize_host_url(host)
    if not host:
        return ""
    if url_port is not None:
        port = url_port
        scheme = url_scheme
    else:
        scheme = url_scheme
        if port is None:
            meta = SERVICE_META.get(service_type, {})
            default_port = (
                meta.get("default_port")
                if isinstance(meta.get("default_port"), int)
                else 80
            )
            port = 443 if scheme == "https" else default_port
    if (scheme == "https" and port == 443) or (scheme == "http" and port == 80):
        return f"{scheme}://{host}"
    return f"{scheme}://{host}:{port}"


async def list_instances() -> list[dict[str, Any]]:
    """Return all app instances with is_configured (host and api_key set)."""
    async with get_session_factory()() as session:
        result = await session.execute(
            text(
                "SELECT id, service_type, label, host, port, api_key, external_url, active,"
                " COALESCE(sort_order, 0) AS sort_order,"
                " COALESCE(media_server_id, '') AS media_server_id"
                " FROM app_instances ORDER BY sort_order ASC, id"
            )
        )
        rows = result.mappings().fetchall()
    out = []
    for row in rows:
        d = dict(row)
        host = (d.get("host") or "").strip()
        api_key = (d.get("api_key") or "").strip()
        d["is_configured"] = bool(host and api_key)
        d["active"] = bool(d.get("active", 1))
        meta = SERVICE_META.get(d.get("service_type") or "", {})
        d["category"] = meta.get("category", "media_servers")
        d["service_name"] = meta.get("name", d.get("service_type", ""))
        external_url = (d.get("external_url") or "").strip()
        d["app_url"] = (
            external_url
            if external_url
            else build_base_url(host, d.get("port"), d.get("service_type") or "")
        )
        if "api_key" in d and d["api_key"]:
            d["api_key_masked"] = "\u2022" * 15
        else:
            d["api_key_masked"] = ""
        del d["api_key"]
        out.append(d)
    return out


async def get_instance(
    instance_id: int, mask_api_key: bool = True
) -> dict[str, Any] | None:
    """Return one instance by id. By default the api_key is masked."""
    async with get_session_factory()() as session:
        result = await session.execute(
            text(
                "SELECT id, service_type, label, host, port, api_key, external_url, active,"
                " COALESCE(sort_order, 0) AS sort_order,"
                " COALESCE(media_server_id, '') AS media_server_id"
                " FROM app_instances WHERE id = :instance_id"
            ),
            {"instance_id": instance_id},
        )
        row = result.mappings().fetchone()
    if not row:
        return None
    d = dict(row)
    key = (d.get("api_key") or "").strip()
    d["is_configured"] = bool((d.get("host") or "").strip() and key)
    d["active"] = bool(d.get("active", 1))
    external_url = (d.get("external_url") or "").strip()
    d["app_url"] = (
        external_url
        if external_url
        else build_base_url(
            (d.get("host") or "").strip(), d.get("port"), d.get("service_type") or ""
        )
    )
    if mask_api_key:
        d["api_key_masked"] = "\u2022" * 15 if key else ""
        del d["api_key"]
    return d


async def create_instance(
    service_type: str,
    label: str | None = None,
    host: str = "",
    port: int | None = None,
    api_key: str = "",
    external_url: str = "",
    sort_order: int | None = None,
) -> int:
    """Create a new app instance. Returns the instance id (integer)."""
    if service_type not in SERVICE_META:
        raise ValueError(f"Unknown service_type: {service_type}")
    label_val = (label or "").strip() or service_type
    _, extracted_port, _ = _normalize_host_url(host or "")
    if extracted_port is not None and port is None:
        port = extracted_port
    host_to_store = (host or "").strip()
    async with get_session_factory()() as session:
        if sort_order is None:
            r = await session.execute(
                text("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM app_instances")
            )
            row = r.fetchone()
            sort_order = row[0] if row else 0
        result = await session.execute(
            text(
                "INSERT INTO app_instances"
                " (service_type, label, host, port, api_key, external_url, active, sort_order,"
                "  media_server_id, server_name, server_version)"
                " VALUES (:service_type, :label, :host, :port, :api_key, :external_url, false, :sort_order,"
                "  '', '', '')"
                " RETURNING id"
            ),
            {
                "service_type": service_type,
                "label": label_val,
                "host": host_to_store,
                "port": port,
                "api_key": api_key or "",
                "external_url": (external_url or "").strip(),
                "sort_order": sort_order,
            },
        )
        new_id = result.scalar()
        await session.commit()
    return new_id


async def update_instance(
    instance_id: int,
    host: str | None = None,
    port: int | None = None,
    api_key: str | None = None,
    label: str | None = None,
    external_url: str | None = None,
    active: bool | None = None,
    sort_order: int | None = None,
) -> None:
    """Update instance; None keeps existing value."""
    async with get_session_factory()() as session:
        r = await session.execute(
            text(
                "SELECT host, port, api_key, label, external_url, active,"
                " COALESCE(sort_order, 0) AS sort_order"
                " FROM app_instances WHERE id = :instance_id"
            ),
            {"instance_id": instance_id},
        )
        row = r.fetchone()
        if not row:
            raise ValueError(f"Instance not found: {instance_id}")
        cur_host, _, cur_key, cur_label, cur_external, cur_active, cur_sort = (
            row[0],
            row[1],
            row[2],
            row[3],
            (row[4] or ""),
            row[5],
            row[6],
        )
        new_host_raw = (host if host is not None else cur_host) or ""
        _, extracted_port, _ = _normalize_host_url(new_host_raw)
        if port is not None:
            new_port = port
        elif extracted_port is not None:
            new_port = extracted_port
        else:
            new_port = None
        new_key = api_key if api_key is not None else cur_key
        new_label = (label if label is not None else cur_label) or cur_label or ""
        new_external = (
            external_url if external_url is not None else cur_external
        ) or ""
        new_active = bool(active if active is not None else cur_active)
        new_sort = cur_sort if sort_order is None else sort_order
        await session.execute(
            text(
                "UPDATE app_instances"
                " SET host = :host, port = :port, api_key = :api_key, label = :label,"
                " external_url = :external_url, active = :active, sort_order = :sort_order"
                " WHERE id = :instance_id"
            ),
            {
                "host": new_host_raw.strip(),
                "port": new_port,
                "api_key": new_key or "",
                "label": new_label.strip(),
                "external_url": new_external.strip(),
                "active": new_active,
                "sort_order": new_sort,
                "instance_id": instance_id,
            },
        )
        await session.commit()


async def set_instance_server_info(
    instance_id: int,
    media_server_id: str | None = None,
    server_name: str | None = None,
    server_version: str | None = None,
) -> None:
    """Store server info from System/Info."""
    async with get_session_factory()() as session:
        r = await session.execute(
            text(
                "SELECT media_server_id, server_name, server_version"
                " FROM app_instances WHERE id = :instance_id"
            ),
            {"instance_id": instance_id},
        )
        row = r.fetchone()
        if not row:
            return
        cur_id, cur_name, cur_ver = (row[0] or ""), (row[1] or ""), (row[2] or "")
        new_id = (
            (media_server_id or "").strip() if media_server_id is not None else cur_id
        )
        new_name = (server_name or "").strip() if server_name is not None else cur_name
        new_ver = (
            (server_version or "").strip() if server_version is not None else cur_ver
        )
        await session.execute(
            text(
                "UPDATE app_instances"
                " SET media_server_id = :mid, server_name = :sname, server_version = :sver"
                " WHERE id = :instance_id"
            ),
            {
                "mid": new_id,
                "sname": new_name,
                "sver": new_ver,
                "instance_id": instance_id,
            },
        )
        await session.commit()


async def delete_instance(instance_id: int) -> bool:
    """Delete an app instance and, by cascade, everything synced for it.

    Every table with a NOT NULL ``instance_id`` has an ``ON DELETE CASCADE``
    foreign key to ``app_instances`` (see ``brein.db._ensure_instance_cascades``),
    so this one statement also removes the instance's users, items, playback
    sessions, metrics snapshots, activity log and scheduled tasks. Doing it in
    the schema rather than as a list of DELETEs here means a future delete path
    cannot forget it.

    ``users.emby_instance_id`` / ``users.jellyfin_instance_id`` are deliberately
    NOT cascaded: those are Brein login accounts, possibly admins. SET NULL would
    be worse than leaving them — it would silently turn a passthrough account
    into a local one whose password is an unguessable placeholder. ``web.auth``
    already denies login when the referenced instance is gone.

    Returns True if an instance row was actually deleted.
    """
    async with get_session_factory()() as session:
        result = await session.execute(
            text("DELETE FROM app_instances WHERE id = :instance_id RETURNING id"),
            {"instance_id": instance_id},
        )
        deleted = result.fetchone() is not None
        await session.commit()
    if deleted:
        log.info("Deleted instance %s and all data cascading from it", instance_id)
    return deleted


async def get_instance_connection_config(
    instance_id: int,
) -> tuple[str, str, str] | None:
    """Return (service_type, base_url, api_key) for an instance; None if not found."""
    async with get_session_factory()() as session:
        result = await session.execute(
            text(
                "SELECT service_type, host, port, api_key"
                " FROM app_instances WHERE id = :instance_id"
            ),
            {"instance_id": instance_id},
        )
        row = result.fetchone()
    if not row:
        return None
    st, host, port, api_key = (
        row[0],
        (row[1] or "").strip(),
        row[2],
        (row[3] or "").strip(),
    )
    base_url = build_base_url(host, port, st)
    return (st, base_url, api_key)
