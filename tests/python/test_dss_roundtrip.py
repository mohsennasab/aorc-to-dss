"""Official HEC-DSS grid round-trip test."""

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import box

from aorctodss_service.dss.adapter import HecDssAdapter
from aorctodss_service.dss.pathname import DSSPathname
from aorctodss_service.spatial.shg import build_shg_grid


@pytest.mark.dss
def test_grid_write_and_read_back(tmp_path: Path) -> None:
    if not HecDssAdapter.dependency_status()["available"]:
        pytest.skip("Official hecdss package is unavailable")
    file_path = tmp_path / "roundtrip.dss"
    grid = build_shg_grid(box(-90, 35, -89.98, 35.02), 2000)
    pathname = str(
        DSSPathname.grid(
            "TEST",
            "PRECIP",
            datetime(2020, 1, 1, 23, tzinfo=timezone.utc),
            datetime(2020, 1, 2, 0, tzinfo=timezone.utc),
            2000,
        )
    )
    assert "/01JAN2020:2300/01JAN2020:2400/" in pathname
    values = np.arange(grid.width * grid.height, dtype=np.float32).reshape(grid.height, grid.width)
    with HecDssAdapter(file_path) as adapter:
        adapter.write_grid_record(pathname, values, grid, "MM", 1)
        assert pathname in adapter.list_pathnames()
        record = adapter.read_grid_record(pathname)
        assert record.numberOfCellsX == grid.width
        assert record.numberOfCellsY == grid.height
        assert record.lowerLeftCellX == grid.lower_left_cell_x
        assert record.lowerLeftCellY == grid.lower_left_cell_y
        assert record.dataUnits == "MM"
        assert np.allclose(np.flipud(record.data), values)
        assert adapter.validate_grid_record(pathname, grid, "MM") == []
    assert file_path.stat().st_size > 0
