"""Pure helpers behind the session and snapshot rebuilds."""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from brein import config as brein_config
from brein.store import emby_playback_sessions as sessions
from brein.store import metrics_helpers


# ── Incremental snapshot bounds ──────────────────────────────────────────────


def _local_date(utc: datetime) -> date:
    return utc.astimezone(ZoneInfo(brein_config.TIMEZONE)).date()


def test_rebuild_since_is_the_local_date_a_day_earlier():
    changed = datetime(2031, 5, 4, 12, tzinfo=timezone.utc)
    expected = (_local_date(changed) - timedelta(days=1)).isoformat()
    assert metrics_helpers._snapshot_rebuild_since("2031-05-04T12:00:00Z") == expected
    # The 7-digit form the sync jobs store is truncated to the second.
    assert (
        metrics_helpers._snapshot_rebuild_since("2031-05-04T12:00:00.0000000Z")
        == expected
    )


def test_rebuild_since_takes_the_entry_as_utc():
    """23:30Z is already the next local day anywhere east of UTC+0:30; the
    day before that is still what the rebuild has to reach back to."""
    changed = datetime(2031, 5, 4, 23, 30, tzinfo=timezone.utc)
    expected = (_local_date(changed) - timedelta(days=1)).isoformat()
    assert metrics_helpers._snapshot_rebuild_since("2031-05-04T23:30:00Z") == expected


@pytest.mark.parametrize("raw", ["", "not a date", "2031-13-45T00:00:00Z", None])
def test_rebuild_since_is_none_for_garbage(raw):
    """None makes the caller rebuild everything rather than guess."""
    assert metrics_helpers._snapshot_rebuild_since(raw) is None


def test_since_params_prefilter_a_day_earlier():
    assert metrics_helpers._snapshot_since_params("2031-05-04") == {
        "since_date": "2031-05-04",
        "since_lo": "2031-05-03",
    }


def test_since_params_with_garbage_do_not_prefilter():
    assert metrics_helpers._snapshot_since_params("yesterday") == {
        "since_date": "yesterday",
        "since_lo": "",
    }


# ── Session rebuild ──────────────────────────────────────────────────────────


def test_parse_dt_takes_a_naive_value_as_utc():
    parsed = sessions._parse_dt("2031-05-04T12:00:00")
    assert parsed.tzinfo is not None
    assert parsed == datetime(2031, 5, 4, 12, tzinfo=timezone.utc)


def test_parse_dt_converts_an_offset_to_utc():
    parsed = sessions._parse_dt("2031-05-04T14:00:00+02:00")
    assert parsed == datetime(2031, 5, 4, 12, tzinfo=timezone.utc)
    assert parsed.utcoffset() == timedelta(0)


def test_parse_dt_accepts_the_stored_forms():
    for raw in ("2031-05-04T12:00:00Z", "2031-05-04T12:00:00.0000000Z"):
        assert sessions._parse_dt(raw) == datetime(2031, 5, 4, 12, tzinfo=timezone.utc)


def test_parse_dt_raises_on_garbage():
    with pytest.raises(ValueError):
        sessions._parse_dt("last tuesday")


def _event(event_type: str, when: str, item: int = 7) -> tuple:
    return (1, 5, item, event_type, when)


def test_a_zulu_start_next_to_a_naive_stop_still_makes_a_session():
    """Subtracting naive from aware raised TypeError, and one entry with a
    'Z' next to one without threw the whole group away."""
    rows = sessions._build_sessions_from_events(
        [
            _event("VideoPlayback", "2031-05-04T12:00:00Z"),
            _event("VideoPlaybackStopped", "2031-05-04T12:30:00"),
        ]
    )
    assert rows == [
        {
            "instance_id": 1,
            "user_id": 5,
            "item_id": 7,
            "start_time": "2031-05-04T12:00:00Z",
            "end_time": "2031-05-04T12:30:00",
            "duration_seconds": 1800,
        }
    ]


def test_a_stop_without_a_start_makes_nothing():
    assert (
        sessions._build_sessions_from_events(
            [_event("VideoPlaybackStopped", "2031-05-04T12:30:00Z")]
        )
        == []
    )


def test_an_implausibly_long_session_is_dropped():
    rows = sessions._build_sessions_from_events(
        [
            _event("VideoPlayback", "2031-05-04T12:00:00Z"),
            _event("VideoPlaybackStopped", "2031-05-05T12:00:00Z"),
        ]
    )
    assert rows == []


def test_groups_are_kept_apart():
    rows = sessions._build_sessions_from_events(
        [
            _event("VideoPlayback", "2031-05-04T12:00:00Z", item=7),
            _event("VideoPlaybackStopped", "2031-05-04T12:10:00Z", item=7),
            _event("VideoPlayback", "2031-05-04T13:00:00Z", item=8),
            _event("VideoPlaybackStopped", "2031-05-04T13:05:00Z", item=8),
        ]
    )
    assert [(r["item_id"], r["duration_seconds"]) for r in rows] == [
        (7, 600),
        (8, 300),
    ]
