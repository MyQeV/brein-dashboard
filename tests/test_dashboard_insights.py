"""The cross-backend insight queries, against real rows.

These three answer questions no per-backend module can: how many streams ran
at the same moment across every server, who has stopped watching anywhere, and
what nobody has ever played. Each is a single hand-written query whose shape is
easy to get subtly wrong — an off-by-one in the concurrency sweep, a join that
drops a user, a filter that counts a title twice — so they are exercised here
with rows placed to make those mistakes visible.
"""

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from brein.store import dashboard_insights as insights
from tests.conftest import requires_db

# The `session` fixture is session-scoped, so its tests must share that loop.
pytestmark = [pytest.mark.asyncio(loop_scope="session"), requires_db]

# Well clear of any real instance id the other database-backed tests create.
INSTANCE_A = 90_001
INSTANCE_B = 90_002

DAY = "2031-03-05"


def _utc(hour: int, minute: int = 0) -> str:
    """A UTC timestamp on DAY, in the ISO form the sync jobs store."""
    return f"{DAY}T{hour:02d}:{minute:02d}:00.0000000Z"


async def _reset(session) -> None:
    for table, column in (
        ("emby_playback_sessions", "instance_id"),
        ("jellyfin_playback_sessions", "instance_id"),
        ("plex_playback_sessions", "instance_id"),
        ("emby_items", "instance_id"),
        ("emby_users", "instance_id"),
        ("app_instances", "id"),
    ):
        await session.execute(
            text(f"DELETE FROM {table} WHERE {column} IN (:a, :b)"),
            {"a": INSTANCE_A, "b": INSTANCE_B},
        )
    await session.commit()


async def _instances(session) -> None:
    for instance_id, label in ((INSTANCE_A, "Server A"), (INSTANCE_B, "Server B")):
        await session.execute(
            text(
                "INSERT INTO app_instances"
                " (id, service_type, label, host, api_key, external_url,"
                "  active, sort_order)"
                " VALUES (:id, 'emby', :label, 'http://localhost', '', '',"
                "  TRUE, 0)"
            ),
            {"id": instance_id, "label": label},
        )
    await session.commit()


async def _emby_session(
    session, *, instance_id: int, user_id: int, item_id: int, start: str, seconds: int
) -> None:
    started = datetime.strptime(start[:19], "%Y-%m-%dT%H:%M:%S").replace(
        tzinfo=timezone.utc
    )
    ended = started + timedelta(seconds=seconds)
    await session.execute(
        text(
            "INSERT INTO emby_playback_sessions"
            " (instance_id, user_id, item_id, start_time, end_time, duration_seconds)"
            " VALUES (:instance_id, :user_id, :item_id, :start, :end, :seconds)"
        ),
        {
            "instance_id": instance_id,
            "user_id": user_id,
            "item_id": item_id,
            "start": start,
            "end": ended.strftime("%Y-%m-%dT%H:%M:%S.0000000Z"),
            "seconds": seconds,
        },
    )


