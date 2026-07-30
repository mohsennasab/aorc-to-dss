"""Chunked reads from annual AORC Zarr stores."""

from __future__ import annotations

from datetime import datetime, timezone
from threading import Event
from typing import Callable

import s3fs
import numpy as np
import xarray as xr

from ..exceptions import ArchiveError, CancelledError
from .catalog import AORCCatalog

ProgressCallback = Callable[[float, str], None]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _datetime64(value: datetime) -> np.datetime64:
    """Return a timezone-free UTC timestamp compatible with xarray coordinates."""

    naive_utc = _utc(value).replace(tzinfo=None)
    return np.datetime64(naive_utc, "ns")


def years_in_range(start: datetime, end: datetime) -> list[int]:
    """Return all annual stores touched by a half-open interval."""

    start = _utc(start)
    end = _utc(end)
    if end <= start:
        raise ArchiveError("The requested end time must be after the start time")
    last_included = end.timestamp() - 1
    end_year = datetime.fromtimestamp(last_included, tz=timezone.utc).year
    return list(range(start.year, end_year + 1))


def open_aorc_window(
    catalog: AORCCatalog,
    variable: str,
    start: datetime,
    end: datetime,
    bounds: tuple[float, float, float, float],
    cancel: Event | None = None,
    progress: ProgressCallback | None = None,
) -> xr.DataArray:
    """Open only the chunks needed for a variable, period, and bounding box."""

    cancel = cancel or Event()
    start = _utc(start)
    end = _utc(end)
    stores: list[xr.DataArray] = []
    years = years_in_range(start, end)
    archive_years = set(catalog.years())
    missing = [year for year in years if year not in archive_years]
    if missing:
        raise ArchiveError(f"AORC annual stores are missing for {missing}")
    filesystem = s3fs.S3FileSystem(
        anon=True,
        config_kwargs={
            "max_pool_connections": 8,
            "retries": {"max_attempts": 3, "mode": "adaptive"},
        },
    )
    min_x, min_y, max_x, max_y = bounds
    for index, year in enumerate(years):
        if cancel.is_set():
            raise CancelledError("AORC read was cancelled")
        if progress:
            progress(index / max(len(years), 1), f"Opening AORC {year}")
        mapper = s3fs.S3Map(root=catalog.store_url(year), s3=filesystem, check=False)
        try:
            dataset = xr.open_zarr(mapper, consolidated=True, chunks={})
            if variable not in dataset:
                raise ArchiveError(f"{variable} is not present in the {year} AORC store")
            latitude = dataset.latitude.values
            lat_slice = slice(min_y, max_y) if latitude[0] < latitude[-1] else slice(max_y, min_y)
            subset = dataset[variable].sel(
                longitude=slice(min_x, max_x),
                latitude=lat_slice,
            )
            subset = subset.sel(
                time=slice(
                    _datetime64(start),
                    _datetime64(end) - np.timedelta64(1, "ns"),
                )
            )
            stores.append(subset)
        except ArchiveError:
            raise
        except Exception as exc:
            raise ArchiveError(
                f"Could not open AORC data for {year}",
                "Check the NOAA archive status and retry. A short outage may be temporary.",
            ) from exc
    if not stores:
        raise ArchiveError("The request did not select any AORC annual stores")
    combined = xr.concat(stores, dim="time") if len(stores) > 1 else stores[0]
    if combined.sizes.get("time", 0) == 0:
        raise ArchiveError("No AORC hours were found for the requested period")
    if progress:
        progress(1, "AORC window is ready")
    return combined
