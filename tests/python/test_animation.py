"""On-demand native AORC animation frames."""

from datetime import datetime
from pathlib import Path

import numpy as np
import rasterio
import xarray as xr

import aorctodss_service.animation as animation
from aorctodss_service.animation import AnimationManager
from aorctodss_service.models import VariableMetadata


class SyntheticCatalog:
    def variable(self, source_name: str) -> VariableMetadata:
        assert source_name == "APCP_surface"
        return VariableMetadata(
            source_name="APCP_surface",
            display_name="Total Precipitation",
            units="kg/m^2",
            temporal_resolution="1 hour",
            start="2025-01-01T00:00:00Z",
            end="2025-12-31T23:00:00Z",
            missing_value=-32767,
            description="Synthetic precipitation",
            aggregation="sum",
            dss_parameter="PRECIP",
            dss_units="MM",
            dss_data_type=1,
        )


def test_animation_registers_hourly_cog_source_and_builds_clipped_frame(
    tmp_path: Path,
    monkeypatch,
) -> None:
    latitudes = np.linspace(34.95, 35.15, 24)
    longitudes = np.linspace(-90.05, -89.85, 24)
    values = np.full((2, 24, 24), 12.7, dtype=np.float32)
    values[:, :, :3] = 0
    data = xr.DataArray(
        values,
        dims=("time", "latitude", "longitude"),
        coords={
            "time": np.array(
                ["2025-10-27T00:00", "2025-10-27T01:00"],
                dtype="datetime64[ns]",
            ),
            "latitude": latitudes,
            "longitude": longitudes,
        },
        name="APCP_surface",
    )
    calls: list[datetime] = []

    def fake_open(_catalog, _variable, start, _end, _bounds, *_args, **_kwargs):
        calls.append(start)
        return data

    monkeypatch.setattr(animation, "open_aorc_window", fake_open)
    manager = AnimationManager(SyntheticCatalog(), tmp_path)
    result = manager.register(
        {
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
            "event_start": "2025-10-26T23:00:00Z",
            "event_end": "2025-10-27T01:00:00Z",
            "selected_values": [0.1, 0.2],
        }
    )

    assert result["times"] == [
        "2025-10-27T00:00:00Z",
        "2025-10-27T01:00:00Z",
    ]
    assert result["url_template"].endswith("{date:YYYY-MM-DD-HH}.tif")
    assert result["colormap"] == "gist_ncar"
    assert result["nodata"] == -9999

    manager.start_preload(result["id"])
    definition = manager.get(result["id"])
    assert definition and definition.preload_thread
    definition.preload_thread.join(timeout=5)
    preload = manager.status(result["id"])
    assert preload["state"] == "complete"
    assert preload["completed"] == 2
    assert preload["progress"] == 1

    frame = manager.frame(result["id"], "2025-10-27-00")
    assert frame.is_file()
    assert calls == [datetime.fromisoformat("2025-10-27T00:00:00+00:00")]
    with rasterio.open(frame) as dataset:
        raster = dataset.read(1)
        assert dataset.crs.to_epsg() == 4326
        assert dataset.tags(ns="IMAGE_STRUCTURE")["LAYOUT"] == "COG"
        assert dataset.nodata == -9999
        assert dataset.tags(1)["units"] == "in"
        assert np.any(raster == -9999)
        assert np.any(raster > 0)
        assert not np.any(raster == 0)

    assert manager.frame(result["id"], "2025-10-27-00") == frame
    assert len(calls) == 1