class TestConcurrency:
    async def test_counts_overlap_across_servers(self, session):
        """Two streams at once on different servers are two, not one each."""
        await _reset(session)
        await _instances(session)
        # 10:00-11:00 on A, 10:30-11:30 on B — overlapping by half an hour.
        await _emby_session(
            session,
            instance_id=INSTANCE_A,
            user_id=1,
            item_id=1,
            start=_utc(10),
            seconds=3600,
        )
        await _emby_session(
            session,
            instance_id=INSTANCE_B,
            user_id=2,
            item_id=2,
            start=_utc(10, 30),
            seconds=3600,
        )
        await session.commit()

        rows = await insights.get_concurrency_by_day(DAY, DAY)
        peaks = {row["date"]: row["peak"] for row in rows}
        assert peaks.get(DAY) == 2

    async def test_back_to_back_streams_are_not_double_counted(self, session):
        """One stream ending exactly as the next begins is never two at once."""
        await _reset(session)
        await _instances(session)
        await _emby_session(
            session,
            instance_id=INSTANCE_A,
            user_id=1,
            item_id=1,
            start=_utc(10),
            seconds=3600,
        )
        await _emby_session(
            session,
            instance_id=INSTANCE_A,
            user_id=1,
            item_id=2,
            start=_utc(11),
            seconds=3600,
        )
        await session.commit()

        rows = await insights.get_concurrency_by_day(DAY, DAY)
        peaks = {row["date"]: row["peak"] for row in rows}
        assert peaks.get(DAY) == 1

    async def test_scopes_to_the_requested_instance(self, session):
        await _reset(session)
        await _instances(session)
        await _emby_session(
            session,
            instance_id=INSTANCE_A,
            user_id=1,
            item_id=1,
            start=_utc(10),
            seconds=3600,
        )
        await _emby_session(
            session,
            instance_id=INSTANCE_B,
            user_id=2,
            item_id=2,
            start=_utc(10),
            seconds=3600,
        )
        await session.commit()

        rows = await insights.get_concurrency_by_day(DAY, DAY, INSTANCE_A)
        assert {row["date"]: row["peak"] for row in rows}.get(DAY) == 1

    async def test_survives_more_than_ten_user_keys(self, session):
        """The union renames each arm's bind parameters; ":inst_1" must not
        rewrite the prefix of ":inst_10". A plain str.replace did, and the
        query then referenced names no parameter matched — a 500 as soon as
        eleven users were selected."""
        await _reset(session)
        await _instances(session)
        await _emby_session(
            session,
            instance_id=INSTANCE_A,
            user_id=1,
            item_id=1,
            start=_utc(10),
            seconds=3600,
        )
        await session.commit()

        keys = [f"{INSTANCE_A}:{n}" for n in range(1, 13)]
        rows = await insights.get_concurrency_by_day(DAY, DAY, None, keys)
        assert {row["date"]: row["peak"] for row in rows}.get(DAY) == 1

    async def test_counts_a_stream_that_began_the_night_before(self, session):
        """A stream running at 00:30 counts, even though it started yesterday.

        Bounding the scan exactly at the range start dropped it, and the first
        day of every range opened with an artificially empty chart.
        """
        await _reset(session)
        await _instances(session)
        yesterday = (date.fromisoformat(DAY) - timedelta(days=1)).isoformat()
        await _emby_session(
            session,
            instance_id=INSTANCE_A,
            user_id=1,
            item_id=1,
            start=f"{yesterday}T23:30:00.0000000Z",
            seconds=3600,
        )
        await session.commit()

        rows = await insights.get_concurrency_by_day(DAY, DAY)
        assert {row["date"]: row["peak"] for row in rows}.get(DAY) == 1

    async def test_never_reports_a_day_outside_the_range(self, session):
        """A stream crossing midnight must not invent a day of its own.

        The scan deliberately reaches a day either side to catch overlap, so
        the output has to be trimmed back. Asserted as containment rather than
        equality because the app timezone decides which local day a UTC
        evening start belongs to.
        """
        await _reset(session)
        await _instances(session)
        await _emby_session(
            session,
            instance_id=INSTANCE_A,
            user_id=1,
            item_id=1,
            start=_utc(23, 30),
            seconds=3600,
        )
        await session.commit()

        rows = await insights.get_concurrency_by_day(DAY, DAY)
        assert all(
            row["date"] == DAY for row in rows
        ), f"days outside the range leaked through: {[r['date'] for r in rows]}"


