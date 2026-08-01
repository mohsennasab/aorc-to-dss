"""Small end-to-end event export with synthetic AORC data."""

import json
from pathlib import Path
from threading import Event

import numpy as np
import pandas as pd
import xarray as xr
import rasterio
from PIL import Image

import aorctodss_service.pipeline as pipeline
from aorctodss_service.dss.adapter import HecDssAdapter
from aorctodss_service.models import VariableMetadata


class SyntheticCatalog:
    """Catalog stub for an offline pipeline test."""

    def variable(self, source_name: str) -> VariableMetadata:
        assert source_name == "APCP_surface"
        return VariableMetadata(
            source_name="APCP_surface",
            display_name="Total Precipitation",
            units="kg/m^2",
            temporal_resolution="1 hour",
            start="2020-01-01T00:00:00Z",
            end="2020-01-01T02:00:00Z",
            missing_value=-32767,
            description="Synthetic hourly depth",
            aggregation="sum",
            dss_parameter="PRECIP",
            dss_units="MM",
            dss_data_type=1,
        )


def test_zarr_promotion_retries_a_temporary_windows_lock(
    tmp_path: Path,
    monkeypatch,
) -> None:
    partial = tmp_path / "partial.zarr"
    target = tmp_path / "event.zarr"
    partial.mkdir()
    attempts = 0
    original_replace = Path.replace

    def replace(path: Path, destination: Path) -> Path:
        nonlocal attempts
        if path == partial and attempts < 2:
            attempts += 1
            raise PermissionError("temporary OneDrive lock")
        return original_replace(path, destination)

    monkeypatch.setattr(Path, "replace", replace)
    monkeypatch.setattr(pipeline.time, "sleep", lambda _seconds: None)
    pipeline._promote_zarr_store(partial, target)
    assert attempts == 2
    assert target.is_dir()


def test_synthetic_event_export(tmp_path: Path, monkeypatch) -> None:
    latitudes = np.linspace(34.95, 35.15, 24)
    longitudes = np.linspace(-90.05, -89.85, 24)
    values = np.stack([
        np.full((24, 24), 2.0, dtype=np.float32),
        np.full((24, 24), 3.0, dtype=np.float32),
    ])
    data = xr.DataArray(
        values,
        dims=("time", "latitude", "longitude"),
        coords={
            "time": np.array(["2020-01-01T01:00", "2020-01-01T02:00"], dtype="datetime64[ns]"),
            "latitude": latitudes,
            "longitude": longitudes,
        },
        name="APCP_surface",
        attrs={"units": "kg/m^2", "missing_value": -32767},
    ).chunk({"time": 2, "latitude": 7, "longitude": 9})
    data.encoding["chunks"] = (144, 128, 256)
    monkeypatch.setattr(pipeline, "open_aorc_window", lambda *args, **kwargs: data)
    incomplete_store = (
        tmp_path
        / "cache"
        / "aorc_20200101t0000z_002h_shg2k_apcp.zarr"
    )
    incomplete_store.mkdir(parents=True)
    (incomplete_store / "partial").write_text("incomplete", encoding="utf-8")
    payload = {
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [-90.0, 35.0],
                [-89.9, 35.0],
                [-89.9, 35.1],
                [-90.0, 35.1],
                [-90.0, 35.0],
            ]],
        },
        "variable": "APCP_surface",
        "unit_system": "us-customary",
        "event_start": "2020-01-01T00:00:00Z",
        "event_end": "2020-01-01T02:00:00Z",
        "output_dir": str(tmp_path),
        "dss_filename": "event.dss",
        "watershed": "TEST",
        "cell_size": 2000,
        "buffer_m": 0,
        "overwrite": False,
    }
    progress = []
    result = pipeline.run_export(
        payload,
        Event(),
        lambda value, message: progress.append((value, message)),
        SyntheticCatalog(),
    )
    assert result.dss_file.is_file()
    assert result.cog_file.is_file()
    assert result.timeseries_file.is_file()
    assert result.timeseries_parquet and result.timeseries_parquet.is_file()
    assert result.aoi_file and result.aoi_file.is_file()
    assert result.validation_report.is_file()
    assert result.animation_file and result.animation_file.is_file()
    assert result.dss_file.parent.name == "dss"
    assert result.cog_file.parent.name == "rasters"
    assert result.timeseries_file.parent.name == "timeseries"
    assert result.event_summary.parent.name == "metadata"
    assert result.processing_log.parent.name == "logs"
    assert result.zarr_store.parent.name == "cache"
    assert (result.zarr_store / ".zmetadata").is_file()
    assert len(result.pathnames) == 2
    assert not [check for check in result.validation if check.status == "failure"]
    assert progress[-1][0] == 1
    series = pd.read_csv(result.timeseries_file)
    assert set(series["units"]) == {"in"}
    assert np.allclose(series["value"], np.array([2.0, 3.0]) / 25.4)
    with rasterio.open(result.cog_file) as dataset:
        raster = dataset.read(1)
        assert dataset.crs.to_epsg() == 5070
        assert dataset.tags(ns="IMAGE_STRUCTURE")["LAYOUT"] == "COG"
        assert dataset.nodata == -9999
        assert dataset.tags(1)["aorctodss_mask"] == "AORC source clip, all_touched=True"
        assert dataset.tags(1)["aorctodss_resampling"] == "nearest"
        assert dataset.tags(1)["aorctodss_colormap"] == "gist_ncar"
        assert dataset.tags(1)["aorctodss_transparent_zero"] == "true"
        assert np.any(raster == dataset.nodata)
        assert np.any(raster != dataset.nodata)
        assert not np.any(raster == 0)
    with HecDssAdapter(result.dss_file) as adapter:
        dss_values = np.asarray(adapter.read_grid_record(result.pathnames[0]).data)
        assert np.any(dss_values <= -3.0e38)
        assert np.any(dss_values > -3.0e38)
    grid_metadata = json.loads(result.grid_metadata.read_text(encoding="utf-8"))
    assert grid_metadata["output_units"]["dss"] == "IN"
    assert grid_metadata["processing"] == {
        "timeseries_averaging": "area-weighted",
        "source_clip_all_touched": True,
        "resampling": "nearest",
        "lower_left_indices": "floor minimum projected pixel-center coordinates",
    }
    assert result.visualization == {
        "colormap": "gist_ncar",
        "rescale_min": 0.0,
        "rescale_max": result.visualization["rescale_max"],
        "nodata": -9999.0,
        "transparent_zero": True,
        "crs": "EPSG:5070",
        "layer_name": "AORC Cumulative Precipitation",
        "cog_relative_path": result.cog_file.relative_to(tmp_path).as_posix(),
    }
    assert result.visualization["rescale_max"] > 0
    value_check = next(
        check for check in result.validation if check.name == "Value preservation"
    )
    assert value_check.status == "pass"
    assert value_check.details["comparison"] == (
        "Area-weighted AOI means before and after reprojection"
    )
    assert value_check.details["event_total"]["percent_difference"] < 0.01
    with Image.open(result.animation_file) as animation:
        assert animation.size == (1120, 630)
        assert animation.n_frames == 2
        first_frame = np.asarray(animation.convert("RGB"))
        assert np.all(first_frame[0, 0] >= 245)
        orange_boundary = (
            (first_frame[..., 0] > 180)
            & (first_frame[..., 1] > 50)
            & (first_frame[..., 1] < 150)
            & (first_frame[..., 2] < 90)
        )
        assert np.count_nonzero(orange_boundary) > 50
