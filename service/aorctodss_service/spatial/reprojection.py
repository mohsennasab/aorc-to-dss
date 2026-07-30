"""AORC raster conversion to a true, origin-aligned SHG grid."""

from __future__ import annotations

from collections.abc import Iterator
from threading import Event
from typing import Callable

import numpy as np
import xarray as xr
from affine import Affine
from pyproj import Transformer
from rasterio.features import geometry_mask
from rasterio.transform import from_bounds, from_origin
from rasterio.warp import Resampling, reproject
from shapely import Geometry
from shapely.geometry import mapping
from shapely.ops import transform

from ..exceptions import CancelledError
from ..models import GridDefinition
from .shg import SHG_CRS

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


def aoi_grid_mask(geometry_wgs84: Geometry, grid: GridDefinition) -> np.ndarray:
    """Return cells whose centers fall inside the unbuffered AOI polygon."""

    transformer = Transformer.from_crs("EPSG:4326", SHG_CRS, always_xy=True)
    projected = transform(transformer.transform, geometry_wgs84)
    return geometry_mask(
        [mapping(projected)],
        out_shape=(grid.height, grid.width),
        transform=destination_transform(grid),
        all_touched=False,
        invert=True,
    )


def _north_up(values: np.ndarray, latitudes: np.ndarray) -> np.ndarray:
    return np.flipud(values) if latitudes[0] < latitudes[-1] else values


def reproject_hour(
    values: np.ndarray,
    latitudes: np.ndarray,
    longitudes: np.ndarray,
    grid: GridDefinition,
    resampling: Resampling = Resampling.average,
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
    resampling: Resampling = Resampling.average,
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
