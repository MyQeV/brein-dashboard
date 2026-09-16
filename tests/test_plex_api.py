"""Unit tests for integrations/api/plex.py — httpx is mocked throughout."""

import json
from unittest.mock import AsyncMock, MagicMock, patch


def _mock_response(status_code: int, json_data: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json = MagicMock(return_value=json_data or {})
    return resp


class TestNormalizeBaseUrl:
    def test_valid_http(self):
        from brein.integrations.api.plex import _normalize_base_url

        assert _normalize_base_url("http://localhost:32400") == "http://localhost:32400"

    def test_strips_trailing_slash(self):
        from brein.integrations.api.plex import _normalize_base_url

        assert (
            _normalize_base_url("http://localhost:32400/") == "http://localhost:32400"
        )

    def test_strips_whitespace(self):
        from brein.integrations.api.plex import _normalize_base_url

        assert (
            _normalize_base_url("  http://localhost:32400  ")
            == "http://localhost:32400"
        )

    def test_invalid_returns_none(self):
        from brein.integrations.api.plex import _normalize_base_url

        assert _normalize_base_url("localhost:32400") is None
        assert _normalize_base_url("") is None
        assert _normalize_base_url(None) is None


class TestTestConnection:
    async def test_success(self):
        from brein.integrations.api.plex import test_connection

        mock_resp = _mock_response(200)
        with patch("brein.integrations.api.plex.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client
            ok, msg = await test_connection("http://localhost:32400", "mytoken")
        assert ok is True
        assert msg == "OK"
        # Verify Accept: application/json was sent
        call_kwargs = mock_client.get.call_args
        headers = (
            call_kwargs.kwargs.get("headers")
            or (call_kwargs[1] if len(call_kwargs) > 1 else {}).get("headers")
            or {}
        )
        assert (
            headers.get("Accept") == "application/json"
        ), f"Expected Accept header, got headers={headers}"
        assert (
            headers.get("X-Plex-Token") == "mytoken"
        ), f"Expected X-Plex-Token header, got headers={headers}"

    async def test_probes_an_endpoint_that_needs_the_token(self):
        """/identity is served without a token, so probing it passed any
        token at all."""
        from brein.integrations.api.plex import test_connection

        mock_resp = _mock_response(200)
        with patch("brein.integrations.api.plex.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client
            await test_connection("http://localhost:32400", "mytoken")
        url = mock_client.get.call_args.args[0]
        assert url == "http://localhost:32400/library/sections"

    async def test_redirect_is_a_failure_naming_the_target(self):
        from brein.integrations.api.plex import test_connection

        mock_resp = _mock_response(301)
        mock_resp.headers = {"location": "https://plex.example:32400/library/sections"}
        with patch("brein.integrations.api.plex.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client
            ok, msg = await test_connection("http://localhost:32400", "mytoken")
        assert ok is False
        assert "https://plex.example:32400/library/sections" in msg

    async def test_invalid_token_401(self):
        from brein.integrations.api.plex import test_connection

        mock_resp = _mock_response(401)
        with patch("brein.integrations.api.plex.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client
            ok, msg = await test_connection("http://localhost:32400", "badtoken")
        assert ok is False
        assert "Invalid" in msg or "401" in msg

    async def test_invalid_url_returns_false(self):
        from brein.integrations.api.plex import test_connection

        ok, msg = await test_connection("not-a-url", "token")
        assert ok is False
        assert "Invalid" in msg

    async def test_connect_error(self):
        import httpx
        from brein.integrations.api.plex import test_connection

        with patch("brein.integrations.api.plex.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
            mock_client_cls.return_value = mock_client
            ok, msg = await test_connection("http://localhost:32400", "token")
        assert ok is False
        assert msg.startswith("Connection failed")


class TestGetIdentity:
    async def test_success_returns_machine_identifier(self):
        from brein.integrations.api.plex import get_identity

        payload = {
            "MediaContainer": {
                "machineIdentifier": "abc123",
                "version": "1.32.0",
                "platform": "Linux",
            }
        }
        mock_resp = _mock_response(200, payload)
        with patch("brein.integrations.api.plex.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client
            ok, data = await get_identity("http://localhost:32400", "mytoken")
        assert ok is True
        assert data["machineIdentifier"] == "abc123"
        assert data["version"] == "1.32.0"

    async def test_non_200_returns_false(self):
        from brein.integrations.api.plex import get_identity

        mock_resp = _mock_response(403)
        with patch("brein.integrations.api.plex.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client
            ok, data = await get_identity("http://localhost:32400", "mytoken")
        assert ok is False
        assert data is None

    async def test_invalid_url_returns_false(self):
        from brein.integrations.api.plex import get_identity

        ok, data = await get_identity("bad-url", "token")
        assert ok is False
        assert data is None


def _sample_history_media_container() -> dict:
    """PMS-style JSON: Metadata[] under MediaContainer (session history)."""
    return {
        "MediaContainer": {
            "size": 1,
            "totalSize": 33,
            "offset": 0,
            "Metadata": [
                {
                    "historyKey": "/status/sessions/history/12",
                    "key": "/library/metadata/1234",
                    "ratingKey": "1234",
                    "librarySectionID": "1",
                    "title": "My Wonderful Movie",
                    "type": "movie",
                    "thumb": "/library/metadata/1234/thumb/1234567890",
                    "originallyAvailableAt": "2023-01-01",
                    "viewedAt": 1345678901,
                    "accountID": 123456,
                    "deviceID": 12,
                }
            ],
        }
    }


class TestParseHistoryResponseBody:
    def test_json_metadata_array_total_size_and_row(self):
        from brein.integrations.api.plex import _parse_history_response_body

        body = json.dumps(_sample_history_media_container())
        items, total_size = _parse_history_response_body(body)
        assert total_size == 33
        assert len(items) == 1
        row = items[0]
        assert row["historyKey"] == "/status/sessions/history/12"
        assert row["viewedAt"] == 1345678901
        assert row["accountID"] == 123456
        assert row["ratingKey"] == "1234"
        assert row["type"] == "movie"

    def test_session_history_items_extracts_metadata(self):
        from brein.integrations.api.plex import _session_history_items

        container = _sample_history_media_container()["MediaContainer"]
        items = _session_history_items(container)
        assert len(items) == 1
        assert items[0]["historyKey"] == "/status/sessions/history/12"

    def test_xml_metadata_elements_included(self):
        from brein.integrations.api.plex import _parse_history_response_body

        xml = """<?xml version="1.0" encoding="UTF-8"?>
<MediaContainer size="1">
  <Metadata historyKey="/status/sessions/history/12" key="/library/metadata/1234"
    ratingKey="1234" librarySectionID="1" title="My Wonderful Movie" type="movie"
    thumb="/library/metadata/1234/thumb/1" originallyAvailableAt="2023-01-01"
    viewedAt="1345678901" accountID="123456" deviceID="12"/>
</MediaContainer>"""
        items, total_size = _parse_history_response_body(xml)
        assert len(items) == 1
        assert items[0].get("historyKey") == "/status/sessions/history/12"
        assert items[0].get("viewedAt") == "1345678901"
        assert total_size == 1


class TestPlexNotificationWebsocketUrl:
    def test_http_to_ws_and_path(self):
        from brein.integrations.websockets.plex import plex_notification_websocket_url

        u = plex_notification_websocket_url("http://192.168.1.10:32400/", "mytoken")
        assert u.startswith("ws://192.168.1.10:32400/:/websockets/notifications")
        assert "X-Plex-Token=mytoken" in u

    def test_https_to_wss(self):
        from brein.integrations.websockets.plex import plex_notification_websocket_url

        u = plex_notification_websocket_url("https://plex.example:32400", "t")
        assert u.startswith("wss://plex.example:32400/:/websockets/notifications")


class TestPlexExtractTrackableSession:
    def test_session_fields(self):
        from brein.store.plex_playback_sessions import _extract_trackable_session

        item = {
            "User": {"id": 42},
            "Session": {"id": "sess-1"},
            "ratingKey": "999",
            "title": "Test Movie",
            "type": "movie",
            "grandparentTitle": "Show",
            "viewOffset": 120000,
            "duration": 600000,
        }
        got = _extract_trackable_session(item)
        assert got is not None
        key, fields = got
        assert key == "sess-1"
        assert fields["account_id"] == 42
        assert fields["rating_key"] == "999"
        assert fields["view_offset_ms"] == 120000
        assert fields["duration_ms"] == 600000

    def test_skip_without_session_id(self):
        from brein.store.plex_playback_sessions import _extract_trackable_session

        assert _extract_trackable_session({"User": {"id": 1}, "ratingKey": "1"}) is None

    def test_rating_key_from_key_path_when_rating_key_absent(self):
        from brein.store.plex_playback_sessions import _extract_trackable_session

        item = {
            "User": {"id": 1},
            "Session": {"id": "sess-k"},
            "key": "/library/metadata/55555",
            "title": "Only Key",
            "type": "movie",
            "viewOffset": 0,
            "duration": 120000,
        }
        got = _extract_trackable_session(item)
        assert got is not None
        _key, fields = got
        assert fields["rating_key"] == "55555"


class TestParseRatingKeyHelpers:
    def test_parse_metadata_path(self):
        from brein.integrations.api.plex import parse_rating_key_from_library_key

        assert parse_rating_key_from_library_key("/library/metadata/12345") == "12345"
        assert parse_rating_key_from_library_key(None) is None

    def test_rating_key_from_session_prefers_rating_key(self):
        from brein.integrations.api.plex import rating_key_from_plex_session_dict

        assert (
            rating_key_from_plex_session_dict({"ratingKey": "9", "key": "/bad"}) == "9"
        )

    def test_rating_key_from_session_fallback_key(self):
        from brein.integrations.api.plex import rating_key_from_plex_session_dict

        assert (
            rating_key_from_plex_session_dict({"key": "/library/metadata/42"}) == "42"
        )


class TestGetLibraryAllItemsPage:
    async def test_returns_metadata_and_total(self):
        from brein.integrations.api.plex import get_library_all_items_page

        payload = {
            "MediaContainer": {
                "totalSize": 2,
                "size": 1,
                "Metadata": [
                    {
                        "ratingKey": "1",
                        "title": "A",
                        "type": "movie",
                        "duration": 3600000,
                    }
                ],
            }
        }
        mock_resp = _mock_response(200, payload)
        with patch("brein.integrations.api.plex.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client
            items, total = await get_library_all_items_page(
                "http://localhost:32400", "tok", 1, 0, 50
            )
        assert total == 2
        assert len(items) == 1
        assert items[0]["ratingKey"] == "1"
        call_kwargs = mock_client.get.call_args
        hdrs = call_kwargs.kwargs.get("headers") or {}
        assert hdrs.get("X-Plex-Container-Start") == "0"
        assert hdrs.get("X-Plex-Container-Size") == "50"


class TestGetSessionsVideoFallback:
    async def test_collects_video_not_only_metadata(self):
        from brein.integrations.api.plex import get_sessions

        payload = {
            "MediaContainer": {
                "size": 1,
                "Video": [
                    {
                        "ratingKey": "777",
                        "title": "From Video",
                        "type": "movie",
                        "User": {"id": "1"},
                        "Session": {"id": "sv"},
                        "duration": 1000,
                        "viewOffset": 0,
                    }
                ],
            }
        }
        mock_resp = _mock_response(200, payload)
        with patch("brein.integrations.api.plex.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client
            sessions = await get_sessions("http://localhost:32400", "t")
        assert len(sessions) == 1
        assert sessions[0]["ratingKey"] == "777"


class TestPlexMetadataRow:
    def test_row_from_plex_metadata_movie(self):
        from brein.store.plex_items import row_from_plex_metadata

        m = {
            "ratingKey": "10",
            "title": "Film",
            "type": "movie",
            "duration": 5000,
            "librarySectionID": 2,
            "guid": "plex://movie/guid",
        }
        row = row_from_plex_metadata(1, m, "srv1", "2025-01-01T00:00:00+00:00")
        assert row is not None
        assert row["item_id"] == "10"
        assert row["server_id"] == "srv1"
        assert row["run_time_ticks"] == 5000 * 10000
        assert row["series_id"] is None
        assert row["library_section_id"] == "2"
        assert row["guid"] == "plex://movie/guid"
