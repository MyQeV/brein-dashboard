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


# ── Connection tests refuse redirects ────────────────────────────────────────


def _redirect(location: str) -> MagicMock:
    r = _make_response(301)
    r.headers = {"location": location}
    return r


@pytest.mark.asyncio
async def test_emby_test_connection_fails_on_a_redirect():
    """The clients never follow redirects, so an http:// URL a server answers
    with 301-to-https passed the test and then failed every data call."""
    from brein.integrations.api import emby

    mock_client = MagicMock()
    mock_client.get = AsyncMock(
        return_value=_redirect("https://emby.example/System/Info?api_key=k")
    )
    with patch("brein.integrations.api.emby.get_http_client", return_value=mock_client):
        ok, msg = await emby.test_connection("http://emby.example", "k")
    assert ok is False
    assert "https://emby.example/System/Info" in msg
    assert "api_key" not in msg


@pytest.mark.asyncio
async def test_arr_test_connection_fails_on_a_redirect_and_on_any_non_200():
    from brein.integrations.api import base

    for response, expected in (
        (_redirect("https://sonarr.example/api/v3/system/status"), "redirected"),
        (_make_response(500), "HTTP 500"),
        (_make_response(204), "HTTP 204"),
    ):
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=response)
        with patch(
            "brein.integrations.api.base.get_http_client", return_value=mock_client
        ):
            ok, msg = await base.get_with_api_key(
                "http://192.168.1.10:8989", "api/v3/system/status", "k"
            )
        assert ok is False
        assert expected in msg


# ── Emby / Jellyfin authorization ────────────────────────────────────────────


def test_auth_headers_carry_the_token_in_both_forms():
    """Jellyfin 12.0 dropped X-Emby-Token; Emby still reads it. One key, both headers."""
    from brein.integrations.api import emby

    headers = emby._auth_headers("abc123")
    assert headers["X-Emby-Token"] == "abc123"
    assert headers["Authorization"] == 'MediaBrowser Token="abc123"'
    assert emby._auth_headers("") == {}


@pytest.mark.asyncio
async def test_jellyfin_requests_send_the_authorization_header():
    from brein.integrations.api import jellyfin

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_make_response(200))
    with patch("brein.integrations.api.base.get_http_client", return_value=mock_client):
        ok, _ = await jellyfin.test_connection("http://jellyfin.local:8096", "abc123")
    assert ok is True
    sent = mock_client.get.call_args.kwargs["headers"]
    assert sent["Authorization"] == 'MediaBrowser Token="abc123"'
    assert sent["X-Emby-Token"] == "abc123"


@pytest.mark.asyncio
async def test_media_server_login_sends_client_identity_in_both_forms():
    """AuthenticateByName carries the client identity; 12.0 only reads Authorization."""
    from brein.integrations.api import emby

    response = _make_response(200)
    response.json = MagicMock(return_value={"AccessToken": "t"})
    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=response)
    with patch("brein.integrations.api.emby.get_http_client", return_value=mock_client):
        ok, _ = await emby.authenticate_user("http://emby.local:8096", "u", "p")
    assert ok is True
    sent = mock_client.post.call_args.kwargs["headers"]
    assert sent["Authorization"].startswith("MediaBrowser Client=")
    assert sent["X-Emby-Authorization"] == sent["Authorization"]


# ── Emby sessions ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_emby_get_sessions_returns_none_when_the_server_does_not_answer():
    """None, not []: an empty list says nothing is playing, which would
    close every live session on a server that merely failed to respond."""
    import httpx

    from brein.integrations.api import emby

    mock_client = MagicMock()
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
    with patch("brein.integrations.api.emby.get_http_client", return_value=mock_client):
        sessions = await emby.get_sessions("http://emby.local:8096", "abc123")
    assert sessions is None


@pytest.mark.asyncio
async def test_emby_get_sessions_returns_an_empty_list_when_nothing_plays():
    from brein.integrations.api import emby

    response = _make_response(200)
    response.json = MagicMock(return_value=[])
    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=response)
    with patch("brein.integrations.api.emby.get_http_client", return_value=mock_client):
        sessions = await emby.get_sessions("http://emby.local:8096", "abc123")
    assert sessions == []
