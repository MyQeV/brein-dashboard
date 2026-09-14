"""Unit tests for the core integration clients (SABnzbd)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_response(status_code: int) -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    return r


# ── SABnzbd ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sabnzbd_test_connection_ok():
    from brein.integrations.api import sabnzbd

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_make_response(200))
    with patch(
        "brein.integrations.api.sabnzbd.get_http_client", return_value=mock_client
    ):
        ok, msg = await sabnzbd.test_connection("http://192.168.1.10:8080", "abc123")
    assert ok is True
    assert msg == "OK"


def test_parse_server_stats_daily_timeline_sums_across_servers():
    from brein.integrations.api import sabnzbd

    payload = {
        "servers": {
            "news.example": {
                "daily": {"2025-03-01": 1_000_000_000, "2025-03-02": 2_000_000_000},
            },
            "backup.example": {"daily": {"2025-03-01": 500_000_000}},
        }
    }
    got = sabnzbd.parse_server_stats_daily_timeline(payload)
    assert got["2025-03-01"] == 1_500_000_000
    assert got["2025-03-02"] == 2_000_000_000


@pytest.mark.asyncio
async def test_sabnzbd_test_connection_bad_key():
    from brein.integrations.api import sabnzbd

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_make_response(401))
    with patch(
        "brein.integrations.api.sabnzbd.get_http_client", return_value=mock_client
    ):
        ok, msg = await sabnzbd.test_connection("http://192.168.1.10:8080", "badkey")
    assert ok is False


@pytest.mark.asyncio
async def test_sabnzbd_test_connection_bad_url():
    from brein.integrations.api import sabnzbd

    ok, msg = await sabnzbd.test_connection("not-a-url", "abc123")
    assert ok is False


# ── SABnzbd extended functions ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sabnzbd_get_queue_ok():
    from brein.integrations.api import sabnzbd

    mock_client = AsyncMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "queue": {
            "slots": [{"filename": "test.nzb", "percentage": 50}],
            "paused": False,
        }
    }
    mock_client.get = AsyncMock(return_value=resp)
    with patch(
        "brein.integrations.api.sabnzbd.get_http_client", return_value=mock_client
    ):
        ok, data = await sabnzbd.get_queue("http://192.168.1.10:8080", "abc123")
    assert ok is True
    assert isinstance(data, dict)


@pytest.mark.asyncio
async def test_sabnzbd_get_queue_failure():
    from brein.integrations.api import sabnzbd

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_make_response(500))
    with patch(
        "brein.integrations.api.sabnzbd.get_http_client", return_value=mock_client
    ):
        ok, data = await sabnzbd.get_queue("http://192.168.1.10:8080", "abc123")
    assert ok is False
    assert data is None


@pytest.mark.asyncio
async def test_sabnzbd_get_history_filtered_ok():
    from brein.integrations.api import sabnzbd

    mock_client = AsyncMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "history": {"slots": [{"name": "done.nzb", "status": "Completed"}]}
    }
    mock_client.get = AsyncMock(return_value=resp)
    with patch(
        "brein.integrations.api.sabnzbd.get_http_client", return_value=mock_client
    ):
        ok, items = await sabnzbd.get_history_filtered(
            "http://192.168.1.10:8080", "abc123"
        )
    assert ok is True
    assert isinstance(items, list)


@pytest.mark.asyncio
async def test_sabnzbd_get_history_filtered_failure():
    from brein.integrations.api import sabnzbd

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_make_response(502))
    with patch(
        "brein.integrations.api.sabnzbd.get_http_client", return_value=mock_client
    ):
        ok, items = await sabnzbd.get_history_filtered(
            "http://192.168.1.10:8080", "abc123"
        )
    assert ok is False
    assert items is None


@pytest.mark.asyncio
async def test_sabnzbd_pause_queue_ok():
    from brein.integrations.api import sabnzbd

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_make_response(200))
    with patch(
        "brein.integrations.api.sabnzbd.get_http_client", return_value=mock_client
    ):
        ok, msg = await sabnzbd.pause_queue("http://192.168.1.10:8080", "abc123")
    assert ok is True


@pytest.mark.asyncio
async def test_sabnzbd_pause_queue_failure():
    from brein.integrations.api import sabnzbd

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_make_response(500))
    with patch(
        "brein.integrations.api.sabnzbd.get_http_client", return_value=mock_client
    ):
        ok, msg = await sabnzbd.pause_queue("http://192.168.1.10:8080", "abc123")
    assert ok is False


@pytest.mark.asyncio
async def test_sabnzbd_resume_queue_ok():
    from brein.integrations.api import sabnzbd

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_make_response(200))
    with patch(
        "brein.integrations.api.sabnzbd.get_http_client", return_value=mock_client
    ):
        ok, msg = await sabnzbd.resume_queue("http://192.168.1.10:8080", "abc123")
    assert ok is True


@pytest.mark.asyncio
async def test_sabnzbd_set_speed_limit_ok():
    from brein.integrations.api import sabnzbd

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_make_response(200))
    with patch(
        "brein.integrations.api.sabnzbd.get_http_client", return_value=mock_client
    ):
        ok, msg = await sabnzbd.set_speed_limit(
            "http://192.168.1.10:8080", "abc123", 5000
        )
    assert ok is True


@pytest.mark.asyncio
async def test_sabnzbd_set_speed_limit_failure():
    from brein.integrations.api import sabnzbd

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_make_response(500))
    with patch(
        "brein.integrations.api.sabnzbd.get_http_client", return_value=mock_client
    ):
        ok, msg = await sabnzbd.set_speed_limit(
            "http://192.168.1.10:8080", "abc123", 5000
        )
    assert ok is False
