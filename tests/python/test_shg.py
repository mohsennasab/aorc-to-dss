"""SHG alignment and raster reprojection tests."""

import numpy as np
import pytest
from pyproj import Transformer
from rasterio.warp import Resampling
from shapely.geometry import box
from threading import Event
import xarray as xr

from aorctodss_service.exceptions import CancelledError, GeometryError
from aorctodss_service.models import GridDefinition
from aorctodss_service.spatial.reprojection import (
    clip_source_all_touched,
    projected_grid,
    reproject_hour,
    reproject_series,
    shg_area_weights,
)
from aorctodss_service.spatial.shg import SHG_CRS, align_bounds, build_shg_grid


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


def test_all_touched_clip_keeps_cells_crossed_by_a_polygon() -> None:
    data = xr.DataArray(
        np.ones((1, 3, 3), dtype=np.float32),
        dims=("time", "latitude", "longitude"),
        coords={
            "time": np.array(["2020-01-01T00:00"], dtype="datetime64[ns]"),
            "latitude": np.array([35.0, 35.01, 35.02]),
            "longitude": np.array([-90.0, -89.99, -89.98]),
        },
    )
    crossed = box(-89.996, 35.004, -89.994, 35.006)
    clipped = clip_source_all_touched(data, crossed)
    assert clipped.sizes["latitude"] == 2
    assert clipped.sizes["longitude"] == 2
    assert int(clipped.notnull().sum()) == 4


def test_projected_grid_uses_nearest_neighbor_and_pixel_center_indices() -> None:
    data = xr.DataArray(
        np.arange(16, dtype=np.float32).reshape(1, 4, 4),
        dims=("time", "latitude", "longitude"),
        coords={
            "time": np.array(["2020-01-01T00:00"], dtype="datetime64[ns]"),
            "latitude": np.linspace(35.0, 35.03, 4),
            "longitude": np.linspace(-90.0, -89.97, 4),
        },
    )
    grid = projected_grid(data, 1000)
    output = reproject_hour(
        data.isel(time=0).values,
        data.latitude.values,
        data.longitude.values,
        grid,
    )
    valid = output[np.isfinite(output)]
    assert valid.size
    assert set(np.unique(valid)).issubset(set(np.arange(16, dtype=np.float32)))
    assert grid.lower_left_cell_x == np.floor(
        (grid.min_x + grid.cell_size / 2) / grid.cell_size
    )
    assert grid.lower_left_cell_y == np.floor(
        (grid.min_y + grid.cell_size / 2) / grid.cell_size
    )


def test_shg_area_weights_follow_polygon_overlap() -> None:
    geometry = box(-90.0, 35.0, -89.98, 35.02)
    transformer = Transformer.from_crs("EPSG:4326", SHG_CRS, always_xy=True)
    center_x, center_y = transformer.transform(-89.99, 35.01)
    grid = GridDefinition(
        cell_size=1000,
        min_x=center_x - 2500,
        min_y=center_y - 2500,
        max_x=center_x + 2500,
        max_y=center_y + 2500,
        width=5,
        height=5,
        crs_wkt=SHG_CRS.to_wkt(version="WKT1_ESRI"),
    )
    weights = shg_area_weights(geometry, grid)
    assert weights.shape == (5, 5)
    assert weights.sum() == pytest.approx(1)
    assert np.count_nonzero(weights) > 1


def test_lower_left_indices_floor_fractional_pixel_centers() -> None:
    grid = GridDefinition(
        cell_size=1000,
        min_x=848828.6606936215,
        min_y=1134355.684807822,
        max_x=849828.6606936215,
        max_y=1135355.684807822,
        width=1,
        height=1,
        crs_wkt="",
    )
    assert grid.lower_left_cell_x == 849
    assert grid.lower_left_cell_y == 1134


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
