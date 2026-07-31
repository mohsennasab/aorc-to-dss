"""UTC event window calculations."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..exceptions import AORCToDSSError
from ..models import EventWindow


def parse_utc(value: str) -> datetime:
    """Parse an ISO timestamp and require an explicit UTC offset."""

    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise AORCToDSSError("Date and time values must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def event_from_duration(start: str, duration_hours: int) -> EventWindow:
    """Build a half-open event window."""

    if duration_hours <= 0:
        raise AORCToDSSError("Event duration must be greater than zero")
    start_time = parse_utc(start)
    return EventWindow(start_time, start_time + timedelta(hours=duration_hours))


def custom_event(start: str, end: str) -> EventWindow:
    """Validate a custom half-open event window."""

    start_time = parse_utc(start)
    end_time = parse_utc(end)
    if end_time <= start_time:
        raise AORCToDSSError("Event end must be later than event start")
    if any(
        value.minute or value.second or value.microsecond
        for value in (start_time, end_time)
    ):
        raise AORCToDSSError(
            "Event start and end must use whole UTC hours with minutes set to 00"
        )
    if (end_time - start_time).total_seconds() % 3600:
        raise AORCToDSSError("Event duration must be a whole number of hours")
    return EventWindow(start_time, end_time)
