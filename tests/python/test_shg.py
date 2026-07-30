"""SHG alignment and raster reprojection tests."""

import numpy as np
import pytest
from rasterio.warp import Resampling
from shapely.geometry import box
from threading import Event
import xarray as xr

from aorctodss_service.exceptions import CancelledError, GeometryError
from aorctodss_service.spatial.reprojection import reproject_hour, reproject_series
from aorctodss_service.spatial.shg import align_bounds, build_shg_grid


def test_align_bounds_handles_negative_coordinates() -> None:
    assert align_bounds((-2195054, 2027427, -2191001, 2030001), 2000) == (
        -2196000,
        2026000,
        -2190000,
        2032000,
    )


def test_grid_edges_are_origin_aligned() -> None:
    grid = build_shg_grid(box(-90, 35, -89.9, 35.1), 2000, 4000)
    assert grid.min_x % 2000 == 0
    assert grid.min_y % 2000 == 0
    assert grid.max_x % 2000 == 0
    assert grid.max_y % 2000 == 0
    assert grid.width > 0
    assert grid.height > 0


def test_4000_m_grid_is_supported() -> None:
    grid = build_shg_grid(box(-90, 35, -89.9, 35.1), 4000)
    assert grid.cell_size == 4000
    assert grid.width > 0
    assert grid.height > 0


def test_unsupported_cell_size_is_rejected() -> None:
    with pytest.raises(GeometryError, match="cell size"):
        build_shg_grid(box(-90, 35, -89.9, 35.1), 750)


def test_constant_depth_survives_average_reprojection() -> None:
    grid = build_shg_grid(box(-90, 35, -89.98, 35.02), 2000)
    latitudes = np.linspace(34.98, 35.04, 8)
    longitudes = np.linspace(-90.02, -89.96, 8)
    source = np.full((8, 8), 12.5, dtype=np.float32)
    result = reproject_hour(
        source,
        latitudes,
        longitudes,
        grid,
        Resampling.average,
    )
    valid = result[np.isfinite(result)]
    assert valid.size
    assert np.allclose(valid, 12.5, atol=0.01)


def test_reprojection_cancellation() -> None:
    grid = build_shg_grid(box(-90, 35, -89.98, 35.02), 2000)
    data = xr.DataArray(
        np.ones((1, 4, 4), dtype=np.float32),
        dims=("time", "latitude", "longitude"),
        coords={
            "time": np.array(["2020-01-01T00:00"], dtype="datetime64[ns]"),
            "latitude": np.linspace(34.98, 35.04, 4),
            "longitude": np.linspace(-90.02, -89.96, 4),
        },
    )
    cancel = Event()
    cancel.set()
    with pytest.raises(CancelledError):
        list(reproject_series(data, grid, -32767, cancel=cancel))
