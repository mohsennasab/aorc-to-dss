"""DSS validation comparisons use the same north-up AOI footprint."""

from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from aorctodss_service.dss.adapter import HecDssAdapter
from aorctodss_service.dss.validator import validate_dss
from aorctodss_service.models import GridDefinition
from aorctodss_service.spatial.shg import SHG_CRS


def test_value_preservation_accounts_for_dss_row_orientation(tmp_path: Path) -> None:
    grid = GridDefinition(
        cell_size=2000,
        min_x=0,
        min_y=0,
        max_x=4000,
        max_y=4000,
        width=2,
        height=2,
        crs_wkt=SHG_CRS.to_wkt(version="WKT1_ESRI"),
    )
    values = np.array([[1.0, 2.0], [10.0, 20.0]], dtype=np.float32)
    weights = np.array([[0.7, 0.1], [0.1, 0.1]], dtype=np.float64)
    expected_mean = float(np.sum(values * weights))
    pathname = "/SHG/TEST/PRECIP/01JAN2020:0000/01JAN2020:0100/TEST/"
    dss_path = tmp_path / "orientation.dss"
    with HecDssAdapter(dss_path) as adapter:
        adapter.write_grid_record(pathname, values, grid, "MM", 1)

    checks = validate_dss(
        dss_path,
        [pathname],
        grid,
        "MM",
        datetime(2020, 1, 1, tzinfo=timezone.utc),
        datetime(2020, 1, 1, 1, tzinfo=timezone.utc),
        [expected_mean],
        [expected_mean],
        weights,
    )
    value_check = next(check for check in checks if check.name == "Value preservation")
    assert value_check.status == "pass"
    assert value_check.details["maximum_dss_readback_percent_difference"] < 0.001
