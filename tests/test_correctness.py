"""Regression tests for the P1 correctness fixes."""

import asyncio

import pytest


# ── Cache is bounded ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cache_stays_under_the_byte_limit():
    """Poster images are cached as base64. Before this bound the process grew
    until the hourly sweep happened to run."""
    from brein import cache

    original = cache.MAX_CACHE_BYTES
    cache.MAX_CACHE_BYTES = 50_000
    try:
        cache._store.clear()
        blob = "x" * 10_000
        for i in range(20):
            await cache.set_cached(f"image:{i}", blob, ttl_seconds=300)
        assert cache._current_bytes() <= 50_000
    finally:
        cache.MAX_CACHE_BYTES = original
        cache._store.clear()


@pytest.mark.asyncio
async def test_cache_evicts_expired_entries_before_live_ones():
    from brein import cache

    original = cache.MAX_CACHE_BYTES
    cache.MAX_CACHE_BYTES = 30_000
    try:
        cache._store.clear()
        await cache.set_cached("stale", "y" * 10_000, ttl_seconds=-1)
        await cache.set_cached("fresh", "z" * 10_000, ttl_seconds=600)
        await cache.set_cached("newest", "w" * 10_000, ttl_seconds=600)
        assert await cache.get_cached("stale") is None
        assert await cache.get_cached("newest") is not None
    finally:
        cache.MAX_CACHE_BYTES = original
        cache._store.clear()


# ── Background tasks are not garbage collected ───────────────────────────────


@pytest.mark.asyncio
async def test_spawned_task_is_referenced_until_it_finishes():
    """asyncio.create_task only holds a weak reference; an unreferenced task
    can be collected mid-flight and simply stop."""
    from brein import background

    started = asyncio.Event()
    finished = asyncio.Event()

    async def _work():
        started.set()
        await asyncio.sleep(0)
        finished.set()

    task = background.spawn(_work(), "test-task")
    await started.wait()
    assert background.pending_count() >= 1
    await task
    assert finished.is_set()


@pytest.mark.asyncio
async def test_spawn_logs_failures_instead_of_losing_them(caplog):
    from brein import background

    async def _boom():
        raise RuntimeError("expected failure")

    with caplog.at_level("ERROR", logger="brein.background"):
        task = background.spawn(_boom(), "failing-task")
        with pytest.raises(RuntimeError):
            await task
        await asyncio.sleep(0)
    assert "failing-task" in caplog.text
    assert "expected failure" in caplog.text


def test_no_unreferenced_create_task_remains():
    """Every fire-and-forget call site must go through background.spawn()."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent / "brein"
    offenders = []
    for path in root.rglob("*.py"):
        lines = path.read_text().splitlines()
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if not stripped.startswith("asyncio.create_task("):
                continue
            # A result that is assigned, returned or appended is referenced
            # deliberately and stays alive; only a bare statement is at risk.
            previous = lines[i - 2].strip() if i >= 2 else ""
            if previous.endswith(("append(", "= [", "return [")):
                continue
            offenders.append(f"{path.relative_to(root.parent)}:{i}")
    assert offenders == [], f"unreferenced create_task at: {offenders}"


# ── Startup ──────────────────────────────────────────────────────────────────


def test_main_does_not_initialise_the_database():
    """The lifespan runs init_db(); main.py doing it too ran the schema DDL
    twice and built an engine in a process that then forks under reload."""
    import pathlib

    source = (pathlib.Path(__file__).resolve().parent.parent / "main.py").read_text()
    code_lines = [
        line for line in source.splitlines() if not line.strip().startswith("#")
    ]
    assert not any("init_db()" in line for line in code_lines)


def test_unhandled_exception_handler_does_not_bypass_logging():
    """print_exc wrote outside the logging config, skipping the rotating
    file handler, and duplicated the log.exception above it."""
    import inspect

    from brein.web import app as app_module

    source = inspect.getsource(app_module.unhandled_exception_handler)
    assert "log.exception" in source
    assert "print_exc" not in source


# ── Jellyfin dispatch ────────────────────────────────────────────────────────


def test_media_router_never_calls_the_emby_module_directly():
    """The Emby router also serves Jellyfin. Jellyfin overrides
    test_connection, get_users and get_media_folders, so a direct
    emby_integration.* call silently used the wrong implementation."""
    import pathlib

    source = (
        pathlib.Path(__file__).resolve().parent.parent
        / "brein"
        / "web"
        / "routers"
        / "emby.py"
    ).read_text()
    assert "await emby_integration." not in source


def test_jellyfin_overrides_are_reachable_through_the_dispatcher():
    from brein.integrations.api import emby, jellyfin
    from brein.web.routers.emby import _media_integration

    assert _media_integration("jellyfin") is jellyfin
    assert _media_integration("emby") is emby
    # These three differ between the two servers; the rest are re-exports.
    for name in ("test_connection", "get_users", "get_media_folders"):
        assert getattr(jellyfin, name) is not getattr(emby, name), name


# ── One source of truth for scheduled-task cadence ───────────────────────────


def test_no_setting_duplicates_a_scheduled_task_interval():
    """The runner reads scheduled_tasks.interval_seconds and nothing else.

    A settings row carrying the same cadence rendered as an editable field
    that changed nothing, because the reconciler's upsert deliberately
    preserves interval_seconds so per-task edits survive.
    """
    from brein.store.system_settings import get_catalog

    catalog_keys = {entry["key"] for entry in get_catalog()}
    for key in (
        "emby_activity_sync_interval_seconds",
        "users_sync_interval_seconds",
        "items_sync_interval_seconds",
        "sabnzbd_server_stats_interval_seconds",
    ):
        assert (
            key not in catalog_keys
        ), f"{key} duplicates a scheduled-task cadence; retune the task instead"


def test_registry_defaults_are_seed_only():
    """Registry intervals are insert-time defaults: the upsert must update
    only name and category, or a reconcile would clobber the user's edit."""
    import inspect

    from brein.store import scheduled_tasks

    source = inspect.getsource(scheduled_tasks.upsert_task)
    # The SET clause only — the params dict below it names every column.
    set_clause = source.split("DO UPDATE", 1)[1].split('"""', 1)[0]
    assert "interval_seconds" not in set_clause
    assert "enabled" not in set_clause
    assert "name = EXCLUDED.name" in set_clause


def test_interval_env_vars_still_seed_the_registry():
    """Removing the settings rows must not remove the env-driven defaults."""
    from brein.jobs.scheduled_task_registry import task_types

    for key in ("emby_users_sync", "emby_items_sync", "sabnzbd_server_stats_sync"):
        assert task_types()[key].default_interval_seconds > 0
