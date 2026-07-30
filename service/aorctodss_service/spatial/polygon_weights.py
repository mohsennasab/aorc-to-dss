"""Reusable polygon weights for an AORC latitude and longitude window."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Callable, Literal

import numpy as np
from pyproj import CRS, Transformer
from shapely import (
    Geometry,
    area as geometry_area,
    box as geometry_boxes,
    contains,
    intersection,
    intersects,
    intersects_xy,
    prepare,
    to_geojson,
    transform as transform_geometries,
)
from shapely.ops import transform as transform_geometry

from ..exceptions import CancelledError, GeometryError

ProgressCallback = Callable[[float, str], None]


@dataclass(frozen=True)
class PolygonWeights:
    """Weights aligned to a latitude by longitude grid window."""

    weights: np.ndarray
    method: Literal["cell-center", "area-weighted"]
    valid_cell_count: int


def _cache_key(
    geometry: Geometry,
    latitudes: np.ndarray,
    longitudes: np.ndarray,
    method: str,
) -> str:
    digest = hashlib.sha256()
    digest.update(to_geojson(geometry).encode("utf-8"))
    digest.update(np.asarray(latitudes, dtype="<f8").tobytes())
    digest.update(np.asarray(longitudes, dtype="<f8").tobytes())
    digest.update(method.encode("ascii"))
    return digest.hexdigest()


def _edges(coordinates: np.ndarray) -> np.ndarray:
    values = np.asarray(coordinates, dtype=float)
    if len(values) < 2:
        raise GeometryError("At least two grid coordinates are required")
    midpoints = (values[:-1] + values[1:]) / 2
    first = values[0] - (values[1] - values[0]) / 2
    last = values[-1] + (values[-1] - values[-2]) / 2
    return np.concatenate(([first], midpoints, [last]))


def _cell_center_weights(
    geometry: Geometry,
    latitudes: np.ndarray,
    longitudes: np.ndarray,
) -> np.ndarray:
    longitude_grid, latitude_grid = np.meshgrid(longitudes, latitudes)
    return np.asarray(
        intersects_xy(geometry, longitude_grid, latitude_grid),
        dtype=np.float64,
    )


def _area_weights(
    geometry: Geometry,
    latitudes: np.ndarray,
    longitudes: np.ndarray,
    cancel: Event,
    progress: ProgressCallback | None,
) -> np.ndarray:
    local_crs = CRS.from_proj4(
        f"+proj=laea +lat_0={geometry.centroid.y} +lon_0={geometry.centroid.x} "
        "+datum=WGS84 +units=m +no_defs"
    )
    transformer = Transformer.from_crs("EPSG:4326", local_crs, always_xy=True)
    projected_aoi = transform_geometry(transformer.transform, geometry)
    prepare(projected_aoi)
    lat_edges = _edges(latitudes)
    lon_edges = _edges(longitudes)
    output = np.zeros((len(latitudes), len(longitudes)), dtype=np.float64)
    columns = len(longitudes)
    west = np.minimum(lon_edges[:-1], lon_edges[1:])
    east = np.maximum(lon_edges[:-1], lon_edges[1:])
    row_starts = list(range(0, len(latitudes), 32))
    for block_index, first_row in enumerate(row_starts):
        if cancel.is_set():
            raise CancelledError("Time-series calculation was cancelled")
        last_row = min(first_row + 32, len(latitudes))
        south = np.minimum(
            lat_edges[first_row:last_row],
            lat_edges[first_row + 1:last_row + 1],
        )
        north = np.maximum(
            lat_edges[first_row:last_row],
            lat_edges[first_row + 1:last_row + 1],
        )
        cells = geometry_boxes(
            np.tile(west, last_row - first_row),
            np.repeat(south, columns),
            np.tile(east, last_row - first_row),
            np.repeat(north, columns),
        )
        projected_cells = transform_geometries(
            cells,
            transformer.transform,
            interleaved=False,
        )
        overlaps = np.asarray(intersects(projected_aoi, projected_cells), dtype=bool)
        interior = np.asarray(contains(projected_aoi, projected_cells), dtype=bool)
        boundary = overlaps & ~interior
        areas = np.zeros(len(projected_cells), dtype=np.float64)
        if interior.any():
            areas[interior] = np.asarray(
                geometry_area(projected_cells[interior]),
                dtype=np.float64,
            )
        if boundary.any():
            areas[boundary] = np.asarray(
                geometry_area(
                    intersection(projected_cells[boundary], projected_aoi)
                ),
                dtype=np.float64,
            )
        output[first_row:last_row] = areas.reshape(last_row - first_row, columns)
        if progress:
            progress(
                (block_index + 1) / len(row_starts),
                (
                    "Calculating area weights "
                    f"({block_index + 1} of {len(row_starts)} row blocks)"
                ),
            )
    return output


def polygon_weights(
    geometry: Geometry,
    latitudes: np.ndarray,
    longitudes: np.ndarray,
    method: Literal["cell-center", "area-weighted"],
    cache_dir: Path | None = None,
    cancel: Event | None = None,
    progress: ProgressCallback | None = None,
) -> PolygonWeights:
    """Create or read cached normalized weights."""

    cancel = cancel or Event()
    key = _cache_key(geometry, latitudes, longitudes, method)
    cache_path = cache_dir / f"{key}.npz" if cache_dir else None
    if cache_path and cache_path.exists():
        with np.load(cache_path) as stored:
            weights = stored["weights"]
        if progress:
            progress(1, "Reusing cached watershed weights")
        return PolygonWeights(weights, method, int(np.count_nonzero(weights)))
    if cancel.is_set():
        raise CancelledError("Time-series calculation was cancelled")
    if method == "cell-center":
        if progress:
            progress(0, "Selecting AORC cell centers inside the study area")
        raw = _cell_center_weights(geometry, latitudes, longitudes)
        if progress:
            progress(1, "Watershed cell-center weights are ready")
    elif method == "area-weighted":
        if progress:
            progress(0, "Preparing area-weighted AORC cells")
        raw = _area_weights(
            geometry,
            latitudes,
            longitudes,
            cancel,
            progress,
        )
    else:
        raise GeometryError(f"Unknown averaging method {method}")
    total = float(raw.sum())
    if total <= 0:
        raise GeometryError(
            "The area of interest does not include any AORC grid cells",
            "Use area-weighted averaging for very small polygons or enlarge the area.",
        )
    weights = raw / total
    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(cache_path, weights=weights, metadata=json.dumps({"method": method}))
    return PolygonWeights(weights, method, int(np.count_nonzero(raw)))
