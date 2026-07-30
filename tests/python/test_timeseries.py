"""Spatial average and missing-data tests."""

from threading import Event

import numpy as np
import xarray as xr
from shapely.geometry import box

from aorctodss_service.aorc.timeseries import average_dataarray
from aorctodss_service.exceptions import CancelledError


def sample_data() -> xr.DataArray:
    return xr.DataArray(
        np.array([
            [[1.0, 3.0], [5.0, 7.0]],
            [[1.0, -32767.0], [5.0, 7.0]],
        ]),
        dims=("time", "latitude", "longitude"),
        coords={
            "time": np.array(["2020-01-01T00", "2020-01-01T01"], dtype="datetime64[h]"),
            "latitude": [0.5, 1.5],
            "longitude": [0.5, 1.5],
        },
    )


def test_average_renormalizes_missing_cells() -> None:
    points = average_dataarray(
        sample_data(),
        box(0, 0, 2, 2),
        -32767,
        "mm",
        "cell-center",
    )
    assert points[0].value == 4
    assert np.isclose(points[1].value, 13 / 3)
    assert points[1].quality == "partial"


def test_cancel_is_honored() -> None:
    cancel = Event()
    cancel.set()
    with np.testing.assert_raises(CancelledError):
        average_dataarray(
            sample_data(),
            box(0, 0, 2, 2),
            -32767,
            "mm",
            cancel=cancel,
        )
