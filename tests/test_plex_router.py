"""Plex instance endpoints: paging of the stored history, and the guards."""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

from tests.conftest import requires_db

STORE_CFG = "brein.store.instances.get_instance_connection_config"
STORE_HISTORY = "brein.store.plex_playback_sessions"

CFG_PLEX = ("plex", "http://plex:32400", "token")
CFG_EMBY = ("emby", "http://emby:8096", "apikey")

ROW = {
    "name": "Pilot",
    "date": "2031-05-04T12:00:00Z",
    "type": "episode",
    "user_id": 701,
    "rating_key": "9001",
}


def _history(client, query: str, rows=(ROW,), total: int = 33):
    with (
        patch(STORE_CFG, new_callable=AsyncMock, return_value=CFG_PLEX),
        patch(
            f"{STORE_HISTORY}.get_entries",
            new_callable=AsyncMock,
            return_value=list(rows),
        ) as entries,
        patch(
            f"{STORE_HISTORY}.count_entries", new_callable=AsyncMock, return_value=total
        ) as count,
    ):
        r = client.get(f"/api/instances/1/plex/history{query}")
    return r, entries, count


class TestPlexHistory:
    def test_200_pages_through_the_store(self, client):
        r, entries, count = _history(client, "?account_id=701&start=40&size=20")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total_size"] == 33
        assert body["history"] == [
            {
                "title": "Pilot",
                "viewedAt": "2031-05-04T12:00:00Z",
                "type": "episode",
                "accountID": 701,
                "ratingKey": "9001",
            }
        ]
        entries.assert_awaited_once_with(1, user_id=701, limit=20, offset=40)
        count.assert_awaited_once_with(1, user_id=701)

    def test_200_defaults(self, client):
        r, entries, count = _history(client, "")
        assert r.status_code == 200
        entries.assert_awaited_once_with(1, user_id=None, limit=100, offset=0)
        count.assert_awaited_once_with(1, user_id=None)

    def test_422_out_of_range_paging(self, client):
        for query in ("?start=-1", "?size=0", "?size=501"):
            r, entries, _ = _history(client, query)
            assert r.status_code == 422, query
            entries.assert_not_awaited()

    def test_400_not_a_plex_instance(self, client):
        with patch(STORE_CFG, new_callable=AsyncMock, return_value=CFG_EMBY):
            r = client.get("/api/instances/1/plex/history")
        assert r.status_code == 400
        assert r.json()["detail"] == "Instance is not a Plex server"

    def test_404_instance_not_found(self, client):
        with patch(STORE_CFG, new_callable=AsyncMock, return_value=None):
            r = client.get("/api/instances/99/plex/history")
        assert r.status_code == 404


class TestPlexSessions:
    def test_502_when_plex_does_not_answer(self, client):
        with (
            patch(STORE_CFG, new_callable=AsyncMock, return_value=CFG_PLEX),
            patch(
                "brein.integrations.api.plex.get_sessions",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            r = client.get("/api/instances/1/plex/sessions")
        assert r.status_code == 502


# ── Database-backed: the store the history route pages through ───────────────

# Clear of the ids the other database-backed tests use.
PLEX_INSTANCE = 91_004


async def _seed_history(session) -> None:
    await session.execute(
        text("DELETE FROM plex_playback_sessions WHERE instance_id = :i"),
        {"i": PLEX_INSTANCE},
    )
    await session.execute(
        text("DELETE FROM app_instances WHERE id = :i"), {"i": PLEX_INSTANCE}
    )
    await session.execute(
        text(
            "INSERT INTO app_instances"
            " (id, service_type, label, host, api_key, external_url, active, sort_order)"
            " VALUES (:i, 'plex', 'Plex box', 'http://localhost', '', '', TRUE, 0)"
        ),
        {"i": PLEX_INSTANCE},
    )
    # Three plays for account 701, one for 702, each ending an hour apart.
    for n, account in enumerate((701, 701, 701, 702), start=1):
        await session.execute(
            text(
                "INSERT INTO plex_playback_sessions"
                " (instance_id, account_id, account_title, rating_key, item_type,"
                "  title, plex_session_key, start_time, end_time, watched_seconds)"
                " VALUES (:i, :account, 'Ada', :key, 'movie', :title, :sess,"
                "  :start, :end, 600)"
            ),
            {
                "i": PLEX_INSTANCE,
                "account": account,
                "key": str(9000 + n),
                "title": f"Film {n}",
                "sess": f"sess-{n}",
                "start": f"2031-05-04T{n:02d}:00:00Z",
                "end": f"2031-05-04T{n:02d}:30:00Z",
            },
        )
    await session.commit()


@requires_db
@pytest.mark.asyncio(loop_scope="session")
async def test_history_store_pages_and_counts_per_account(session):
    from brein.store import plex_playback_sessions as store

    await _seed_history(session)
    try:
        assert await store.count_entries(PLEX_INSTANCE) == 4
        assert await store.count_entries(PLEX_INSTANCE, user_id=701) == 3
        assert await store.count_entries(PLEX_INSTANCE, user_id=999) == 0

        # Newest first; offset skips the newest of 701's three.
        page = await store.get_entries(PLEX_INSTANCE, user_id=701, limit=2, offset=1)
        assert [row["name"] for row in page] == ["Film 2", "Film 1"]
        assert {row["user_id"] for row in page} == {701}

        past_the_end = await store.get_entries(
            PLEX_INSTANCE, user_id=701, limit=2, offset=3
        )
        assert past_the_end == []
    finally:
        await session.execute(
            text("DELETE FROM app_instances WHERE id = :i"), {"i": PLEX_INSTANCE}
        )
        await session.commit()
