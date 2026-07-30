"""Area of interest validation and reporting."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pyproj import CRS, Geod, Transformer
from shapely import Geometry, from_geojson, make_valid, to_geojson
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
from shapely.ops import transform, unary_union

from ..exceptions import GeometryError

CONUS_BOUNDS = (-125.0, 25.0, -67.0, 53.0)


@dataclass(frozen=True)
class GeometrySummary:
    """Validated AOI geometry and user-facing facts."""

    geometry: Geometry
    source_crs: str
    feature_count: int
    repaired: bool
    dissolved: bool
    area_sq_km: float

    def geojson(self) -> dict[str, Any]:
        """Return the geometry as a GeoJSON object."""

        return json.loads(to_geojson(self.geometry))

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready summary."""

        return {
            "geometry": self.geojson(),
            "source_crs": self.source_crs,
            "analysis_crs": "EPSG:4326",
            "feature_count": self.feature_count,
            "repaired": self.repaired,
            "dissolved": self.dissolved,
            "area_sq_km": self.area_sq_km,
            "bounds": list(self.geometry.bounds),
        }


def _polygonal_parts(geometry: Geometry) -> list[Polygon]:
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return list(geometry.geoms)
    if isinstance(geometry, GeometryCollection):
        return [part for part in geometry.geoms if isinstance(part, Polygon)]
    return []


def _read_features(payload: dict[str, Any]) -> list[Geometry]:
    kind = payload.get("type")
    if kind == "FeatureCollection":
        values = [feature.get("geometry") for feature in payload.get("features", [])]
    elif kind == "Feature":
        values = [payload.get("geometry")]
    else:
        values = [payload]
    output: list[Geometry] = []
    for value in values:
        if value:
            output.append(from_geojson(json.dumps(value)))
    return output


def geodesic_area_sq_km(geometry: Geometry) -> float:
    """Calculate polygon area on the WGS84 ellipsoid."""

    geod = Geod(ellps="WGS84")
    area, _ = geod.geometry_area_perimeter(geometry)
    return abs(area) / 1_000_000


def prepare_geometry(
    payload: dict[str, Any],
    source_crs: str = "EPSG:4326",
    dissolve: bool = True,
) -> GeometrySummary:
    """Validate, repair, dissolve, and report a polygon AOI."""

    try:
        crs = CRS.from_user_input(source_crs)
    except Exception as exc:
        raise GeometryError(
            f"Coordinate reference system {source_crs} is not supported",
            "Choose a recognized EPSG code or WKT definition.",
        ) from exc
    inputs = _read_features(payload)
    if not inputs:
        raise GeometryError("No polygon features were found in the area of interest")
    repaired = False
    polygons: list[Polygon] = []
    transformer = (
        Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
        if crs.to_epsg() != 4326
        else None
    )
    for geometry in inputs:
        if not geometry.is_valid:
            geometry = make_valid(geometry)
            repaired = True
        if transformer is not None:
            try:
                geometry = transform(transformer.transform, geometry)
            except Exception as exc:
                raise GeometryError(
                    f"Geometry could not be transformed from {crs.to_string()} to WGS84",
                    "Confirm that the GeoJSON CRS declaration matches its coordinates.",
                ) from exc
        if not geometry.is_valid:
            geometry = make_valid(geometry)
            repaired = True
        polygons.extend(_polygonal_parts(geometry))
    if not polygons:
        raise GeometryError("The area of interest does not contain polygon geometry")
    combined: Geometry
    if dissolve:
        combined = unary_union(polygons)
    elif len(polygons) == 1:
        combined = polygons[0]
    else:
        combined = MultiPolygon(polygons)
    if combined.is_empty or not combined.is_valid:
        raise GeometryError(
            "The area of interest could not be repaired",
            "Run a geometry repair tool and remove self intersections before retrying.",
        )
    min_x, min_y, max_x, max_y = combined.bounds
    c_min_x, c_min_y, c_max_x, c_max_y = CONUS_BOUNDS
    if max_x < c_min_x or min_x > c_max_x or max_y < c_min_y or min_y > c_max_y:
        raise GeometryError(
            "The area of interest is outside the CONUS AORC grid",
            "Use the Alaska archive for Alaska projects. SHG is defined only for CONUS.",
        )
    return GeometrySummary(
        geometry=combined,
        source_crs=crs.to_string(),
        feature_count=len(inputs),
        repaired=repaired,
        dissolved=dissolve and len(inputs) > 1,
        area_sq_km=geodesic_area_sq_km(combined),
    )
