"""The extension seam: core registers itself; extras are optional."""

import importlib


def test_core_service_types_present_without_extras(monkeypatch):
    import brein.extras as extras

    monkeypatch.setattr(extras, "EXTRAS", [])
    from brein.extensions import load_extensions

    ext = load_extensions()
    assert set(ext.service_types) == {
        "emby",
        "jellyfin",
        "plex",
        "sonarr",
        "radarr",
        "sabnzbd",
    }


def test_extras_register_when_listed():
    from brein.extensions import load_extensions

    ext = load_extensions()
    # Whatever brein/extras lists is loaded; the private tree lists five groups
    # and tests/extras asserts the ids they register. Here: something beyond
    # core showed up, without naming it.
    import brein.extras as extras

    core = {"emby", "jellyfin", "plex", "sonarr", "radarr", "sabnzbd"}
    if extras.EXTRAS:
        assert set(ext.service_types) - core


def _paths(router) -> set[str]:
    out: set[str] = set()
    for route in router.routes:
        # FastAPI 0.141's lazy `_IncludedRouter` wrapper (used for every
        # app.include_router(...) call) exposes the routes it wraps via
        # `.original_router`, not `.routes` directly.
        nested = getattr(route, "original_router", None) or (
            route if hasattr(route, "routes") else None
        )
        if nested is not None:
            out |= _paths(nested)
        else:
            path = getattr(route, "path", None)
            if path:
                out.add(path)
    return out


def test_sabnzbd_downloader_registered_with_capabilities():
    from brein.extensions import load_extensions

    d = load_extensions().downloaders["sabnzbd"]
    assert d.capabilities.per_item_pause is True
    assert d.capabilities.queue_level_pause is True
    assert d.capabilities.history == "list"


def test_app_imports_with_stub(monkeypatch):
    import brein.extras as extras

    monkeypatch.setattr(extras, "EXTRAS", [])
    from brein import extensions

    extensions.reset_extensions()
    app_module = importlib.import_module("brein.web.app")
    importlib.reload(app_module)
    assert "/api/service-types" in _paths(app_module.app)


def test_service_types_endpoint_carries_tabs_and_icon(client):
    r = client.get("/api/service-types")
    assert r.status_code == 200
    by_id = {s["id"]: s for s in r.json()["service_types"]}
    assert by_id["sonarr"]["tabs"][0] == {
        "slug": "queue",
        "label": "Queue",
        "admin_only": False,
    }
    assert by_id["emby"]["icon"] is True
    assert "arr_tables" in by_id["sonarr"]