class TestIdleUsers:
    async def test_reports_the_never_and_the_long_ago(self, session):
        await _reset(session)
        await _instances(session)
        recent = datetime.now(timezone.utc) - timedelta(days=1)
        stale = datetime.now(timezone.utc) - timedelta(days=400)

        for user_id, name in ((1, "watcher"), (2, "lapsed"), (3, "never")):
            await session.execute(
                text(
                    "INSERT INTO emby_users"
                    " (instance_id, user_id, name, user_item_id, is_deleted)"
                    " VALUES (:instance_id, :user_id, :name, :user_item_id, 0)"
                ),
                {
                    "instance_id": INSTANCE_A,
                    "user_id": str(user_id),
                    "name": name,
                    "user_item_id": str(user_id),
                },
            )
        await _emby_session(
            session,
            instance_id=INSTANCE_A,
            user_id=1,
            item_id=1,
            start=recent.strftime("%Y-%m-%dT%H:%M:%S.0000000Z"),
            seconds=600,
        )
        await _emby_session(
            session,
            instance_id=INSTANCE_A,
            user_id=2,
            item_id=1,
            start=stale.strftime("%Y-%m-%dT%H:%M:%S.0000000Z"),
            seconds=600,
        )
        await session.commit()

        idle = await insights.get_idle_users(30, INSTANCE_A)
        names = {row["display_name"] for row in idle}
        assert "watcher" not in names, "someone who watched yesterday is not idle"
        assert {"lapsed", "never"} <= names

    async def test_names_the_server(self, session):
        await _reset(session)
        await _instances(session)
        await session.execute(
            text(
                "INSERT INTO emby_users"
                " (instance_id, user_id, name, user_item_id, is_deleted)"
                " VALUES (:instance_id, '7', 'solo', '7', 0)"
            ),
            {"instance_id": INSTANCE_B},
        )
        await session.commit()

        idle = await insights.get_idle_users(30, INSTANCE_B)
        assert [row["instance_label"] for row in idle] == ["Server B"]


class TestUnwatchedLibrary:
    async def test_counts_only_what_was_never_played(self, session):
        await _reset(session)
        await _instances(session)
        for item_id, item_type in (("11", "Movie"), ("12", "Movie"), ("13", "Episode")):
            await session.execute(
                text(
                    "INSERT INTO emby_items (instance_id, item_id, type, name)"
                    " VALUES (:instance_id, :item_id, :type, :name)"
                ),
                {
                    "instance_id": INSTANCE_A,
                    "item_id": item_id,
                    "type": item_type,
                    "name": f"Title {item_id}",
                },
            )
        # Only item 11 has ever been played.
        await _emby_session(
            session,
            instance_id=INSTANCE_A,
            user_id=1,
            item_id=11,
            start=_utc(9),
            seconds=600,
        )
        await session.commit()

        summary = {
            row["item_type"]: row
            for row in await insights.get_unwatched_summary(INSTANCE_A)
        }
        assert summary["Movie"]["total"] == 2
        assert summary["Movie"]["unwatched"] == 1
        assert summary["Episode"]["unwatched"] == 1

        titles = [
            row["title"]
            for row in await insights.get_unwatched_items("Movie", INSTANCE_A)
        ]
        assert titles == ["Title 12"]

    async def test_a_play_on_one_server_does_not_clear_another(self, session):
        """Item ids repeat across servers; the join must be scoped to both."""
        await _reset(session)
        await _instances(session)
        for instance_id in (INSTANCE_A, INSTANCE_B):
            await session.execute(
                text(
                    "INSERT INTO emby_items (instance_id, item_id, type, name)"
                    " VALUES (:instance_id, '11', 'Movie', 'Shared id')"
                ),
                {"instance_id": instance_id},
            )
        await _emby_session(
            session,
            instance_id=INSTANCE_A,
            user_id=1,
            item_id=11,
            start=_utc(9),
            seconds=600,
        )
        await session.commit()

        by_instance = {
            row["instance_id"]: row["unwatched"]
            for row in await insights.get_unwatched_summary([INSTANCE_A, INSTANCE_B])
        }
        assert by_instance[INSTANCE_A] == 0
        assert by_instance[INSTANCE_B] == 1
