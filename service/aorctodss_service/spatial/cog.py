"""Cloud-Optimized GeoTIFF event summaries."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import geometry_mask
from shapely import Geometry
from shapely.geometry import mapping

from ..models import GridDefinition
from .reprojection import destination_transform, source_transform
from .shg import SHG_CRS


def write_cog(
    path: Path,
    values: np.ndarray,
    grid: GridDefinition,
    units: str,
    statistic: str,
    transparent_zero: bool = False,
    colormap: str | None = None,
) -> Path:
    """Write a tiled GeoTIFF and build overview levels."""

    path.parent.mkdir(parents=True, exist_ok=True)
    array = np.asarray(values, dtype=np.float32)
    if transparent_zero:
        array = np.where(array > 0, array, np.nan)
    profile = {
        "driver": "COG",
        "height": grid.height,
        "width": grid.width,
        "count": 1,
        "dtype": "float32",
        "crs": SHG_CRS,
        "transform": destination_transform(grid),
        "nodata": -9999.0,
        "compress": "DEFLATE",
        "predictor": 3,
        "blocksize": 512,
        "overview_resampling": "nearest",
    }
    stored = np.where(np.isfinite(array), array, -9999).astype(np.float32)
    with rasterio.open(path, "w", **profile) as dataset:
        dataset.write(stored, 1)
        dataset.update_tags(
            1,
            units=units,
            statistic=statistic,
            aorctodss_mask="AORC source clip, all_touched=True",
            aorctodss_resampling="nearest",
            aorctodss_colormap=colormap or "",
            aorctodss_transparent_zero=str(transparent_zero).lower(),
        )
    return path


def write_wgs84_animation_cog(
    path: Path,
    values: np.ndarray,
    latitudes: np.ndarray,
    longitudes: np.ndarray,
    geometry_wgs84: Geometry,
    units: str,
    transparent_zero: bool = False,
) -> Path:
    """Write one AOI-clipped native AORC frame for browser animation."""

    path.parent.mkdir(parents=True, exist_ok=True)
    latitude_values = np.asarray(latitudes)
    array = np.asarray(values, dtype=np.float32)
    if latitude_values[0] < latitude_values[-1]:
        array = np.flipud(array)
    transform = source_transform(latitude_values, np.asarray(longitudes))
    inside = geometry_mask(
        [mapping(geometry_wgs84)],
        out_shape=array.shape,
        transform=transform,
        all_touched=True,
        invert=True,
    )
    valid = inside & np.isfinite(array)
    if transparent_zero:
        valid &= array > 0
    stored = np.where(valid, array, -9999).astype(np.float32)
    profile = {
        "driver": "COG",
        "height": stored.shape[0],
        "width": stored.shape[1],
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:4326",
        "transform": transform,
        "nodata": -9999.0,
        "compress": "DEFLATE",
        "predictor": 3,
        "blocksize": 512,
        "overview_resampling": "nearest",
    }
    with rasterio.open(path, "w", **profile) as dataset:
        dataset.write(stored, 1)
        dataset.update_tags(
            1,
            units=units,
            statistic="AORC hourly frame",
            aorctodss_mask="AORC source clip, all_touched=True",
        )
    return path
