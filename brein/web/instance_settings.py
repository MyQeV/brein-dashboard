"""Live system information for the instance Settings tab.

Extracted from the Jinja handler: this was the only place these system-info,
health and host-config calls were made, so there was no way to reach them
except by rendering a template.
"""

import asyncio
import logging
from typing import Any

from brein.extensions import load_extensions

log = logging.getLogger(__name__)


async def load_settings_info(
    service_type: str,
    base_url: str,
    api_key: str,
    instance_id: int | None = None,
) -> dict[str, Any]:
    """Load live API data for the instance Settings tab (no DB persistence)."""
    st = (service_type or "").lower()
    out: dict[str, Any] = {
        "settings_system_info": None,
        "settings_public_info": None,
        "settings_health": None,
        "settings_host_config": None,
        "settings_fetch_error": None,
    }
    if st in ("emby", "jellyfin"):
        from brein.integrations.api import emby as _emby_api

        (iok, info), (pok, pub) = await asyncio.gather(
            _emby_api.get_system_info(base_url, api_key),
            _emby_api.get_system_info_public(base_url, api_key),
        )
        out["settings_system_info"] = info if iok else None
        out["settings_public_info"] = pub if pok else None
        if not iok and not pok:
            out["settings_fetch_error"] = "Could not load system information."
        return out
    if st == "sonarr":
        from brein.integrations import sonarr as _sonarr_api

        (sok, status), (hok, health), (cok, host) = await asyncio.gather(
            _sonarr_api.get_system_info(base_url, api_key),
            _sonarr_api.get_health(base_url, api_key),
            _sonarr_api.get_config_host(base_url, api_key),
        )
        out["settings_system_info"] = status if sok else None
        out["settings_health"] = health if hok else None
        out["settings_host_config"] = host if cok else None
        if not sok:
            out["settings_fetch_error"] = "Could not reach Sonarr."
        return out
    if st == "radarr":
        from brein.integrations import radarr as _radarr_api

        (sok, status), (hok, health), (cok, host) = await asyncio.gather(
            _radarr_api.get_system_info(base_url, api_key),
            _radarr_api.get_health(base_url, api_key),
            _radarr_api.get_config_host(base_url, api_key),
        )
        out["settings_system_info"] = status if sok else None
        out["settings_health"] = health if hok else None
        out["settings_host_config"] = host if cok else None
        if not sok:
            out["settings_fetch_error"] = "Could not reach Radarr."
        return out
    if st == "plex":
        from brein.integrations.api import plex as _plex_api

        iok, identity = await _plex_api.get_identity(base_url, api_key)
        out["settings_system_info"] = identity if iok else None
        if not iok:
            out["settings_fetch_error"] = "Could not reach Plex."
        return out
    hook = load_extensions().instance_settings.get(st)
    if hook:
        out.update(await hook(base_url, api_key, instance_id))
    return out
