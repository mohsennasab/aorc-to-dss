"""Standard Hydrologic Grid definitions and alignment."""

from __future__ import annotations

import math
from typing import Iterable

from pyproj import CRS, Transformer
from shapely import Geometry
from shapely.ops import transform

from ..exceptions import GeometryError
from ..models import GridDefinition

SHG_CELL_SIZES = (10, 20, 50, 100, 200, 500, 1000, 2000, 4000, 5000, 10000)
SHG_CRS = CRS.from_proj4(
    "+proj=aea +lat_1=29.5 +lat_2=45.5 +lat_0=23 +lon_0=-96 "
    "+x_0=0 +y_0=0 +datum=NAD83 +units=m +no_defs"
)
SHG_WKT = SHG_CRS.to_wkt(version="WKT1_ESRI")


def buffered_geometry_wgs84(geometry_wgs84: Geometry, buffer_m: float) -> Geometry:
    """Buffer an AOI in SHG meters and return the result in WGS84."""

    if buffer_m <= 0:
        return geometry_wgs84
    forward = Transformer.from_crs("EPSG:4326", SHG_CRS, always_xy=True)
    reverse = Transformer.from_crs(SHG_CRS, "EPSG:4326", always_xy=True)
    projected = transform(forward.transform, geometry_wgs84)
    return transform(reverse.transform, projected.buffer(buffer_m))


def align_bounds(bounds: Iterable[float], cell_size: int) -> tuple[float, float, float, float]:
    """Expand bounds to exact SHG cell edges."""

    min_x, min_y, max_x, max_y = bounds
    return (
        math.floor(min_x / cell_size) * cell_size,
        math.floor(min_y / cell_size) * cell_size,
        math.ceil(max_x / cell_size) * cell_size,
        math.ceil(max_y / cell_size) * cell_size,
    )


def build_shg_grid(
    geometry_wgs84: Geometry,
    cell_size: int = 2000,
    buffer_m: float = 0,
    extent: tuple[float, float, float, float] | None = None,
) -> GridDefinition:
    """Project an AOI and build an origin-aligned SHG grid."""

    if cell_size not in SHG_CELL_SIZES:
        values = ", ".join(str(value) for value in SHG_CELL_SIZES)
        raise GeometryError(f"SHG cell size must be one of {values} m")
    if extent is None:
        transformer = Transformer.from_crs("EPSG:4326", SHG_CRS, always_xy=True)
        projected = transform(transformer.transform, geometry_wgs84)
        bounds = projected.buffer(buffer_m).bounds
    else:
        bounds = extent
    min_x, min_y, max_x, max_y = align_bounds(bounds, cell_size)
    width = round((max_x - min_x) / cell_size)
    height = round((max_y - min_y) / cell_size)
    if width <= 0 or height <= 0:
        raise GeometryError("The selected SHG extent has no grid cells")
    return GridDefinition(
        cell_size=cell_size,
        min_x=min_x,
        min_y=min_y,
        max_x=max_x,
        max_y=max_y,
        width=width,
        height=height,
        crs_wkt=SHG_WKT,
    )


def grid_estimates(grid: GridDefinition, hours: int) -> dict[str, float | int]:
    """Estimate uncompressed and DSS storage sizes."""

    cells = grid.width * grid.height
    raw_bytes = cells * 4 * hours
    return {
        "width": grid.width,
        "height": grid.height,
        "cells": cells,
        "hours": hours,
        "raw_megabytes": round(raw_bytes / 1_048_576, 2),
        "estimated_dss_megabytes": round(raw_bytes * 0.45 / 1_048_576, 2),
    }
