"""HEC-DSS gridded pathname creation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ..exceptions import AORCToDSSError

INVALID = re.compile(r"[^A-Z0-9 _.\-:]")
SPACE = re.compile(r"\s+")


def clean_part(value: str, fallback: str) -> str:
    """Normalize a DSS pathname part."""

    cleaned = INVALID.sub("_", value.upper().strip().replace("/", "_"))
    cleaned = SPACE.sub(" ", cleaned).strip(" ._-")
    return cleaned or fallback


def shg_a_part(cell_size: int) -> str:
    """Return the HEC grid-system label for an SHG resolution."""

    if cell_size == 2000:
        return "SHG"
    if cell_size % 1000 == 0:
        return f"SHG{cell_size // 1000}K"
    return f"SHG{cell_size}M"


def dss_datetime(value: datetime, *, interval_end: bool = False) -> str:
    """Format a UTC time using HEC's gridded-record time convention.

    HEC-DSS uses ``2400`` on the preceding date when an interval ends exactly
    at midnight.  A record that starts at midnight continues to use ``0000``.
    """

    utc_value = value.astimezone(timezone.utc)
    if (
        interval_end
        and utc_value.hour == 0
        and utc_value.minute == 0
        and utc_value.second == 0
        and utc_value.microsecond == 0
    ):
        previous_date = utc_value.date() - timedelta(days=1)
        return f"{previous_date.strftime('%d%b%Y').upper()}:2400"
    return utc_value.strftime("%d%b%Y:%H%M").upper()


@dataclass(frozen=True)
class DSSPathname:
    """Six parts of a gridded DSS pathname."""

    a: str
    b: str
    c: str
    d: str
    e: str
    f: str

    def __str__(self) -> str:
        return f"/{self.a}/{self.b}/{self.c}/{self.d}/{self.e}/{self.f}/"

    @classmethod
    def grid(
        cls,
        watershed: str,
        parameter: str,
        start: datetime,
        end: datetime,
        cell_size: int,
        dataset: str = "AORC-V1.1",
        interval: bool = True,
    ) -> "DSSPathname":
        """Create a gridded record pathname using HEC grid conventions."""

        return cls(
            a=shg_a_part(cell_size),
            b=clean_part(watershed, "WATERSHED"),
            c=clean_part(parameter, "MET"),
            d=dss_datetime(start),
            e=dss_datetime(end, interval_end=True) if interval else "",
            f=clean_part(dataset, "AORC"),
        )

    @classmethod
    def parse(cls, value: str) -> "DSSPathname":
        """Parse and validate a complete pathname."""

        if not value.startswith("/") or not value.endswith("/"):
            raise AORCToDSSError("DSS pathname must begin and end with a slash")
        parts = value.split("/")[1:-1]
        if len(parts) != 6:
            raise AORCToDSSError("DSS pathname must contain exactly six parts")
        if any("/" in part for part in parts):
            raise AORCToDSSError("DSS pathname parts cannot contain a slash")
        return cls(*parts)
