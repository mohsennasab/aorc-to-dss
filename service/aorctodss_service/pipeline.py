"""End-to-end event conversion pipeline."""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event
from typing import Any, Callable

import numpy as np
import xarray as xr
import geopandas as gpd
from pyproj import Transformer
from rasterio.warp import Resampling
from shapely import to_geojson

from .aorc.catalog import AORCCatalog
from .aorc.subset import open_aorc_window
from .aorc.timeseries import average_dataarray
from .dss.adapter import HecDssAdapter
from .dss.pathname import DSSPathname
from .dss.validator import validate_dss
from .events.selection import custom_event
from .models import ProcessingResult
from .outputs import (
    validation_payload,
    write_json,
    write_timeseries_csv,
    write_timeseries_parquet,
)
from .spatial.cog import write_cog
from .spatial.geometry import prepare_geometry
from .spatial.reprojection import aoi_grid_mask, reproject_series
from .spatial.shg import SHG_CRS, build_shg_grid, grid_estimates
from .units import convert_points, convert_values, output_units

Progress = Callable[[float, str], None]


def _event_source_range(start: Any, end: Any, aggregation: str) -> tuple[Any, Any]:
    if aggregation == "sum":
        return start + timedelta(hours=1), end + timedelta(hours=1)
    return start, end


def _output_bounds_wgs84(grid: Any) -> tuple[float, float, float, float]:
    transformer = Transformer.from_crs(SHG_CRS, "EPSG:4326", always_xy=True)
    points = [
        transformer.transform(grid.min_x, grid.min_y),
        transformer.transform(grid.min_x, grid.max_y),
        transformer.transform(grid.max_x, grid.min_y),
        transformer.transform(grid.max_x, grid.max_y),
    ]
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def _write_animation_zarr(
    data: xr.DataArray,
    target: Path,
    variable: str,
    attributes: dict[str, Any],
) -> None:
    """Write an event cube with aligned Dask and Zarr chunks.

    NOAA's annual encoding describes chunks anchored at the full-store origin.
    A spatial slice can begin partway through those chunks, so retaining that
    encoding would make several Dask chunks write into the same output chunk.
    Rechunk the event window from its own origin and let xarray use those exact
    chunks for the new store.
    """

    chunk_sizes = {
        dimension: min(
            data.sizes[dimension],
            24 if dimension == "time" else 128 if "lat" in dimension.lower() else 256,
        )
        for dimension in data.dims
    }
    animation_data = data.chunk(chunk_sizes).to_dataset(name=variable)
    animation_data.attrs.update(attributes)
    animation_data[variable].encoding.pop("chunks", None)
    animation_data[variable].encoding.pop("preferred_chunks", None)
    animation_data.to_zarr(target, mode="w", consolidated=True)


def estimate_export(payload: dict[str, Any]) -> dict[str, Any]:
    """Estimate grid dimensions and storage before processing."""

    summary = prepare_geometry(payload["geometry"], payload.get("source_crs", "EPSG:4326"))
    event = custom_event(payload["event_start"], payload["event_end"])
    grid = build_shg_grid(
        summary.geometry,
        int(payload.get("cell_size", 2000)),
        float(payload.get("buffer_m", 0)),
    )
    return {
        "area": summary.to_dict(),
        "grid": {
            "cell_size": grid.cell_size,
            "bounds": [grid.min_x, grid.min_y, grid.max_x, grid.max_y],
            **grid_estimates(grid, event.hours),
        },
    }


