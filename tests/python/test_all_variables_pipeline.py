"""End-to-end output coverage for every supported AORC variable."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event
from typing import Literal

import numpy as np
import pytest
import rasterio
import xarray as xr
from PIL import Image

import aorctodss_service.pipeline as pipeline
from aorctodss_service.dss.adapter import HecDssAdapter
from aorctodss_service.dss.pathname import DSSPathname
from aorctodss_service.models import VariableMetadata


VARIABLES = [
    ("APCP_surface", "Precipitation", "kg/m^2", "sum", "PRECIP", "MM", 1, 4.0, "cumulative_precipitation"),
    ("TMP_2maboveground", "Air Temperature", "K", "mean", "AIRTEMP", "DEG C", 2, 285.0, "mean_air_temperature"),
    ("SPFH_2maboveground", "Specific Humidity", "kg/kg", "mean", "SPEC-HUMID", "KG/KG", 2, 0.008, "mean_specific_humidity"),
    ("DLWRF_surface", "Downward Longwave Radiation Flux", "W/m^2", "mean", "DLWRF", "W/M2", 0, 310.0, "mean_downward_longwave_radiation_flux"),
    ("DSWRF_surface", "Downward Shortwave Radiation Flux", "W/m^2", "mean", "DSWRF", "W/M2", 0, 420.0, "mean_downward_shortwave_radiation_flux"),
    ("PRES_surface", "Surface Air Pressure", "Pa", "mean", "PRESSURE", "PA", 2, 96000.0, "mean_surface_air_pressure"),
    ("UGRD_10maboveground", "Eastward Wind Component at 10 m", "m/s", "mean", "WIND-U", "M/S", 2, -3.0, "mean_eastward_wind_component_10m"),
    ("VGRD_10maboveground", "Northward Wind Component at 10 m", "m/s", "mean", "WIND-V", "M/S", 2, 5.0, "mean_northward_wind_component_10m"),
]


class Catalog:
    def __init__(self, metadata: VariableMetadata) -> None:
        self.metadata = metadata

    def variable(self, source_name: str) -> VariableMetadata:
        assert source_name == self.metadata.source_name
        return self.metadata


@pytest.mark.parametrize(
    ("source", "display", "source_units", "aggregation", "parameter", "dss_units", "data_type", "base", "summary_name"),
    VARIABLES,
)
def test_complete_export_for_supported_variable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
    display: str,
    source_units: str,
    aggregation: Literal["sum", "mean", "instant"],
    parameter: str,
    dss_units: str,
    data_type: int,
    base: float,
    summary_name: str,
) -> None:
    metadata = VariableMetadata(
        source_name=source,
        display_name=display,
        units=source_units,
        temporal_resolution="1 hour",
        start="2020-01-01T00:00:00Z",
        end="2020-01-02T00:00:00Z",
        missing_value=-32767,
        description="Synthetic variable validation",
        aggregation=aggregation,
        dss_parameter=parameter,
        dss_units=dss_units,
        dss_data_type=data_type,
    )
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    offset = 1 if metadata.is_interval else 0
    latitudes = np.linspace(35.0, 35.12, 16)
    longitudes = np.linspace(-84.0, -83.88, 16)
    spatial = np.add.outer(np.linspace(0, 0.2, 16), np.linspace(0, 0.3, 16))
    values = np.stack([base + spatial, base + 1 + spatial]).astype(np.float32)
    data = xr.DataArray(
        values,
        dims=("time", "latitude", "longitude"),
        coords={
            "time": np.asarray(
                [
                    (start + timedelta(hours=index + offset)).replace(tzinfo=None)
                    for index in range(2)
                ],
                dtype="datetime64[ns]",
            ),
            "latitude": latitudes,
            "longitude": longitudes,
        },
        name=source,
        attrs={"units": source_units, "missing_value": -32767},
    ).chunk({"time": 2, "latitude": 8, "longitude": 8})
    monkeypatch.setattr(pipeline, "open_aorc_window", lambda *args, **kwargs: data)
    payload = {
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [-83.98, 35.02],
                [-83.90, 35.02],
                [-83.90, 35.10],
                [-83.98, 35.10],
                [-83.98, 35.02],
            ]],
        },
        "variable": source,
        "unit_system": "metric",
        "event_start": "2020-01-01T00:00:00Z",
        "event_end": "2020-01-01T02:00:00Z",
        "output_dir": str(tmp_path),
        "watershed": "UPPER-TENNESSEE",
        "cell_size": 2000,
        "buffer_m": 0,
        "overwrite": False,
    }
    result = pipeline.run_export(
        payload,
        Event(),
        lambda _value, _message: None,
        Catalog(metadata),
    )

    assert result.dss_file.name.startswith("aorc_20200101t0000z_002h_shg2k_")
    assert result.cog_file.name.endswith(f"_{summary_name}.tif")
    assert result.animation_file and result.animation_file.is_file()
    assert not [item for item in result.validation if item.status == "failure"]
    assert len(result.pathnames) == 2
    parsed = [DSSPathname.parse(pathname) for pathname in result.pathnames]
    assert all(bool(item.e) is metadata.is_interval for item in parsed)
    with HecDssAdapter(result.dss_file) as dss:
        assert dss.list_pathnames() == result.pathnames
        record = dss.read_grid_record(result.pathnames[0])
        assert record.dataUnits.upper() == dss_units
        assert record.isInterval == (1 if metadata.is_interval else 0)
    with rasterio.open(result.cog_file) as raster:
        assert raster.tags(1)["statistic"] == (
            "event total" if aggregation == "sum" else "event mean"
        )
    with Image.open(result.animation_file) as animation:
        assert animation.n_frames == 2
        assert animation.size == (1120, 630)
    summary = json.loads(result.event_summary.read_text(encoding="utf-8"))
    assert summary["variable"]["temporal_support"] == (
        "interval" if metadata.is_interval else "instantaneous"
    )
    assert summary["output_statistic"] == (
        "event total" if aggregation == "sum" else "event mean"
    )
    value_check = next(
        item for item in result.validation if item.name == "Value preservation"
    )
    assert ("event_total" if aggregation == "sum" else "event_mean") in value_check.details
