"""The SABnzbd and generic downloads routes: what they refuse, and how."""

from unittest.mock import AsyncMock, patch

STORE_CFG = "brein.store.instances.get_instance_connection_config"
SAB_API = "brein.integrations.api.sabnzbd"
SAB_STATS = "brein.store.sabnzbd_stats"

CFG_SAB = ("sabnzbd", "http://sab:8080", "apikey")
CFG_EMBY = ("emby", "http://emby:8096", "apikey")
CFG_SAB_UNCONFIGURED = ("sabnzbd", "", "")


class TestSabnzbdRoutes:
    def test_400_not_a_sabnzbd_instance(self, client):
        with (
            patch(STORE_CFG, new_callable=AsyncMock, return_value=CFG_EMBY),
            patch(f"{SAB_API}.test_connection", new_callable=AsyncMock) as probe,
        ):
            r = client.get("/api/instances/1/sabnzbd/ping")
        assert r.status_code == 400
        assert r.json()["detail"] == "Not a SABnzbd instance"
        probe.assert_not_awaited()

    def test_404_instance_not_found(self, client):
        with patch(STORE_CFG, new_callable=AsyncMock, return_value=None):
            r = client.get("/api/instances/99/sabnzbd/ping")
        assert r.status_code == 404

    def test_400_unconfigured(self, client):
        with patch(
            STORE_CFG, new_callable=AsyncMock, return_value=CFG_SAB_UNCONFIGURED
        ):
            r = client.get("/api/instances/1/sabnzbd/ping")
        assert r.status_code == 400
        assert "host" in r.json()["detail"].lower()

    def test_400_daily_stats_with_start_after_end(self, client):
        with (
            patch(STORE_CFG, new_callable=AsyncMock, return_value=CFG_SAB),
            patch(
                f"{SAB_STATS}.get_daily_series_gigabytes", new_callable=AsyncMock
            ) as series,
        ):
            r = client.get(
                "/api/instances/1/sabnzbd/stats/daily?start=2031-05-10&end=2031-05-01"
            )
        assert r.status_code == 400
        assert "start" in r.json()["detail"]
        series.assert_not_awaited()

    def test_200_daily_stats(self, client):
        with (
            patch(STORE_CFG, new_callable=AsyncMock, return_value=CFG_SAB),
            patch(
                f"{SAB_STATS}.get_daily_series_gigabytes",
                new_callable=AsyncMock,
                return_value=(["2031-05-01", "2031-05-02"], [1.5, 0.0]),
            ) as series,
        ):
            r = client.get(
                "/api/instances/1/sabnzbd/stats/daily?start=2031-05-01&end=2031-05-02"
            )
        assert r.status_code == 200
        assert r.json() == {
            "labels": ["2031-05-01", "2031-05-02"],
            "gigabytes": [1.5, 0.0],
        }
        series.assert_awaited_once()

    def test_502_speedlimit_when_unreachable(self, client):
        with (
            patch(STORE_CFG, new_callable=AsyncMock, return_value=CFG_SAB),
            patch(
                f"{SAB_API}.get_speed_limit_config",
                new_callable=AsyncMock,
                return_value=(False, None),
            ),
        ):
            r = client.get("/api/instances/1/sabnzbd/speedlimit")
        assert r.status_code == 502


class TestDownloadsRoutes:
    def test_400_unconfigured(self, client):
        with patch(
            STORE_CFG, new_callable=AsyncMock, return_value=CFG_SAB_UNCONFIGURED
        ):
            r = client.get("/api/instances/1/downloads/queue")
        assert r.status_code == 400
        assert r.json()["detail"] == "Configure host and API key first"

    def test_400_not_a_download_client(self, client):
        with patch(STORE_CFG, new_callable=AsyncMock, return_value=CFG_EMBY):
            r = client.get("/api/instances/1/downloads/queue")
        assert r.status_code == 400
        assert r.json()["detail"] == "Not a download client"

    def test_404_instance_not_found(self, client):
        with patch(STORE_CFG, new_callable=AsyncMock, return_value=None):
            r = client.get("/api/instances/99/downloads/queue")
        assert r.status_code == 404

    def test_502_when_the_client_does_not_answer(self, client):
        with (
            patch(STORE_CFG, new_callable=AsyncMock, return_value=CFG_SAB),
            patch(
                f"{SAB_API}.get_queue",
                new_callable=AsyncMock,
                return_value=(False, None),
            ),
        ):
            r = client.get("/api/instances/1/downloads/queue")
        assert r.status_code == 502