def run_export(
    payload: dict[str, Any],
    cancel: Event,
    progress: Progress,
    catalog: AORCCatalog | None = None,
) -> ProcessingResult:
    """Create DSS, COG, time series, logs, inventory, and validation output."""

    catalog = catalog or AORCCatalog()
    output_dir = Path(payload["output_dir"]).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    processing_log = output_dir / "processing.log"
    handler = logging.FileHandler(processing_log, mode="w", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger = logging.getLogger(f"aorctodss.{id(cancel)}")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.propagate = False
    try:
        progress(0.01, "Validating area and event")
        summary = prepare_geometry(
            payload["geometry"],
            payload.get("source_crs", "EPSG:4326"),
            bool(payload.get("dissolve", True)),
        )
        event = custom_event(payload["event_start"], payload["event_end"])
        metadata = catalog.variable(payload["variable"])
        units = output_units(metadata, payload.get("unit_system", "metric"))
        grid = build_shg_grid(
            summary.geometry,
            int(payload.get("cell_size", 2000)),
            float(payload.get("buffer_m", 0)),
        )
        source_start, source_end = _event_source_range(
            event.start,
            event.end,
            metadata.aggregation,
        )
        bounds = _output_bounds_wgs84(grid)
        logger.info("AOI area %.3f sq km", summary.area_sq_km)
        logger.info("Event %s to %s UTC", event.start.isoformat(), event.end.isoformat())
        logger.info("SHG grid %s by %s at %s m", grid.width, grid.height, grid.cell_size)
        dss_file = output_dir / payload.get("dss_filename", "aorc_event.dss")
        if dss_file.exists() and not bool(payload.get("overwrite", False)):
            raise FileExistsError(
                f"{dss_file} exists. Enable overwrite or choose a different filename."
            )
        zarr_store = output_dir / "event_frames.zarr"
        zarr_partial = output_dir / ".event_frames.zarr.partial"
        if zarr_partial.exists():
            shutil.rmtree(zarr_partial)
        reuse_zarr = False
        if zarr_store.exists():
            if not (zarr_store / ".zmetadata").is_file():
                logger.warning("Removed an incomplete event Zarr store from an earlier failed run")
                shutil.rmtree(zarr_store)
            else:
                existing = xr.open_zarr(zarr_store, consolidated=True)
                reuse_zarr = (
                    metadata.source_name in existing
                    and existing.sizes.get("time") == event.hours
                    and existing.attrs.get("event_start_utc") == event.start.isoformat()
                    and existing.attrs.get("event_end_utc") == event.end.isoformat()
                    and existing.attrs.get("source_bounds_wgs84") == list(bounds)
                )
                existing.close()
            if not reuse_zarr:
                if zarr_store.exists() and not bool(payload.get("overwrite", False)):
                    raise FileExistsError(
                        f"{zarr_store} contains a different event. Enable overwrite or choose another folder."
                    )
                if zarr_store.exists():
                    shutil.rmtree(zarr_store)
            else:
                logger.info("Reused the existing event Zarr subset")
                progress(0.20, "Reusing the cached event window")
        if not reuse_zarr:
            progress(0.04, "Reading the event window from NOAA")
            data = open_aorc_window(
                catalog,
                metadata.source_name,
                source_start,
                source_end,
                bounds,
                cancel,
                lambda value, message: progress(0.04 + value * 0.16, message),
            )
            if data.sizes["time"] != event.hours:
                raise ValueError(
                    f"Expected {event.hours} AORC hours and found {data.sizes['time']}"
                )
            _write_animation_zarr(
                data,
                zarr_partial,
                metadata.source_name,
                {
                    "crs": "EPSG:4326",
                    "event_start_utc": event.start.isoformat(),
                    "event_end_utc": event.end.isoformat(),
                    "source_bounds_wgs84": list(bounds),
                    "aorctodss_role": "temporary event animation subset",
                },
            )
            zarr_partial.replace(zarr_store)
        data = xr.open_zarr(zarr_store, consolidated=True)[metadata.source_name]
        progress(0.22, "Calculating watershed averages")
        points = average_dataarray(
            data,
            summary.geometry,
            metadata.missing_value,
            metadata.units,
            payload.get("averaging_method", "area-weighted"),
            output_dir / ".weights",
            cancel,
            lambda value, message: progress(0.22 + value * 0.13, message),
        )
        points = convert_points(points, metadata.units, units)
        aoi_mask = aoi_grid_mask(summary.geometry, grid)
        if not np.any(aoi_mask):
            raise ValueError(
                "The selected SHG cell size leaves no cell centers inside the study area. "
                "Choose a smaller SHG cell size."
            )
        timeseries_file = write_timeseries_csv(output_dir / "watershed_timeseries.csv", points)
        timeseries_parquet = write_timeseries_parquet(
            output_dir / "watershed_timeseries.parquet",
            points,
        )
        aoi_file = output_dir / "study_area.gpkg"
        gpd.GeoDataFrame(
            [{"source_features": summary.feature_count, "area_sq_km": summary.area_sq_km}],
            geometry=[summary.geometry],
            crs="EPSG:4326",
        ).to_file(aoi_file, layer="study_area", driver="GPKG")
        if dss_file.exists():
            dss_file.unlink()
        resampling = (
            Resampling.average
            if metadata.aggregation == "sum"
            else Resampling.bilinear
        )
        pathnames: list[str] = []
        source_means: list[float] = []
        projected_means: list[float] = []
        summary_grid = np.zeros((grid.height, grid.width), dtype=np.float64)
        summary_count = np.zeros((grid.height, grid.width), dtype=np.uint32)
        progress(0.36, "Creating the SHG DSS file")
        with HecDssAdapter(dss_file) as adapter:
            for index, (timestamp, values) in enumerate(
                reproject_series(
                    data,
                    grid,
                    metadata.missing_value,
                    resampling,
                    cancel,
                )
            ):
                point_value = points[index].value
                source_means.append(
                    float(point_value) if point_value is not None else float("nan")
                )
                values = convert_values(values, metadata.units, units.calculation)
                values = np.where(aoi_mask, values, np.nan)
                valid = np.isfinite(values)
                projected_means.append(
                    float(values[valid].mean()) if np.any(valid) else float("nan")
                )
                if metadata.aggregation == "sum":
                    summary_grid[valid] += values[valid]
                else:
                    summary_grid[valid] += values[valid]
                summary_count[valid] += 1
                unix_seconds = int(np.datetime64(timestamp, "s").astype(np.int64))
                source_time = datetime.fromtimestamp(unix_seconds, tz=timezone.utc)
                if metadata.aggregation == "sum":
                    interval_end = source_time
                    interval_start = interval_end - timedelta(hours=1)
                    interval = True
                else:
                    interval_start = source_time
                    interval_end = source_time
                    interval = False
                pathname = str(
                    DSSPathname.grid(
                        payload.get("watershed", "WATERSHED"),
                        payload.get("parameter", metadata.dss_parameter),
                        interval_start,
                        interval_end,
                        grid.cell_size,
                        payload.get("dataset_version", "AORC-V1.1"),
                        interval,
                    )
                )
                adapter.write_grid_record(
                    pathname,
                    values,
                    grid,
                    units.dss,
                    metadata.dss_data_type,
                    overwrite=False,
                )
                pathnames.append(pathname)
                progress(
                    0.36 + (index + 1) / event.hours * 0.37,
                    f"Wrote DSS grid {index + 1} of {event.hours}",
                )
        if metadata.aggregation != "sum":
            summary_grid = np.divide(
                summary_grid,
                summary_count,
                out=np.full_like(summary_grid, np.nan),
                where=summary_count > 0,
            )
            statistic = "event mean"
        else:
            summary_grid[summary_count == 0] = np.nan
            statistic = "event total"
        display_grid = (
            np.where(summary_grid > 0, summary_grid, np.nan)
            if metadata.source_name == "APCP_surface"
            else summary_grid
        )
        display_values = display_grid[np.isfinite(display_grid)]
        if display_values.size:
            display_min = float(np.nanpercentile(display_values, 2))
            display_max = float(np.nanpercentile(display_values, 98))
            if display_max <= display_min:
                display_max = display_min + max(abs(display_min) * 0.1, 1.0e-6)
        else:
            display_min, display_max = 0.0, 1.0
        visualization = {
            "colormap": "blues" if metadata.source_name == "APCP_surface" else "viridis",
            "rescale_min": 0.0 if metadata.source_name == "APCP_surface" else display_min,
            "rescale_max": display_max,
            "nodata": -9999.0,
            "transparent_zero": metadata.source_name == "APCP_surface",
            "crs": "EPSG:5070",
        }
        cog_file = write_cog(
            output_dir / "event_summary.tif",
            summary_grid,
            grid,
            units.dss,
            statistic,
            transparent_zero=metadata.source_name == "APCP_surface",
        )
        progress(0.75, "Reading the DSS file back for validation")
        checks = validate_dss(
            dss_file,
            pathnames,
            grid,
            units.dss,
            event.start,
            event.end,
            source_means,
            projected_means,
        )
        pathname_inventory = write_json(output_dir / "dss_pathnames.json", pathnames)
        grid_metadata = write_json(
            output_dir / "grid_metadata.json",
            {
                "grid": {
                    "cell_size": grid.cell_size,
                    "bounds": [grid.min_x, grid.min_y, grid.max_x, grid.max_y],
                    "width": grid.width,
                    "height": grid.height,
                    "lower_left_cell_x": grid.lower_left_cell_x,
                    "lower_left_cell_y": grid.lower_left_cell_y,
                    "crs_wkt": grid.crs_wkt,
                },
                "variable": metadata.to_dict(),
                "output_units": {
                    "display": units.display,
                    "dss": units.dss,
                    "system": payload.get("unit_system", "metric"),
                },
                "aoi": summary.to_dict(),
            },
        )
        validation_report = write_json(
            output_dir / "validation_report.json",
            validation_payload(checks),
        )
        event_summary = write_json(
            output_dir / "event_summary.json",
            {
                "event_start_utc": event.start.isoformat(),
                "event_end_utc": event.end.isoformat(),
                "hours": event.hours,
                "variable": metadata.to_dict(),
                "output_units": {
                    "display": units.display,
                    "dss": units.dss,
                    "system": payload.get("unit_system", "metric"),
                },
                "watershed": payload.get("watershed", "WATERSHED"),
                "aoi_geometry": json.loads(to_geojson(summary.geometry)),
                "output_statistic": statistic,
            },
        )
        download_log = output_dir / "download.log"
        download_log.write_text(
            "AORC data were read by chunk from the public annual Zarr stores.\n"
            f"Source window: {source_start.isoformat()} to {source_end.isoformat()}\n"
            f"Variable: {metadata.source_name}\n"
            f"Records: {event.hours}\n",
            encoding="utf-8",
        )
        progress(1, "DSS export and validation finished")
        return ProcessingResult(
            output_dir=output_dir,
            dss_file=dss_file,
            timeseries_file=timeseries_file,
            timeseries_parquet=timeseries_parquet,
            aoi_file=aoi_file,
            event_summary=event_summary,
            download_log=download_log,
            processing_log=processing_log,
            pathname_inventory=pathname_inventory,
            grid_metadata=grid_metadata,
            validation_report=validation_report,
            cog_file=cog_file,
            animation_file=None,
            zarr_store=zarr_store,
            visualization=visualization,
            pathnames=pathnames,
            validation=checks,
        )
    except Exception:
        logger.exception("Export failed")
        raise
    finally:
        logger.removeHandler(handler)
        handler.close()
