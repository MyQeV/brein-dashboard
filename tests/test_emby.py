"""Unit tests for all Emby-related API endpoints (no live server required)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from brein.web.routers import dashboard as dashboard_router


# ---------------------------------------------------------------------------
# Patch-target constants
# ---------------------------------------------------------------------------
# Moved from store.settings to store.instances; the routers read it as a
# module attribute, so patching it at the source still intercepts them.
STORE_CFG = "brein.store.instances.get_instance_connection_config"
EMBY = "brein.integrations.api.emby"
CACHE = "brein.cache"
NOW_PLAYING = "brein.web.routers.now_playing"

# Fake configs
CFG_EMBY = ("emby", "http://emby:8096", "apikey123")
CFG_RADARR = ("radarr", "http://radarr", "apikey")

# Minimal Emby API response shapes
_USER_RAW = {
    "Id": "uid1",
    "Name": "Test User",
    "LastLoginDate": None,
    "LastActivityDate": None,
    "PrimaryImageTag": None,
    "Policy": {
        "IsDisabled": False,
        "IsAdministrator": False,
        "EnableAllFolders": True,
        "EnabledFolders": [],
        "EnableLiveTvAccess": False,
        "SimultaneousStreamLimit": 0,
    },
}
_FOLDER_RAW = {
    "Id": "lib1",
    "Name": "Movies",
    "ServerId": "server1",
    "Guid": None,
    "Type": "Folder",
    "CollectionType": "movies",
}


# ---------------------------------------------------------------------------
# GET /api/instances/{id}/users
# ---------------------------------------------------------------------------
class TestInstanceUsers:
    def test_200_happy_path(self, client):
        with (
            patch(STORE_CFG, new_callable=AsyncMock) as m_cfg,
            patch(f"{EMBY}.get_users", new_callable=AsyncMock) as m_users,
            patch(f"{EMBY}.get_media_folders", new_callable=AsyncMock) as m_folders,
        ):
            m_cfg.return_value = CFG_EMBY
            m_users.return_value = (True, [_USER_RAW])
            m_folders.return_value = (True, [_FOLDER_RAW])

            r = client.get("/api/instances/1/users")

        assert r.status_code == 200
        body = r.json()
        assert "users" in body and "libraries" in body
        assert body["users"][0]["id"] == "uid1"
        assert body["libraries"][0]["id"] == "lib1"

    def test_404_instance_not_found(self, client):
        with patch(STORE_CFG, new_callable=AsyncMock) as m_cfg:
            m_cfg.return_value = None
            r = client.get("/api/instances/99/users")
        assert r.status_code == 404

    def test_supported_false_for_non_emby(self, client):
        with patch(STORE_CFG, new_callable=AsyncMock) as m_cfg:
            m_cfg.return_value = CFG_RADARR
            r = client.get("/api/instances/1/users")
        assert r.status_code == 200
        assert r.json()["supported"] is False

    def test_502_emby_failure(self, client):
        with (
            patch(STORE_CFG, new_callable=AsyncMock) as m_cfg,
            patch(f"{EMBY}.get_users", new_callable=AsyncMock) as m_users,
            patch(f"{EMBY}.get_media_folders", new_callable=AsyncMock) as m_folders,
        ):
            m_cfg.return_value = CFG_EMBY
            m_users.return_value = (False, None)
            m_folders.return_value = (True, [])
            r = client.get("/api/instances/1/users")
        assert r.status_code == 502


# ---------------------------------------------------------------------------
# GET /api/instances/{id}/libraries
# ---------------------------------------------------------------------------
class TestInstanceLibraries:
    def test_200_happy_path(self, client):
        with (
            patch(STORE_CFG, new_callable=AsyncMock) as m_cfg,
            patch(f"{EMBY}.get_media_folders", new_callable=AsyncMock) as m_folders,
        ):
            m_cfg.return_value = CFG_EMBY
            m_folders.return_value = (True, [_FOLDER_RAW])
            r = client.get("/api/instances/1/libraries")
        assert r.status_code == 200
        body = r.json()
        assert body["supported"] is True
        assert body["libraries"][0]["id"] == "lib1"

    def test_404_instance_not_found(self, client):
        with patch(STORE_CFG, new_callable=AsyncMock) as m_cfg:
            m_cfg.return_value = None
            r = client.get("/api/instances/99/libraries")
        assert r.status_code == 404

    def test_supported_false_for_non_emby(self, client):
        with patch(STORE_CFG, new_callable=AsyncMock) as m_cfg:
            m_cfg.return_value = CFG_RADARR
            r = client.get("/api/instances/1/libraries")
        assert r.status_code == 200
        assert r.json()["supported"] is False

    def test_502_emby_failure(self, client):
        with (
            patch(STORE_CFG, new_callable=AsyncMock) as m_cfg,
            patch(f"{EMBY}.get_media_folders", new_callable=AsyncMock) as m_folders,
        ):
            m_cfg.return_value = CFG_EMBY
            m_folders.return_value = (False, None)
            r = client.get("/api/instances/1/libraries")
        assert r.status_code == 502


# ---------------------------------------------------------------------------
# POST /api/instances/{id}/users/policy
# ---------------------------------------------------------------------------
class TestUsersPolicy:
    def test_200_all_updated(self, client):
        with (
            patch(STORE_CFG, new_callable=AsyncMock) as m_cfg,
            patch(f"{EMBY}.update_user_policy", new_callable=AsyncMock) as m_pol,
        ):
            m_cfg.return_value = CFG_EMBY
            m_pol.return_value = (True, "OK")
            r = client.post(
                "/api/instances/1/users/policy",
                json={"user_ids": ["uid1", "uid2"], "enable_all_folders": True},
            )
        assert r.status_code == 200
        assert r.json()["updated"] == 2
        assert r.json()["errors"] == []

    def test_200_partial_failure(self, client):
        with (
            patch(STORE_CFG, new_callable=AsyncMock) as m_cfg,
            patch(f"{EMBY}.update_user_policy", new_callable=AsyncMock) as m_pol,
        ):
            m_cfg.return_value = CFG_EMBY
            m_pol.side_effect = [(True, "OK"), (False, "server error")]
            r = client.post(
                "/api/instances/1/users/policy",
                json={"user_ids": ["uid1", "uid2"]},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["updated"] == 1
        assert len(body["errors"]) == 1

    def test_400_no_user_ids(self, client):
        with patch(STORE_CFG, new_callable=AsyncMock) as m_cfg:
            m_cfg.return_value = CFG_EMBY
            r = client.post(
                "/api/instances/1/users/policy",
                json={"user_ids": []},
            )
        assert r.status_code == 400

    def test_404_instance_not_found(self, client):
        with patch(STORE_CFG, new_callable=AsyncMock) as m_cfg:
            m_cfg.return_value = None
            r = client.post(
                "/api/instances/99/users/policy",
                json={"user_ids": ["uid1"]},
            )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/instances/{id}/users/{user_id}
# ---------------------------------------------------------------------------
class TestUserDetail:
    def test_200_happy_path(self, client):
        with (
            patch(STORE_CFG, new_callable=AsyncMock) as m_cfg,
            patch(f"{EMBY}.get_user_by_id", new_callable=AsyncMock) as m_get,
        ):
            m_cfg.return_value = CFG_EMBY
            m_get.return_value = (True, _USER_RAW)
            r = client.get("/api/instances/1/users/uid1")
        assert r.status_code == 200
        assert r.json()["Id"] == "uid1"

    def test_404_user_not_found(self, client):
        with (
            patch(STORE_CFG, new_callable=AsyncMock) as m_cfg,
            patch(f"{EMBY}.get_user_by_id", new_callable=AsyncMock) as m_get,
        ):
            m_cfg.return_value = CFG_EMBY
            m_get.return_value = (False, None)
            r = client.get("/api/instances/1/users/missing")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/instances/{id}/activitylog
# ---------------------------------------------------------------------------
class TestActivityLog:
    def test_200_default_pagination(self, client):
        with (
            patch(STORE_CFG, new_callable=AsyncMock) as m_cfg,
            patch(f"{EMBY}.get_activity_log_entries", new_callable=AsyncMock) as m_log,
        ):
            m_cfg.return_value = CFG_EMBY
            m_log.return_value = (True, [{"Id": 1, "Name": "Login"}])
            r = client.get("/api/instances/1/activitylog")
        assert r.status_code == 200
        assert "items" in r.json()
        assert len(r.json()["items"]) == 1

    def test_200_custom_limit(self, client):
        with (
            patch(STORE_CFG, new_callable=AsyncMock) as m_cfg,
            patch(f"{EMBY}.get_activity_log_entries", new_callable=AsyncMock) as m_log,
        ):
            m_cfg.return_value = CFG_EMBY
            m_log.return_value = (True, [])
            r = client.get("/api/instances/1/activitylog?limit=10&start_index=5")
            _, call_kwargs = m_log.call_args
            assert call_kwargs.get("limit") == 10
            assert call_kwargs.get("start_index") == 5
        assert r.status_code == 200

    def test_404_instance_not_found(self, client):
        with patch(STORE_CFG, new_callable=AsyncMock) as m_cfg:
            m_cfg.return_value = None
            r = client.get("/api/instances/99/activitylog")
        assert r.status_code == 404

    def test_502_emby_failure(self, client):
        with (
            patch(STORE_CFG, new_callable=AsyncMock) as m_cfg,
            patch(f"{EMBY}.get_activity_log_entries", new_callable=AsyncMock) as m_log,
        ):
            m_cfg.return_value = CFG_EMBY
            m_log.return_value = (False, None)
            r = client.get("/api/instances/1/activitylog")
        assert r.status_code == 502


# ---------------------------------------------------------------------------
# POST /api/instances/{id}/users/bulk-status
# ---------------------------------------------------------------------------
class TestBulkStatus:
    def test_200_activate(self, client):
        with (
            patch(STORE_CFG, new_callable=AsyncMock) as m_cfg,
            patch(f"{EMBY}.update_user_policy", new_callable=AsyncMock) as m_pol,
        ):
            m_cfg.return_value = CFG_EMBY
            m_pol.return_value = (True, "OK")
            r = client.post(
                "/api/instances/1/users/bulk-status",
                json={"user_ids": ["uid1"], "is_disabled": False},
            )
        assert r.status_code == 200
        assert r.json()["updated"] == 1

    def test_200_deactivate(self, client):
        with (
            patch(STORE_CFG, new_callable=AsyncMock) as m_cfg,
            patch(f"{EMBY}.update_user_policy", new_callable=AsyncMock) as m_pol,
        ):
            m_cfg.return_value = CFG_EMBY
            m_pol.return_value = (True, "OK")
            r = client.post(
                "/api/instances/1/users/bulk-status",
                json={"user_ids": ["uid1"], "is_disabled": True},
            )
        assert r.status_code == 200

    def test_400_no_user_ids(self, client):
        with patch(STORE_CFG, new_callable=AsyncMock) as m_cfg:
            m_cfg.return_value = CFG_EMBY
            r = client.post(
                "/api/instances/1/users/bulk-status",
                json={"user_ids": [], "is_disabled": False},
            )
        assert r.status_code == 400

    def test_404_instance_not_found(self, client):
        with patch(STORE_CFG, new_callable=AsyncMock) as m_cfg:
            m_cfg.return_value = None
            r = client.post(
                "/api/instances/99/users/bulk-status",
                json={"user_ids": ["uid1"], "is_disabled": False},
            )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /api/instances/{id}/users/{user_id}
# ---------------------------------------------------------------------------
class TestUserUpdate:
    def test_200_policy_update(self, client):
        with (
            patch(STORE_CFG, new_callable=AsyncMock) as m_cfg,
            patch(f"{EMBY}.update_user_policy", new_callable=AsyncMock) as m_pol,
        ):
            m_cfg.return_value = CFG_EMBY
            m_pol.return_value = (True, "OK")
            r = client.patch(
                "/api/instances/1/users/uid1",
                json={"is_administrator": True},
            )
        assert r.status_code == 200
        assert r.json() == {"ok": True}

    def test_200_name_change(self, client):
        with (
            patch(STORE_CFG, new_callable=AsyncMock) as m_cfg,
            patch(f"{EMBY}.update_user", new_callable=AsyncMock) as m_upd,
        ):
            m_cfg.return_value = CFG_EMBY
            m_upd.return_value = (True, "OK")
            r = client.patch(
                "/api/instances/1/users/uid1",
                json={"name": "New Name"},
            )
        assert r.status_code == 200

    def test_200_password_change(self, client):
        with (
            patch(STORE_CFG, new_callable=AsyncMock) as m_cfg,
            patch(f"{EMBY}.update_user_password", new_callable=AsyncMock) as m_pw,
        ):
            m_cfg.return_value = CFG_EMBY
            m_pw.return_value = (True, "OK")
            r = client.patch(
                "/api/instances/1/users/uid1",
                json={"new_password": "hunter2"},  # pragma: allowlist secret
            )
        assert r.status_code == 200

    def test_502_password_failure(self, client):
        with (
            patch(STORE_CFG, new_callable=AsyncMock) as m_cfg,
            patch(f"{EMBY}.update_user_password", new_callable=AsyncMock) as m_pw,
        ):
            m_cfg.return_value = CFG_EMBY
            m_pw.return_value = (False, "bad password")
            r = client.patch(
                "/api/instances/1/users/uid1",
                json={"new_password": "tooshort"},  # pragma: allowlist secret
            )
        assert r.status_code == 502


# ---------------------------------------------------------------------------
# GET /api/instances/{id}/image
# ---------------------------------------------------------------------------
class TestInstanceImage:
    def test_400_invalid_item_id(self, client):
        r = client.get("/api/instances/1/image?item_id=../etc&type=Primary")
        assert r.status_code == 400

    def test_400_invalid_tag(self, client):
        r = client.get("/api/instances/1/image?item_id=abc123&tag=../bad&type=Primary")
        assert r.status_code == 400

    def test_400_invalid_type(self, client):
        r = client.get("/api/instances/1/image?item_id=abc123&type=BadType")
        assert r.status_code == 400

    def test_400_invalid_context(self, client):
        r = client.get(
            "/api/instances/1/image?item_id=abc123&type=Primary&context=admin"
        )
        assert r.status_code == 400

    def test_200_cache_hit(self, client):
        import base64

        fake_bytes = base64.b64encode(b"imgdata").decode()
        with (
            patch(STORE_CFG, new_callable=AsyncMock) as m_cfg,
            patch(f"{CACHE}.get_cached", new_callable=AsyncMock) as m_get,
        ):
            m_cfg.return_value = CFG_EMBY
            m_get.return_value = {"b64": fake_bytes, "content_type": "image/jpeg"}
            r = client.get("/api/instances/1/image?item_id=abc123&type=Primary")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/jpeg"

    def test_200_item_context(self, client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"fake_image_bytes"
        mock_response.headers = {"content-type": "image/jpeg"}

        mock_aclient = AsyncMock()
        mock_aclient.__aenter__ = AsyncMock(return_value=mock_aclient)
        mock_aclient.__aexit__ = AsyncMock(return_value=None)
        mock_aclient.get = AsyncMock(return_value=mock_response)

        with (
            patch(STORE_CFG, new_callable=AsyncMock) as m_cfg,
            patch(f"{CACHE}.get_cached", new_callable=AsyncMock) as m_get,
            patch(f"{CACHE}.set_cached", new_callable=AsyncMock),
            patch("httpx.AsyncClient", return_value=mock_aclient),
        ):
            m_cfg.return_value = CFG_EMBY
            m_get.return_value = None  # cache miss
            r = client.get(
                "/api/instances/1/image?item_id=abc123&type=Primary&context=item"
            )
        assert r.status_code == 200

    def test_200_user_context(self, client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"avatar"
        mock_response.headers = {"content-type": "image/png"}

        mock_aclient = AsyncMock()
        mock_aclient.__aenter__ = AsyncMock(return_value=mock_aclient)
        mock_aclient.__aexit__ = AsyncMock(return_value=None)
        mock_aclient.get = AsyncMock(return_value=mock_response)

        with (
            patch(STORE_CFG, new_callable=AsyncMock) as m_cfg,
            patch(f"{CACHE}.get_cached", new_callable=AsyncMock) as m_get,
            patch(f"{CACHE}.set_cached", new_callable=AsyncMock),
            patch("httpx.AsyncClient", return_value=mock_aclient),
        ):
            m_cfg.return_value = CFG_EMBY
            m_get.return_value = None
            r = client.get(
                "/api/instances/1/image?item_id=abc123&type=Profile&context=user"
            )
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# GET /api/now-playing
# ---------------------------------------------------------------------------
class TestNowPlaying:
    def test_200_cache_miss_returns_items(self, client):
        with (
            patch(f"{CACHE}.get_cached", new_callable=AsyncMock) as m_get,
            patch(f"{CACHE}.set_cached", new_callable=AsyncMock),
            patch(
                f"{NOW_PLAYING}.refresh_now_playing_state", new_callable=AsyncMock
            ) as m_refresh,
        ):
            m_get.return_value = None
            m_refresh.return_value = {"items": []}
            r = client.get("/api/now-playing")
        assert r.status_code == 200
        assert "items" in r.json()

    def test_200_cache_hit(self, client):
        with patch(f"{CACHE}.get_cached", new_callable=AsyncMock) as m_get:
            m_get.return_value = {"items": [{"title": "Test Movie"}]}
            r = client.get("/api/now-playing")
        assert r.status_code == 200
        assert r.json()["items"][0]["title"] == "Test Movie"


# ---------------------------------------------------------------------------
# GET /api/dashboard/media-metrics
# ---------------------------------------------------------------------------
class TestDashboardMediaMetrics:
    """The merged endpoint the dashboard actually reads.

    These retarget the tests that covered /api/dashboard/emby-metrics, which
    was superseded by this one and has been removed: the caching path is
    worth keeping under test, and it is now this cache.
    """

    def test_200_merges_the_backends(self, client):
        empty = {
            "total_plays": 0,
            "total_watch_time_seconds": 0,
            "watch_time_per_user": [],
            "plays_per_user": [],
            "most_watched_items": [],
            "streaming_by_hour": [],
            "activity_by_weekday": [],
            "watch_time_by_media_type": {},
            "watch_time_per_series": [],
            "watch_time_per_movie": [],
            "watch_time_per_user_per_day": [],
            "active_users_count": 0,
            "total_watched_movies": 0,
            "total_watched_series": 0,
            "total_watched_episodes": 0,
            "total_watched_live_tv": 0,
            "avg_session_seconds": 0,
            "start_date": "2026-01-01",
            "end_date": "2026-01-07",
        }
        with (
            patch(f"{CACHE}.get_media_metrics_cached", new_callable=AsyncMock) as m_get,
            patch(f"{CACHE}.set_media_metrics_cached", new_callable=AsyncMock),
            patch.object(
                dashboard_router.store_emby_metrics,
                "get_all_metrics",
                new_callable=AsyncMock,
            ) as m_emby,
            patch.object(
                dashboard_router.store_jellyfin_metrics,
                "get_all_metrics",
                new_callable=AsyncMock,
            ) as m_jf,
            patch.object(
                dashboard_router.store_plex_metrics,
                "get_all_metrics",
                new_callable=AsyncMock,
            ) as m_plex,
        ):
            m_get.return_value = None  # cache miss
            m_emby.return_value = {**empty, "total_plays": 42}
            m_jf.return_value = {**empty, "total_plays": 7}
            m_plex.return_value = dict(empty)
            r = client.get("/api/dashboard/media-metrics")
        assert r.status_code == 200
        # The point of the endpoint: one number across every backend.
        assert r.json()["total_plays"] == 49

    def test_200_cache_hit_skips_the_stores(self, client):
        cached = {"total_plays": 7}
        with (
            patch(f"{CACHE}.get_media_metrics_cached", new_callable=AsyncMock) as m_get,
            patch.object(
                dashboard_router.store_emby_metrics,
                "get_all_metrics",
                new_callable=AsyncMock,
            ) as m_emby,
        ):
            m_get.return_value = cached
            r = client.get("/api/dashboard/media-metrics")
        assert r.status_code == 200
        assert r.json()["total_plays"] == 7
        m_emby.assert_not_awaited()
