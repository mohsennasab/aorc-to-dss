"""AORC clipping and source-aligned SHG reprojection."""

from __future__ import annotations

from collections.abc import Iterator
from threading import Event
from typing import Callable

import numpy as np
import xarray as xr
from affine import Affine
from pyproj import Transformer
from rasterio.features import geometry_mask
from rasterio.transform import array_bounds, from_bounds, from_origin
from rasterio.warp import Resampling, calculate_default_transform, reproject
from shapely import (
    Geometry,
    area as geometry_area,
    box as geometry_boxes,
    contains,
    intersection,
    intersects,
    prepare,
)
from shapely.geometry import mapping
from shapely.ops import transform as transform_geometry

from ..exceptions import CancelledError
from ..models import GridDefinition
from .shg import SHG_CELL_SIZES, SHG_CRS

GridProgress = Callable[[float, str], None]


def source_transform(latitudes: np.ndarray, longitudes: np.ndarray) -> Affine:
    """Build the pixel-edge transform for a regular AORC window."""

    x_step = (
        abs(float(longitudes[1] - longitudes[0]))
        if len(longitudes) > 1
        else 1 / 120
    )
    y_step = (
        abs(float(latitudes[1] - latitudes[0]))
        if len(latitudes) > 1
        else 1 / 120
    )
    west = float(np.min(longitudes)) - x_step / 2
    east = float(np.max(longitudes)) + x_step / 2
    south = float(np.min(latitudes)) - y_step / 2
    north = float(np.max(latitudes)) + y_step / 2
    return from_bounds(west, south, east, north, len(longitudes), len(latitudes))


def destination_transform(grid: GridDefinition) -> Affine:
    """Return a north-up transform for an SHG grid."""

    return from_origin(grid.min_x, grid.max_y, grid.cell_size, grid.cell_size)


def clip_source_all_touched(
    data: xr.DataArray,
    geometry_wgs84: Geometry,
) -> xr.DataArray:
    """Mask and crop native AORC cells touched by the AOI.

    The operation retains every source cell touched by the polygon while
    preserving lazy xarray data.
    """

    latitudes = np.asarray(data.latitude.values)
    longitudes = np.asarray(data.longitude.values)
    north_up_mask = geometry_mask(
        [mapping(geometry_wgs84)],
        out_shape=(len(latitudes), len(longitudes)),
        transform=source_transform(latitudes, longitudes),
        all_touched=True,
        invert=True,
    )
    data_order_mask = (
        np.flipud(north_up_mask)
        if latitudes[0] < latitudes[-1]
        else north_up_mask
    )
    rows, columns = np.where(data_order_mask)
    if not rows.size or not columns.size:
        raise ValueError("The area of interest does not touch an AORC grid cell")
    row_slice = slice(int(rows.min()), int(rows.max()) + 1)
    column_slice = slice(int(columns.min()), int(columns.max()) + 1)
    clipped = data.isel(latitude=row_slice, longitude=column_slice)
    clipped_mask = xr.DataArray(
        data_order_mask[row_slice, column_slice],
        dims=("latitude", "longitude"),
        coords={
            "latitude": clipped.latitude,
            "longitude": clipped.longitude,
        },
    )
    return clipped.where(clipped_mask)


def projected_grid(data: xr.DataArray, cell_size: int) -> GridDefinition:
    """Build a source-aligned projected raster at the requested resolution."""

    if cell_size not in SHG_CELL_SIZES:
        values = ", ".join(str(value) for value in SHG_CELL_SIZES)
        raise ValueError(f"SHG cell size must be one of {values} m")
    latitudes = np.asarray(data.latitude.values)
    longitudes = np.asarray(data.longitude.values)
    source = source_transform(latitudes, longitudes)
    left, bottom, right, top = array_bounds(
        len(latitudes),
        len(longitudes),
        source,
    )
    projected, width, height = calculate_default_transform(
        "EPSG:4326",
        SHG_CRS,
        len(longitudes),
        len(latitudes),
        left,
        bottom,
        right,
        top,
        resolution=cell_size,
    )
    min_x = float(projected.c)
    max_y = float(projected.f)
    max_x = min_x + int(width) * cell_size
    min_y = max_y - int(height) * cell_size
    return GridDefinition(
        cell_size=cell_size,
        min_x=min_x,
        min_y=min_y,
        max_x=max_x,
        max_y=max_y,
        width=int(width),
        height=int(height),
        crs_wkt=SHG_CRS.to_wkt(version="WKT1_ESRI"),
    )


