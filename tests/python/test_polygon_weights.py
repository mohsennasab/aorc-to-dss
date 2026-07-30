"""Polygon weight tests."""

from pathlib import Path

import numpy as np
from shapely.geometry import box

from aorctodss_service.spatial.polygon_weights import polygon_weights


def test_cell_center_weights_are_normalized() -> None:
    latitudes = np.array([0.5, 1.5])
    longitudes = np.array([0.5, 1.5])
    weights = polygon_weights(
        box(0, 0, 1.1, 2),
        latitudes,
        longitudes,
        "cell-center",
    )
    assert weights.valid_cell_count == 2
    assert np.isclose(weights.weights.sum(), 1)
    assert np.allclose(weights.weights[:, 0], [0.5, 0.5])


def test_area_weights_reflect_partial_cells() -> None:
    latitudes = np.array([0.5, 1.5])
    longitudes = np.array([0.5, 1.5])
    weights = polygon_weights(
        box(0, 0, 1.5, 2),
        latitudes,
        longitudes,
        "area-weighted",
    )
    assert np.isclose(weights.weights.sum(), 1)
    assert weights.weights[:, 0].sum() > weights.weights[:, 1].sum()


def test_area_weight_progress_is_monotonic() -> None:
    latitudes = np.arange(0.5, 65.5)
    longitudes = np.array([0.5, 1.5])
    updates: list[tuple[float, str]] = []
    weights = polygon_weights(
        box(0, 0, 1.5, 65),
        latitudes,
        longitudes,
        "area-weighted",
        progress=lambda value, message: updates.append((value, message)),
    )
    values = [value for value, _message in updates]
    assert np.isclose(weights.weights.sum(), 1)
    assert values == sorted(values)
    assert values[0] == 0
    assert values[-1] == 1
    assert any("row blocks" in message for _value, message in updates)


def test_weights_are_reused_from_cache(tmp_path: Path) -> None:
    latitudes = np.array([0.5, 1.5])
    longitudes = np.array([0.5, 1.5])
    first = polygon_weights(
        box(0, 0, 2, 2),
        latitudes,
        longitudes,
        "area-weighted",
        tmp_path,
    )
    files = list(tmp_path.glob("*.npz"))
    assert len(files) == 1
    modified = files[0].stat().st_mtime_ns
    second = polygon_weights(
        box(0, 0, 2, 2),
        latitudes,
        longitudes,
        "area-weighted",
        tmp_path,
    )
    assert files[0].stat().st_mtime_ns == modified
    assert np.array_equal(first.weights, second.weights)
