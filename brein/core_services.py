"""What Brein ships with. Everything else registers from brein.extras."""

import asyncio
from typing import Any

from brein.downloads.sabnzbd import SabnzbdDownloader
from brein.extensions import Extension, ServiceType, Tab
from brein.integrations.api import emby, jellyfin, plex, radarr, sabnzbd, sonarr

_ARR_TABS = [
    Tab("queue", "Queue"),
    Tab("history", "History"),
    Tab("blocklist", "Blocklist"),
]
_MEDIA_TABS = [
    Tab("users", "Users", admin_only=True),
    Tab("library", "Library", admin_only=True),
    Tab("activitylog", "Activity log", admin_only=True),
]


def register(ext: Extension) -> None:
    ext.add_service_type(
        ServiceType(
            "emby",
            "Emby",
            "media_servers",
            8096,
            emby.test_connection,
            tabs=[
                *_MEDIA_TABS,
                Tab("user-dashboard", "User dashboard", admin_only=True),
            ],
        )
    )
    ext.add_service_type(
        ServiceType(
            "jellyfin",
            "Jellyfin",
            "media_servers",
            8096,
            jellyfin.test_connection,
            tabs=list(_MEDIA_TABS),
        )
    )
    ext.add_service_type(
        ServiceType(
            "plex",
            "Plex",
            "media_servers",
            32400,
            plex.test_connection,
            tabs=list(_MEDIA_TABS),
        )
    )
    ext.add_service_type(
        ServiceType(
            "sonarr",
            "Sonarr",
            "media_management",
            8989,
            sonarr.test_connection,
            tabs=[
                *_ARR_TABS,
                Tab("missing", "Missing"),
                Tab("cutoff", "Cutoff"),
                Tab("events", "Events"),
                Tab("tasks", "Tasks"),
                Tab("backups", "Backups"),
            ],
        )
    )
    ext.add_service_type(
        ServiceType(
            "radarr",
            "Radarr",
            "media_management",
            7878,
            radarr.test_connection,
            tabs=[
                *_ARR_TABS,
                Tab("collection", "Collections"),
                Tab("missing", "Missing"),
                Tab("cutoff", "Cutoff"),
                Tab("events", "Events"),
                Tab("tasks", "Tasks"),
                Tab("backups", "Backups"),
            ],
        )
    )
    ext.add_service_type(
        ServiceType(
            "sabnzbd",
            "SABnzbd",
            "downloaders",
            8080,
            sabnzbd.test_connection,
            tabs=[Tab("dl-queue", "Queue"), Tab("dl-history", "History")],
        )
    )
    ext.add_downloader("sabnzbd", SabnzbdDownloader())
    ext.add_instance_settings("sabnzbd", sabnzbd_settings)


async def sabnzbd_settings(
    base_url: str, api_key: str, instance_id: int | None
) -> dict[str, Any]:
    from brein.store import sabnzbd_stats as store_sabnzbd_stats

    (aok, status_data), (bok, stats) = await asyncio.gather(
        sabnzbd.get_status(base_url, api_key),
        sabnzbd.get_server_stats(base_url, api_key),
    )
    # mode=status answers {"status": {...}}; the page lists what it is given,
    # so it saw one key holding an object. Unwrap it and keep the fields worth
    # a row, version first.
    status = (
        status_data.get("status") if aok and isinstance(status_data, dict) else None
    )
    status = status if isinstance(status, dict) else {}
    out: dict[str, Any] = {
        "settings_sab_status": (
            {key: status[key] for key in _SAB_STATUS_FIELDS if key in status}
            if aok
            else None
        ),
        "settings_sab_server_stats": stats if bok else None,
    }
    if instance_id is not None:
        snapshot = await store_sabnzbd_stats.get_latest_snapshot(instance_id)
        out["settings_sabnzbd_stats_snapshot"] = (
            {
                "collected_at": snapshot.collected_at,
                "bytes_today": snapshot.bytes_today,
                "bytes_week": snapshot.bytes_week,
                "bytes_month": snapshot.bytes_month,
                "bytes_total": snapshot.bytes_total,
            }
            if snapshot
            else None
        )
    if not aok:
        out["settings_fetch_error"] = "Could not reach SABnzbd."
    return out


_SAB_STATUS_FIELDS = (
    "version",
    "uptime",
    "paused",
    "speed",
    "diskspace1",
    "diskspace2",
    "loadavg",
    "cache_size",
)
