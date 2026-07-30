"""DSS pathname tests."""

from datetime import datetime, timezone

import pytest

from aorctodss_service.dss.pathname import DSSPathname, clean_part, shg_a_part


def test_clean_part_removes_invalid_characters() -> None:
    assert clean_part("Upper/Tennessee!*", "BASIN") == "UPPER_TENNESSEE"


@pytest.mark.parametrize(
    ("cell_size", "expected"),
    [(2000, "SHG"), (1000, "SHG1K"), (500, "SHG500M"), (10000, "SHG10K")],
)
def test_shg_a_part(cell_size: int, expected: str) -> None:
    assert shg_a_part(cell_size) == expected


def test_grid_path_uses_interval_times() -> None:
    start = datetime(2020, 5, 1, 1, tzinfo=timezone.utc)
    end = datetime(2020, 5, 1, 2, tzinfo=timezone.utc)
    path = DSSPathname.grid("Upper Tennessee", "PRECIP", start, end, 2000)
    assert str(path) == "/SHG/UPPER TENNESSEE/PRECIP/01MAY2020:0100/01MAY2020:0200/AORC-V1.1/"
    assert DSSPathname.parse(str(path)) == path


def test_grid_path_uses_2400_for_an_interval_ending_at_midnight() -> None:
    start = datetime(2025, 10, 26, 23, tzinfo=timezone.utc)
    end = datetime(2025, 10, 27, 0, tzinfo=timezone.utc)
    path = DSSPathname.grid("Watershed", "PRECIP", start, end, 2000)
    assert str(path) == (
        "/SHG/WATERSHED/PRECIP/26OCT2025:2300/"
        "26OCT2025:2400/AORC-V1.1/"
    )


def test_parse_rejects_malformed_path() -> None:
    with pytest.raises(Exception, match="six parts"):
        DSSPathname.parse("/A/B/C/")
