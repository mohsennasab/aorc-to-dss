"""Event and UTC handling tests."""

from datetime import timezone

import pytest

from aorctodss_service.events.selection import (
    custom_event,
    event_from_duration,
    parse_utc,
)


def test_parse_utc_converts_offset() -> None:
    value = parse_utc("2020-01-01T01:00:00+01:00")
    assert value.hour == 0
    assert value.tzinfo == timezone.utc


def test_naive_time_is_rejected() -> None:
    with pytest.raises(Exception, match="UTC offset"):
        parse_utc("2020-01-01T00:00:00")


def test_custom_event_requires_whole_hours() -> None:
    with pytest.raises(Exception, match="minutes set to 00"):
        custom_event("2020-01-01T00:00:00Z", "2020-01-01T01:30:00Z")


def test_custom_event_rejects_matching_half_hour_boundaries() -> None:
    with pytest.raises(Exception, match="minutes set to 00"):
        custom_event("2020-01-01T00:30:00Z", "2020-01-01T01:30:00Z")


def test_event_duration_sets_end_time() -> None:
    event = event_from_duration("2020-01-01T00:00:00Z", 48)
    assert event.end.isoformat() == "2020-01-03T00:00:00+00:00"
