"""Unit tests for Plex session fetching and now-playing normalization."""

from unittest.mock import AsyncMock, MagicMock, patch

# -- Sample Plex /status/sessions response --
PLEX_SESSIONS_RESPONSE = {
    "MediaContainer": {
        "size": 1,
        "Metadata": [
            {
                "key": "/library/metadata/1234",
                "ratingKey": "1234",
                "title": "The Episode Title",
                "grandparentTitle": "The Series Name",
                "type": "episode",
                "duration": 2700000,
                "viewOffset": 600000,
                "User": {"id": "5", "title": "alice"},
                "Player": {
                    "state": "playing",
                    "device": "iPhone",
                    "title": "Plex for iOS",
                },
                "Session": {"id": "session-abc"},
            }
        ],
    }
}

PLEX_MOVIE_SESSION = {
    "MediaContainer": {
        "size": 1,
        "Metadata": [
            {
                "key": "/library/metadata/9999",
                "ratingKey": "9999",
                "title": "The Movie Title",
                "type": "movie",
                "duration": 7200000,
                "viewOffset": 3600000,
                "User": {"id": "7", "title": "bob"},
                "Player": {
                    "state": "paused",
                    "device": "AppleTV",
                    "title": "Plex for AppleTV",
                },
                "Session": {"id": "session-xyz"},
            }
        ],
    }
}


class TestGetSessions:
    async def test_returns_list_on_success(self):
        from brein.integrations.api.plex import get_sessions

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(return_value=PLEX_SESSIONS_RESPONSE)
        with patch("brein.integrations.api.plex.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client
            sessions = await get_sessions("http://localhost:32400", "mytoken")
        assert isinstance(sessions, list)
        assert len(sessions) == 1
        assert sessions[0]["ratingKey"] == "1234"

    async def test_returns_none_on_non_200(self):
        from brein.integrations.api.plex import get_sessions

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        with patch("brein.integrations.api.plex.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client
            sessions = await get_sessions("http://localhost:32400", "mytoken")
        # None, not []: an empty list would tell the caller the server said
        # nothing is playing, which closes every live session it holds.
        assert sessions is None

    async def test_returns_none_on_bad_url(self):
        from brein.integrations.api.plex import get_sessions

        sessions = await get_sessions("not-a-url", "token")
        # None, not []: an empty list would tell the caller the server said
        # nothing is playing, which closes every live session it holds.
        assert sessions is None

    async def test_returns_none_on_connect_error(self):
        import httpx
        from brein.integrations.api.plex import get_sessions

        with patch("brein.integrations.api.plex.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
            mock_client_cls.return_value = mock_client
            sessions = await get_sessions("http://localhost:32400", "token")
        # None, not []: an empty list would tell the caller the server said
        # nothing is playing, which closes every live session it holds.
        assert sessions is None


class TestNormalizePlexSession:
    def test_episode_normalizes_correctly(self):
        from brein.web.routers.now_playing import _normalize_plex_session

        session = PLEX_SESSIONS_RESPONSE["MediaContainer"]["Metadata"][0]
        result = _normalize_plex_session(
            session,
            instance_id=1,
            instance_label="My Plex",
            app_url="http://plex:32400",
            server_id="abc123",
        )
        assert result is not None
        assert result["instance_id"] == 1
        assert result["instance_label"] == "My Plex"
        assert result["user_name"] == "alice"
        assert result["item"]["name"] == "The Episode Title"
        assert result["item"]["type"] == "Episode"
        assert result["item"]["series_name"] == "The Series Name"
        assert result["is_paused"] is False
        # viewOffset 600000ms → 6000000000 ticks (×10000)
        assert result["position_ticks"] == 6000000000
        # duration 2700000ms → 27000000000 ticks
        assert result["item"]["run_time_ticks"] == 27000000000

    def test_movie_normalizes_correctly(self):
        from brein.web.routers.now_playing import _normalize_plex_session

        session = PLEX_MOVIE_SESSION["MediaContainer"]["Metadata"][0]
        result = _normalize_plex_session(
            session,
            instance_id=2,
            instance_label="Plex",
            app_url="",
            server_id="",
        )
        assert result is not None
        assert result["item"]["type"] == "Movie"
        assert result["item"]["series_name"] == ""
        assert result["is_paused"] is True

    def test_missing_user_returns_none(self):
        from brein.web.routers.now_playing import _normalize_plex_session

        session = {"ratingKey": "1", "title": "Foo", "type": "movie"}  # no User
        result = _normalize_plex_session(
            session,
            instance_id=1,
            instance_label="P",
            app_url="",
            server_id="",
        )
        assert result is None
