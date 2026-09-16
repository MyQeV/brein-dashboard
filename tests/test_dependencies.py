"""require_instance_config: the one gate every instance route goes through."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from brein.web.dependencies import require_instance_config

STORE_CFG = "brein.store.instances.get_instance_connection_config"


async def _require(cfg, *args, **kwargs):
    with patch(STORE_CFG, new_callable=AsyncMock, return_value=cfg):
        return await require_instance_config(1, *args, **kwargs)


async def _refused(cfg, *args, **kwargs) -> HTTPException:
    with pytest.raises(HTTPException) as exc:
        await _require(cfg, *args, **kwargs)
    return exc.value


async def test_returns_the_connection():
    assert await _require(("emby", "http://emby:8096", "k")) == (
        "emby",
        "http://emby:8096",
        "k",
    )


async def test_404_when_the_instance_does_not_exist():
    exc = await _refused(None)
    assert exc.status_code == 404
    assert exc.detail == "Instance not found"


@pytest.mark.parametrize(
    "cfg", [("emby", "", ""), ("emby", "http://x", ""), ("emby", "", "k")]
)
async def test_400_when_host_or_key_is_missing(cfg):
    exc = await _refused(cfg)
    assert exc.status_code == 400
    assert exc.detail == "Configure host and API key first"


async def test_400_when_the_service_type_does_not_match():
    exc = await _refused(("emby", "http://x", "k"), "plex")
    assert exc.status_code == 400
    assert exc.detail == "Not a plex instance"


async def test_accepts_any_of_several_service_types():
    assert (await _require(("jellyfin", "http://x", "k"), ("emby", "jellyfin")))[
        0
    ] == "jellyfin"
    exc = await _refused(("plex", "http://x", "k"), ("emby", "jellyfin"))
    assert exc.status_code == 400
    assert exc.detail == "Not a emby or jellyfin instance"


async def test_a_route_keeps_its_own_answer_for_a_mismatch():
    exc = await _refused(
        ("plex", "http://x", "k"),
        ("emby", "jellyfin"),
        detail="Not supported for this app",
        status_code=404,
    )
    assert exc.status_code == 404
    assert exc.detail == "Not supported for this app"


async def test_the_connection_is_checked_before_the_type():
    """An unconfigured instance of the wrong kind is reported as unconfigured."""
    exc = await _refused(("plex", "", ""), "emby")
    assert exc.detail == "Configure host and API key first"