def shg_area_weights(
    geometry_wgs84: Geometry,
    grid: GridDefinition,
) -> np.ndarray:
    """Return normalized AOI-overlap weights for an SHG grid.

    Both the source time series and projected-grid validation use exact polygon
    overlap areas. Because SHG uses an equal-area projection, the weights
    provide a like-for-like AOI mean after reprojection.
    """

    transformer = Transformer.from_crs("EPSG:4326", SHG_CRS, always_xy=True)
    projected_aoi = transform_geometry(transformer.transform, geometry_wgs84)
    prepare(projected_aoi)
    weights = np.zeros((grid.height, grid.width), dtype=np.float64)
    west = grid.min_x + np.arange(grid.width, dtype=np.float64) * grid.cell_size
    east = west + grid.cell_size
    for first_row in range(0, grid.height, 32):
        last_row = min(first_row + 32, grid.height)
        row_indices = np.arange(first_row, last_row, dtype=np.float64)
        north = grid.max_y - row_indices * grid.cell_size
        south = north - grid.cell_size
        cells = geometry_boxes(
            np.tile(west, last_row - first_row),
            np.repeat(south, grid.width),
            np.tile(east, last_row - first_row),
            np.repeat(north, grid.width),
        )
        overlaps = np.asarray(intersects(projected_aoi, cells), dtype=bool)
        interior = np.asarray(contains(projected_aoi, cells), dtype=bool)
        boundary = overlaps & ~interior
        areas = np.zeros(len(cells), dtype=np.float64)
        if interior.any():
            areas[interior] = grid.cell_size**2
        if boundary.any():
            areas[boundary] = np.asarray(
                geometry_area(intersection(cells[boundary], projected_aoi)),
                dtype=np.float64,
            )
        weights[first_row:last_row] = areas.reshape(
            last_row - first_row,
            grid.width,
        )
    total = float(weights.sum())
    if total <= 0:
        raise ValueError("The area of interest does not overlap the projected SHG grid")
    return weights / total


def _north_up(values: np.ndarray, latitudes: np.ndarray) -> np.ndarray:
    return np.flipud(values) if latitudes[0] < latitudes[-1] else values


def reproject_hour(
    values: np.ndarray,
    latitudes: np.ndarray,
    longitudes: np.ndarray,
    grid: GridDefinition,
    resampling: Resampling = Resampling.nearest,
    source_nodata: float = -32767,
) -> np.ndarray:
    """Reproject one AORC raster to SHG."""

    source = _north_up(np.asarray(values, dtype=np.float32), latitudes)
    source[source == source_nodata] = np.nan
    destination = np.full((grid.height, grid.width), np.nan, dtype=np.float32)
    reproject(
        source=source,
        destination=destination,
        src_transform=source_transform(latitudes, longitudes),
        src_crs="EPSG:4326",
        src_nodata=np.nan,
        dst_transform=destination_transform(grid),
        dst_crs=SHG_CRS,
        dst_nodata=np.nan,
        resampling=resampling,
        init_dest_nodata=True,
        num_threads=2,
    )
    return destination


def reproject_series(
    data: xr.DataArray,
    grid: GridDefinition,
    source_nodata: float,
    resampling: Resampling = Resampling.nearest,
    cancel: Event | None = None,
    progress: GridProgress | None = None,
) -> Iterator[tuple[np.datetime64, np.ndarray]]:
    """Yield one transformed grid at a time to limit memory use."""

    cancel = cancel or Event()
    latitudes = np.asarray(data.latitude.values)
    longitudes = np.asarray(data.longitude.values)
    count = data.sizes["time"]
    for index in range(count):
        if cancel.is_set():
            raise CancelledError("Grid conversion was cancelled")
        values = data.isel(time=index).values
        grid_values = reproject_hour(
            values,
            latitudes,
            longitudes,
            grid,
            resampling,
            source_nodata,
        )
        if progress:
            progress((index + 1) / count, f"Reprojected {index + 1} of {count} grids")
        yield data.time.values[index], grid_values
