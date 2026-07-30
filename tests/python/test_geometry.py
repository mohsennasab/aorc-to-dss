"""Geometry validation tests."""

import pytest
from pyproj import Transformer

from aorctodss_service.exceptions import GeometryError
from aorctodss_service.spatial.geometry import prepare_geometry


def polygon_feature(west: float, south: float, east: float, north: float) -> dict:
    return {
        "type": "Feature",
        "properties": {},
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [west, south],
                [east, south],
                [east, north],
                [west, north],
                [west, south],
            ]],
        },
    }


def test_valid_polygon_reports_area() -> None:
    summary = prepare_geometry(polygon_feature(-90, 35, -89.9, 35.1))
    assert summary.source_crs == "EPSG:4326"
    assert summary.feature_count == 1
    assert summary.area_sq_km > 90
    assert summary.geometry.is_valid


def test_multiple_features_are_dissolved() -> None:
    collection = {
        "type": "FeatureCollection",
        "features": [
            polygon_feature(-90, 35, -89.9, 35.1),
            polygon_feature(-89.9, 35, -89.8, 35.1),
        ],
    }
    summary = prepare_geometry(collection)
    assert summary.feature_count == 2
    assert summary.dissolved
    assert summary.geometry.geom_type == "Polygon"


def test_bowtie_is_repaired() -> None:
    feature = {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [-90, 35],
                [-89.8, 35.2],
                [-90, 35.2],
                [-89.8, 35],
                [-90, 35],
            ]],
        },
        "properties": {},
    }
    summary = prepare_geometry(feature)
    assert summary.repaired
    assert summary.geometry.is_valid


def test_polygon_outside_conus_is_rejected() -> None:
    with pytest.raises(GeometryError, match="outside"):
        prepare_geometry(polygon_feature(1, 50, 2, 51))


def test_projected_geojson_is_reprojected_to_wgs84() -> None:
    project = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)
    west, south = project.transform(-90, 35)
    east, north = project.transform(-89.9, 35.1)
    summary = prepare_geometry(
        polygon_feature(west, south, east, north),
        "EPSG:5070",
    )
    assert summary.source_crs == "EPSG:5070"
    assert summary.to_dict()["analysis_crs"] == "EPSG:4326"
    assert summary.geometry.bounds == pytest.approx((-90, 35, -89.9, 35.1), abs=0.02)
