"""The drill queries' row shape, across all three media backends.

The dashboard merges Emby, Jellyfin and Plex rows into one list and renders
them through one table, so every drill has to hand back the same keys. Nothing
enforced that: each backend has its own module with its own hand-written SQL
and its own dict literal, and a column added to one of them shows up as an
empty cell for the other two — silently, because the frontend reads rows
defensively and a missing key just renders blank.

These tests seed one session per backend and compare the key sets.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from brein import config as brein_config

from brein.store import jellyfin_dashboard_metrics as jellyfin
from brein.store import metrics_playback as emby
from brein.store import plex_dashboard_metrics as plex
from tests.conftest import requires_db

pytestmark = [pytest.mark.asyncio(loop_scope="session"), requires_db]

# Clear of the ids the other database-backed tests use.
EMBY_INSTANCE = 91_001
JELLYFIN_INSTANCE = 91_002
PLEX_INSTANCE = 91_003

DAY = "2031-05-04"

# What a drill row must carry. The frontend's session table reads exactly
# these; a backend that drops one renders an empty column for its rows only.
ROW_KEYS = frozenset(
    {
        "user_display_name",
        "title",
        "item_type",
        "series_name",
        "season_number",
        "episode_number",
        "instance_label",
        "played_at",
        "duration_seconds",
    }
)

# A user drill is one user's sessions, so those queries drop the name column
# on purpose — the modal's title already says whose they are.
USER_DRILL_KEYS = ROW_KEYS - {"user_display_name"}

# The stored form: the sync jobs keep the API's own string rather than parsing
# it, so every start_time is UTC text. Midday, so the play stays on DAY in
# every zone the suite might inherit from .env: at 20:00Z anything east of
# UTC+4 rolled the local date over and the DAY..DAY drills found nothing.
START_HOUR_UTC = 12
START = f"{DAY}T{START_HOUR_UTC:02d}:00:00.0000000Z"
SECONDS = 1800

# The hour drill buckets in the app's zone, not UTC, so the bucket a midday
# UTC play lands in depends on TZ. Resolved here rather than hard-coded, or
# this test passes only in London.
LOCAL_HOUR = (
    datetime(2031, 5, 4, START_HOUR_UTC, tzinfo=timezone.utc)
    .astimezone(ZoneInfo(brein_config.TIMEZONE))
    .hour
)


def _end(start: str, seconds: int) -> str:
    started = datetime.strptime(start[:19], "%Y-%m-%dT%H:%M:%S").replace(
        tzinfo=timezone.utc
    )
    return (started + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%S.0000000Z")


async def _reset(session) -> None:
    ids = {
        "e": EMBY_INSTANCE,
        "j": JELLYFIN_INSTANCE,
        "p": PLEX_INSTANCE,
    }
    for table, column in (
        ("emby_playback_sessions", "instance_id"),
        ("jellyfin_playback_sessions", "instance_id"),
        ("plex_playback_sessions", "instance_id"),
        ("emby_items", "instance_id"),
        ("jellyfin_items", "instance_id"),
        ("emby_users", "instance_id"),
        ("jellyfin_users", "instance_id"),
        ("app_instances", "id"),
    ):
        await session.execute(
            text(f"DELETE FROM {table} WHERE {column} IN (:e, :j, :p)"), ids
        )
    await session.commit()


async def _seed(session) -> None:
    """One episode play per backend, with the series and user rows to join to."""
    for instance_id, service, label in (
        (EMBY_INSTANCE, "emby", "Emby box"),
        (JELLYFIN_INSTANCE, "jellyfin", "Jellyfin box"),
        (PLEX_INSTANCE, "plex", "Plex box"),
    ):
        await session.execute(
            text(
                "INSERT INTO app_instances"
                " (id, service_type, label, host, api_key, external_url,"
                "  active, sort_order)"
                " VALUES (:id, :service, :label, 'http://localhost', '', '',"
                "  TRUE, 0)"
            ),
            {"id": instance_id, "service": service, "label": label},
        )

    # Emby: numeric session ids joined to text item ids.
    await session.execute(
        text(
            "INSERT INTO emby_items"
            " (instance_id, item_id, type, name, series_id,"
            "  index_number, parent_index_number)"
            " VALUES (:i, '7001', 'Episode', 'Pilot', '7000', 2, 1)"
        ),
        {"i": EMBY_INSTANCE},
    )
    await session.execute(
        text(
            "INSERT INTO emby_items (instance_id, item_id, type, name)"
            " VALUES (:i, '7000', 'Series', 'Test Show')"
        ),
        {"i": EMBY_INSTANCE},
    )
    await session.execute(
        text(
            # user_id is the primary key; user_item_id is what the drills
            # join on. The sync writes both, so seed both.
            "INSERT INTO emby_users"
            " (instance_id, user_id, user_item_id, name, is_deleted)"
            " VALUES (:i, '501', '501', 'Ada', 0)"
        ),
        {"i": EMBY_INSTANCE},
    )
    await session.execute(
        text(
            "INSERT INTO emby_playback_sessions"
            " (instance_id, user_id, item_id, start_time, end_time,"
            "  duration_seconds)"
            " VALUES (:i, 501, 7001, :start, :end, :seconds)"
        ),
        {
            "i": EMBY_INSTANCE,
            "start": START,
            "end": _end(START, SECONDS),
            "seconds": SECONDS,
        },
    )

    # Jellyfin: the same shape, but the ids are text throughout.
    await session.execute(
        text(
            "INSERT INTO jellyfin_items"
            " (instance_id, item_id, type, name, series_id,"
            "  index_number, parent_index_number)"
            " VALUES (:i, '8001', 'Episode', 'Pilot', '8000', 2, 1)"
        ),
        {"i": JELLYFIN_INSTANCE},
    )
    await session.execute(
        text(
            "INSERT INTO jellyfin_items (instance_id, item_id, type, name)"
            " VALUES (:i, '8000', 'Series', 'Test Show')"
        ),
        {"i": JELLYFIN_INSTANCE},
    )
    await session.execute(
        text(
            # Jellyfin's drills join on user_id itself, not user_item_id.
            "INSERT INTO jellyfin_users"
            " (instance_id, user_id, name, is_deleted)"
            " VALUES (:i, '601', 'Ada', 0)"
        ),
        {"i": JELLYFIN_INSTANCE},
    )
    await session.execute(
        text(
            "INSERT INTO jellyfin_playback_sessions"
            " (instance_id, user_id, item_id, start_time, end_time,"
            "  duration_seconds)"
            " VALUES (:i, '601', '8001', :start, :end, :seconds)"
        ),
        {
            "i": JELLYFIN_INSTANCE,
            "start": START,
            "end": _end(START, SECONDS),
            "seconds": SECONDS,
        },
    )

    # Plex carries the titles on the session row itself — there is no items
    # table to join, which is exactly why its row shape drifts most easily.
    await session.execute(
        text(
            "INSERT INTO plex_playback_sessions"
            " (instance_id, account_id, account_title, rating_key, item_type,"
            "  title, grandparent_title, parent_title, plex_session_key,"
            "  start_time, end_time, watched_seconds)"
            " VALUES (:i, 701, 'Ada', '9001', 'episode', 'Pilot',"
            "  'Test Show', 'Season 1', 'sess-1', :start, :end, :seconds)"
        ),
        {
            "i": PLEX_INSTANCE,
            "start": START,
            "end": _end(START, SECONDS),
            "seconds": SECONDS,
        },
    )
    await session.commit()


async def _drills(module, instance_id: int) -> dict[str, list[dict]]:
    """Every drill the dashboard can open, for one backend."""
    return {
        "media_type": await module.get_media_type_sessions(
            DAY, DAY, "Episode", instance_id=instance_id
        ),
        "time": await module.get_time_sessions(
            DAY, DAY, "hour", LOCAL_HOUR, instance_id=instance_id
        ),
        "all": await module.get_all_sessions(DAY, DAY, instance_id=instance_id),
        "item": await module.get_item_sessions(
            DAY, DAY, "Test Show", "series", instance_id=instance_id
        ),
    }


class TestDrillRowContract:
    async def test_every_backend_returns_the_same_keys(self, session):
        await _reset(session)
        await _seed(session)

        by_backend = {
            "emby": await _drills(emby, EMBY_INSTANCE),
            "jellyfin": await _drills(jellyfin, JELLYFIN_INSTANCE),
            "plex": await _drills(plex, PLEX_INSTANCE),
        }

        for drill in ("media_type", "time", "all", "item"):
            for backend, drills in by_backend.items():
                rows = drills[drill]
                assert rows, f"{backend} {drill} drill returned nothing to compare"
                assert set(rows[0]) == ROW_KEYS, (
                    f"{backend} {drill} drill keys drifted: "
                    f"missing {sorted(ROW_KEYS - set(rows[0]))}, "
                    f"extra {sorted(set(rows[0]) - ROW_KEYS)}"
                )

    async def test_every_backend_resolves_the_episode_the_same_way(self, session):
        """A row must name the series and the episode, not just an id.

        The modal prints "Test Show — Pilot (S01E02)", which needs four of the
        joined columns to survive. Emby and Jellyfin reach them through their
        items tables; Plex reads them off the session row.
        """
        await _reset(session)
        await _seed(session)

        for module, instance_id in (
            (emby, EMBY_INSTANCE),
            (jellyfin, JELLYFIN_INSTANCE),
            (plex, PLEX_INSTANCE),
        ):
            rows = await module.get_all_sessions(DAY, DAY, instance_id=instance_id)
            row = rows[0]
            assert row["title"] == "Pilot"
            assert row["series_name"] == "Test Show"
            assert row["user_display_name"] == "Ada"
            assert row["duration_seconds"] == SECONDS
            assert row["instance_label"]
            # The type is spelled differently per API (Plex lowercases it);
            # what matters is that it is not blank, since the modal branches on
            # it to decide whether to print an episode code at all.
            assert row["item_type"]

    async def test_user_drill_keeps_the_contract(self, session):
        """The one drill with a different signature — it takes a user id."""
        await _reset(session)
        await _seed(session)

        for module, instance_id, user_id in (
            (emby, EMBY_INSTANCE, "501"),
            (jellyfin, JELLYFIN_INSTANCE, "601"),
            (plex, PLEX_INSTANCE, "701"),
        ):
            rows = await module.get_user_sessions(
                DAY, DAY, user_id, instance_id=instance_id
            )
            assert rows, f"no user drill rows for instance {instance_id}"
            assert set(rows[0]) == USER_DRILL_KEYS
