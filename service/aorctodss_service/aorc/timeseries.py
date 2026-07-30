"""Watershed-average AORC time series."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from threading import Event
from typing import Literal

import numpy as np
import xarray as xr
from dask import config as dask_config
from dask.callbacks import Callback
from shapely import Geometry

from ..exceptions import ArchiveError, CancelledError
from ..models import TimeSeriesPoint
from ..spatial.polygon_weights import polygon_weights
from .catalog import AORCCatalog
from .subset import ProgressCallback, open_aorc_window


def average_dataarray(
    grid: object,
    geometry: Geometry,
    missing_value: float,
    units: str,
    method: Literal["cell-center", "area-weighted"] = "area-weighted",
    weights_cache: Path | None = None,
    cancel: Event | None = None,
    progress: ProgressCallback | None = None,
) -> list[TimeSeriesPoint]:
    """Calculate a weighted series from an already opened AORC window."""

    cancel = cancel or Event()

    def weight_progress(value: float, message: str) -> None:
        if progress:
            progress(value * 0.3, message)

    weights = polygon_weights(
        geometry,
        np.asarray(grid.latitude.values),
        np.asarray(grid.longitude.values),
        method,
        weights_cache,
        cancel,
        weight_progress,
    ).weights
    if cancel.is_set():
        raise CancelledError("Time-series calculation was cancelled")
    count = grid.sizes["time"]
    weight_grid = xr.DataArray(
        weights,
        dims=("latitude", "longitude"),
        coords={
            "latitude": grid.latitude,
            "longitude": grid.longitude,
        },
    )
    values = grid.astype(float)
    valid = np.isfinite(values) & (values != missing_value)
    numerator = xr.where(valid, values * weight_grid, 0).sum(
        dim=("latitude", "longitude")
    )
    denominator = xr.where(valid, weight_grid, 0).sum(
        dim=("latitude", "longitude")
    )
    reduced = xr.Dataset({"numerator": numerator, "denominator": denominator})

    completed_tasks = 0
    total_tasks = 1
    if progress:
        progress(0.3, f"Calculating watershed averages for {count} hours")

    def start(dsk: dict[object, object]) -> None:
        nonlocal total_tasks
        total_tasks = max(len(dsk), 1)

    def pretask(
        _key: object,
        _dsk: dict[object, object],
        _state: dict[str, object],
    ) -> None:
        if cancel.is_set():
            raise CancelledError("Time-series calculation was cancelled")

    def posttask(
        _key: object,
        _result: object,
        _dsk: dict[object, object],
        _state: dict[str, object],
        _worker_id: object,
    ) -> None:
        nonlocal completed_tasks
        completed_tasks += 1
        if progress and (completed_tasks % 20 == 0 or completed_tasks == total_tasks):
            progress(
                0.3 + (completed_tasks / total_tasks) * 0.7,
                f"Calculating watershed averages for {count} hours",
            )

    with dask_config.set(scheduler="threads", num_workers=2):
        with Callback(start=start, pretask=pretask, posttask=posttask):
            computed = reduced.compute()
    if cancel.is_set():
        raise CancelledError("Time-series calculation was cancelled")

    numerators = np.asarray(computed.numerator.values, dtype=float)
    denominators = np.asarray(computed.denominator.values, dtype=float)
    points: list[TimeSeriesPoint] = []
    for index, (numerator_value, denominator_value) in enumerate(
        zip(numerators, denominators)
    ):
        if denominator_value <= 0:
            value = None
            quality = "missing"
        else:
            value = float(numerator_value / denominator_value)
            quality = "partial" if denominator_value < 0.999999 else "ok"
        timestamp = np.datetime_as_string(grid.time.values[index], unit="s") + "Z"
        points.append(TimeSeriesPoint(timestamp, value, units, quality))
    if progress:
        progress(1, f"Calculated {count} hourly values")
    return points


def watershed_timeseries(
    catalog: AORCCatalog,
    geometry: Geometry,
    variable: str,
    start: datetime,
    end: datetime,
    method: Literal["cell-center", "area-weighted"] = "area-weighted",
    weights_cache: Path | None = None,
    cancel: Event | None = None,
    progress: ProgressCallback | None = None,
) -> list[TimeSeriesPoint]:
    """Calculate one spatially averaged value for every requested hour."""

    cancel = cancel or Event()
    metadata = catalog.variable(variable)

    def archive_progress(value: float, message: str) -> None:
        if progress:
            progress(value * 0.2, message)

    grid = open_aorc_window(
        catalog,
        variable,
        start,
        end,
        geometry.bounds,
        cancel,
        archive_progress,
    )

    def calculation_progress(value: float, message: str) -> None:
        if progress:
            progress(0.2 + value * 0.8, message)

    points = average_dataarray(
        grid,
        geometry,
        metadata.missing_value,
        metadata.units,
        method,
        weights_cache,
        cancel,
        calculation_progress,
    )
    if len(points) != grid.sizes["time"]:
        raise ArchiveError("The time-series result has an unexpected length")
    return points
