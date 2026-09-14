"""SABnzbd behind the downloader interface."""

from typing import Any

from brein.extensions import DownloaderCapabilities
from brein.integrations.api import sabnzbd as api


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _mb_to_bytes(value: Any) -> int:
    return _int(value) * 1024 * 1024


def sabnzbd_queue(payload: dict[str, Any]) -> dict[str, Any]:
    queue = payload.get("queue") or {}
    items = []
    for slot in queue.get("slots") or []:
        total = _mb_to_bytes(slot.get("mb"))
        left = _mb_to_bytes(slot.get("mbleft"))
        items.append(
            {
                "id": str(slot.get("nzo_id") or ""),
                "name": slot.get("filename") or slot.get("name") or "",
                "status": slot.get("status") or "",
                "size_bytes": total,
                "remaining_bytes": left,
                "progress_pct": round(100 * (total - left) / total) if total else 0,
                "eta": slot.get("timeleft") or None,
                "category": slot.get("cat") or None,
            }
        )
    return {
        "items": items,
        "paused": bool(queue.get("paused")),
        # SABnzbd reports the limit as a percentage and the absolute rate
        # separately; both are useful, so both are returned raw.
        "speed_limit_pct": _int(queue.get("speedlimit"), 100),
        "speed_limit_bytes": _int(queue.get("speedlimit_abs")),
        "speed_bytes": _int(float(queue.get("kbpersec") or 0) * 1024),
        "pause_seconds_left": _int(queue.get("pause_int")),
    }


def sabnzbd_history(payload: Any) -> list[dict[str, Any]]:
    slots: list[dict[str, Any]] = payload if isinstance(payload, list) else []
    return [
        {
            "id": str(slot.get("nzo_id") or ""),
            "name": slot.get("name") or "",
            "status": slot.get("status") or "",
            "size_bytes": _int(slot.get("bytes")),
            "completed_at": slot.get("completed") or None,
            "category": slot.get("category") or None,
            "error": slot.get("fail_message") or None,
        }
        for slot in slots
    ]


class SabnzbdDownloader:
    capabilities = DownloaderCapabilities(
        per_item_pause=True, queue_level_pause=True, history="list"
    )

    async def queue(self, base_url: str, api_key: str) -> tuple[bool, dict[str, Any]]:
        ok, data = await api.get_queue(base_url, api_key)
        if not ok or data is None:
            return False, {}
        return True, sabnzbd_queue(data)

    async def history(
        self, base_url: str, api_key: str
    ) -> tuple[bool, list[dict[str, Any]]]:
        ok, slots = await api.get_history_filtered(base_url, api_key)
        return ok, (sabnzbd_history(slots or []) if ok else [])

    async def pause(
        self, base_url: str, api_key: str, item_id: str | None
    ) -> tuple[bool, str]:
        return await (
            api.pause_nzo(base_url, api_key, item_id)
            if item_id
            else api.pause_queue(base_url, api_key)
        )

    async def resume(
        self, base_url: str, api_key: str, item_id: str | None
    ) -> tuple[bool, str]:
        return await (
            api.resume_nzo(base_url, api_key, item_id)
            if item_id
            else api.resume_queue(base_url, api_key)
        )

    async def delete(
        self, base_url: str, api_key: str, item_id: str, remove_files: bool
    ) -> tuple[bool, str]:
        return await api.delete_nzo(base_url, api_key, item_id)

    async def status(self, base_url: str, api_key: str) -> tuple[bool, dict[str, Any]]:
        ok, data = await api.get_queue(base_url, api_key)
        if not ok or not data:
            return ok, {}
        speed_mbps = float(data.get("queue", {}).get("kbpersec", 0)) / 1024
        return True, {"speed_mbps": speed_mbps}

    async def set_speed_limit(
        self, base_url: str, api_key: str, value: int
    ) -> tuple[bool, str]:
        return await api.set_speed_limit(base_url, api_key, value)
