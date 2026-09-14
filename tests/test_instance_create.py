"""Creating an instance: a connection is stored only once it has answered."""

from unittest.mock import AsyncMock, patch

ROUTER = "brein.web.routers.instances"


def test_probe_tests_a_connection_before_any_instance_exists(client):
    with patch(
        f"{ROUTER}.integration_test_service",
        new_callable=AsyncMock,
        return_value=(True, "OK"),
    ) as probe:
        r = client.post(
            "/api/instances/test",
            json={
                "service_type": "emby",
                "host": "emby.local",
                "port": 8096,
                "api_key": "abc123",
            },
        )
    assert r.status_code == 200
    assert r.json() == {"ok": True, "message": "OK"}
    probe.assert_awaited_once_with("emby", "http://emby.local:8096", "abc123")


def test_probe_needs_a_host_and_a_key(client):
    r = client.post(
        "/api/instances/test",
        json={"service_type": "emby", "host": "emby.local", "api_key": ""},
    )
    assert r.status_code == 400


def test_create_refuses_a_connection_that_does_not_answer(client):
    with (
        patch(
            f"{ROUTER}.integration_test_service",
            new_callable=AsyncMock,
            return_value=(False, "Invalid API key"),
        ),
        patch(
            f"{ROUTER}.store_instances.create_instance", new_callable=AsyncMock
        ) as create,
    ):
        r = client.post(
            "/api/instances",
            json={"service_type": "emby", "host": "emby.local", "api_key": "wrong"},
        )
    assert r.status_code == 400
    assert "Invalid API key" in r.json()["detail"]
    create.assert_not_awaited()


def test_create_stores_the_connection_once_it_has_answered(client):
    with (
        patch(
            f"{ROUTER}.integration_test_service",
            new_callable=AsyncMock,
            return_value=(True, "OK"),
        ),
        patch(
            f"{ROUTER}.store_instances.create_instance",
            new_callable=AsyncMock,
            return_value=42,
        ) as create,
        patch(f"{ROUTER}._connection_changed", new_callable=AsyncMock) as after,
    ):
        r = client.post(
            "/api/instances",
            json={
                "service_type": "emby",
                "label": "Living room",
                "host": "emby.local",
                "port": 8096,
                "api_key": "abc123",
                "external_url": "https://emby.example.com",
                "sort_order": 3,
            },
        )
    assert r.status_code == 200
    assert r.json() == {"id": 42, "ok": True}
    create.assert_awaited_once_with(
        "emby",
        label="Living room",
        host="emby.local",
        port=8096,
        api_key="abc123",
        external_url="https://emby.example.com",
        sort_order=3,
    )
    after.assert_awaited_once_with(42)


def test_create_without_a_connection_still_works_for_api_callers(client):
    with (
        patch(f"{ROUTER}.integration_test_service", new_callable=AsyncMock) as probe,
        patch(
            f"{ROUTER}.store_instances.create_instance",
            new_callable=AsyncMock,
            return_value=7,
        ),
        patch(f"{ROUTER}._connection_changed", new_callable=AsyncMock),
    ):
        r = client.post("/api/instances", json={"service_type": "sonarr"})
    assert r.status_code == 200
    assert r.json()["id"] == 7
    probe.assert_not_awaited()
