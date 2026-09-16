"""Reading and updating an instance: what a viewer sees, what a PUT tests."""

from unittest.mock import AsyncMock, patch

import pytest

from tests.conftest import requires_db

ROUTER = "brein.web.routers.instances"
STORE = "brein.store.instances"

# Where the server lives is admin-only; the rest is what the pages render.
CONNECTION_KEYS = {"host", "port", "external_url", "api_key_masked"}

LISTED = {
    "id": 1,
    "service_type": "emby",
    "label": "Living room",
    "host": "emby.local",
    "port": 8096,
    "external_url": "https://emby.example.com",
    "active": True,
    "sort_order": 0,
    "media_server_id": "srv1",
    "is_configured": True,
    "category": "media_servers",
    "service_name": "Emby",
    "app_url": "https://emby.example.com",
    "api_key_masked": "•" * 15,
}

# What the PUT handler reads back before deciding whether to test.
STORED = {
    "id": 1,
    "service_type": "emby",
    "label": "Living room",
    "host": "emby.local",
    "port": 8096,
    "api_key": "abc123",  # pragma: allowlist secret
    "external_url": "",
    "active": True,
    "sort_order": 0,
    "media_server_id": "",
    "is_configured": True,
    "app_url": "http://emby.local:8096",
}


# ── Visibility ───────────────────────────────────────────────────────────────


def test_list_hides_the_connection_from_a_viewer(viewer_client):
    with patch(
        f"{STORE}.list_instances", new_callable=AsyncMock, return_value=[LISTED]
    ):
        r = viewer_client.get("/api/instances")
    assert r.status_code == 200
    (inst,) = r.json()["instances"]
    assert not CONNECTION_KEYS & set(inst)
    # The pages still need these.
    assert inst["label"] == "Living room"
    assert inst["app_url"] == "https://emby.example.com"
    assert inst["is_configured"] is True


def test_list_shows_the_connection_to_an_admin(client):
    with patch(
        f"{STORE}.list_instances", new_callable=AsyncMock, return_value=[LISTED]
    ):
        r = client.get("/api/instances")
    assert r.status_code == 200
    (inst,) = r.json()["instances"]
    assert CONNECTION_KEYS <= set(inst)
    assert inst["host"] == "emby.local"


def test_detail_hides_the_connection_from_a_viewer(viewer_client):
    with patch(f"{STORE}.get_instance", new_callable=AsyncMock, return_value=LISTED):
        r = viewer_client.get("/api/instances/1")
    assert r.status_code == 200
    assert not CONNECTION_KEYS & set(r.json())
    assert r.json()["label"] == "Living room"


def test_detail_shows_the_connection_to_an_admin(client):
    with patch(f"{STORE}.get_instance", new_callable=AsyncMock, return_value=LISTED):
        r = client.get("/api/instances/1")
    assert r.status_code == 200
    assert CONNECTION_KEYS <= set(r.json())


# ── PUT tests a changed connection ───────────────────────────────────────────


def _put(client, body, *, probe):
    with (
        patch(f"{STORE}.get_instance", new_callable=AsyncMock, return_value=STORED),
        patch(f"{ROUTER}.integration_test_service", new_callable=AsyncMock) as test,
        patch(f"{STORE}.update_instance", new_callable=AsyncMock) as update,
        patch(f"{ROUTER}._connection_changed", new_callable=AsyncMock) as after,
    ):
        test.return_value = probe
        r = client.put("/api/instances/1", json=body)
    return r, test, update, after


def test_put_refuses_a_changed_connection_that_does_not_answer(client):
    r, test, update, after = _put(
        client,
        {"host": "new.local", "api_key": "wrong"},  # pragma: allowlist secret
        probe=(False, "Invalid API key"),
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "Connection test failed: Invalid API key"
    test.assert_awaited_once_with("emby", "http://new.local:8096", "wrong")
    update.assert_not_awaited()
    after.assert_not_awaited()


def test_put_stores_a_changed_key_once_it_has_answered(client):
    r, test, update, after = _put(
        client,
        {"api_key": "newkey"},  # pragma: allowlist secret
        probe=(True, "OK"),
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    test.assert_awaited_once_with("emby", "http://emby.local:8096", "newkey")
    update.assert_awaited_once()
    assert update.await_args.kwargs["api_key"] == "newkey"  # pragma: allowlist secret
    after.assert_awaited_once_with(1)


def test_put_without_a_connection_change_runs_no_test(client):
    r, test, update, after = _put(client, {"label": "Bedroom"}, probe=(False, "x"))
    assert r.status_code == 200
    test.assert_not_awaited()
    update.assert_awaited_once()
    assert update.await_args.kwargs["label"] == "Bedroom"
    after.assert_awaited_once_with(1)


def test_put_with_the_same_connection_spelled_again_runs_no_test(client):
    r, test, _, _ = _put(
        client,
        {
            "host": "emby.local",
            "port": 8096,
            "api_key": "abc123",  # pragma: allowlist secret
        },
        probe=(False, "x"),
    )
    assert r.status_code == 200
    test.assert_not_awaited()


# ── Database-backed ──────────────────────────────────────────────────────────


@requires_db
@pytest.mark.asyncio(loop_scope="session")
async def test_update_keeps_the_port_when_omitted_and_clears_only_an_empty_label(
    session,
):
    """None keeps every column; it used to reset the port to the service
    default. An empty label clears it, since None cannot mean both."""
    from brein.store import instances as store_instances

    instance_id = await store_instances.create_instance(
        "emby", label="update-probe", host="emby.local", port=8097, api_key="k"
    )
    try:
        await store_instances.update_instance(instance_id, label="Renamed")
        inst = await store_instances.get_instance(instance_id)
        assert inst is not None
        assert inst["port"] == 8097
        assert inst["label"] == "Renamed"
        assert inst["host"] == "emby.local"

        await store_instances.update_instance(instance_id, label=None, port=8098)
        inst = await store_instances.get_instance(instance_id)
        assert inst is not None
        assert inst["label"] == "Renamed"
        assert inst["port"] == 8098

        await store_instances.update_instance(instance_id, label="")
        inst = await store_instances.get_instance(instance_id)
        assert inst is not None
        assert inst["label"] == ""
        assert inst["port"] == 8098
    finally:
        await store_instances.delete_instance(instance_id)
