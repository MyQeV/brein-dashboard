"""The hourly library sync re-sends the whole library; only changed rows may
be rewritten, or updated_at says when the library was last walked rather
than when the item last changed."""

import pytest
from sqlalchemy import text

from brein.store import emby_items as store
from tests.conftest import requires_db

pytestmark = [pytest.mark.asyncio(loop_scope="session"), requires_db]

# Clear of the ids the other database-backed tests use.
EMBY_INSTANCE = 91_005

ITEM = {"Id": "4001", "Name": "Pilot", "Type": "Episode", "SeriesId": "4000"}


async def _drop(session) -> None:
    # The items go with the instance: emby_items.instance_id cascades.
    await session.execute(
        text("DELETE FROM app_instances WHERE id = :i"), {"i": EMBY_INSTANCE}
    )
    await session.commit()


async def _reset(session) -> None:
    await _drop(session)
    await session.execute(
        text(
            "INSERT INTO app_instances"
            " (id, service_type, label, host, api_key, external_url, active, sort_order)"
            " VALUES (:i, 'emby', 'Emby box', 'http://localhost', '', '', TRUE, 0)"
        ),
        {"i": EMBY_INSTANCE},
    )
    await session.commit()


async def _updated_at() -> str:
    (row,) = await store.get_items(EMBY_INSTANCE)
    return row["updated_at"]


async def test_an_unchanged_row_keeps_its_updated_at(session):
    await _reset(session)
    try:
        await store.upsert_items_bulk(EMBY_INSTANCE, [ITEM])
        first = await _updated_at()
        await store.upsert_items_bulk(EMBY_INSTANCE, [dict(ITEM)])
        assert await _updated_at() == first
    finally:
        await _drop(session)


async def test_a_changed_row_is_stamped(session):
    await _reset(session)
    try:
        await store.upsert_items_bulk(EMBY_INSTANCE, [ITEM])
        first = await _updated_at()
        await store.upsert_items_bulk(EMBY_INSTANCE, [{**ITEM, "Name": "Pilot (HD)"}])
        (row,) = await store.get_items(EMBY_INSTANCE)
        assert row["name"] == "Pilot (HD)"
        assert row["updated_at"] > first
    finally:
        await _drop(session)
