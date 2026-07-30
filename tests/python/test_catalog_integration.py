"""Optional live AORC metadata check."""

import os
from pathlib import Path
from threading import Event
from datetime import datetime, timezone

import pytest

from aorctodss_service.aorc.catalog import AORCCatalog
from aorctodss_service.aorc.subset import open_aorc_window
from aorctodss_service.animation import AnimationManager
from aorctodss_service.pipeline import run_export


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("AORCTODSS_RUN_INTEGRATION") != "1",
    reason="Set AORCTODSS_RUN_INTEGRATION=1 to access the NOAA archive",
)
def test_live_catalog_has_expected_core_variables() -> None:
    catalog = AORCCatalog()
    variables = {item.source_name for item in catalog.variables()}
    assert catalog.years()[0] == 1979
    assert "APCP_surface" in variables
    assert "TMP_2maboveground" in variables


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("AORCTODSS_RUN_INTEGRATION") != "1",
    reason="Set AORCTODSS_RUN_INTEGRATION=1 to access the NOAA archive",
)
def test_live_one_hour_dss_workflow(tmp_path: Path) -> None:
    payload = {
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [-89.99, 35.00],
                [-89.97, 35.00],
                [-89.97, 35.02],
                [-89.99, 35.02],
                [-89.99, 35.00],
            ]],
        },
        "variable": "APCP_surface",
        "event_start": "2020-01-01T00:00:00Z",
        "event_end": "2020-01-01T01:00:00Z",
        "output_dir": str(tmp_path),
        "dss_filename": "live_sample.dss",
        "watershed": "INTEGRATION TEST",
        "cell_size": 2000,
        "buffer_m": 0,
        "overwrite": False,
    }
    result = run_export(payload, Event(), lambda value, message: None)
    assert result.dss_file.is_file()
    assert len(result.pathnames) == 1
    assert not [check for check in result.validation if check.status == "failure"]


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("AORCTODSS_RUN_INTEGRATION") != "1",
    reason="Set AORCTODSS_RUN_INTEGRATION=1 to access the NOAA archive",
)
def test_live_window_crosses_2000_to_2001() -> None:
    data = open_aorc_window(
        AORCCatalog(),
        "APCP_surface",
        datetime(2000, 12, 31, 23, tzinfo=timezone.utc),
        datetime(2001, 1, 1, 1, tzinfo=timezone.utc),
        (-84.1, 35.9, -84.0, 36.0),
    )
    assert data.sizes["time"] == 2
    assert data.sizes["latitude"] > 0
    assert data.sizes["longitude"] > 0


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("AORCTODSS_RUN_INTEGRATION") != "1",
    reason="Set AORCTODSS_RUN_INTEGRATION=1 to access the NOAA archive",
)
def test_live_animation_builds_one_clipped_cog(tmp_path: Path) -> None:
    manager = AnimationManager(AORCCatalog(), tmp_path)
    registration = manager.register(
        {
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [-89.99, 35.00],
                    [-89.97, 35.00],
                    [-89.97, 35.02],
                    [-89.99, 35.02],
                    [-89.99, 35.00],
                ]],
            },
            "variable": "APCP_surface",
            "unit_system": "us-customary",
            "event_start": "2020-01-01T00:00:00Z",
            "event_end": "2020-01-01T02:00:00Z",
            "selected_values": [0.1],
        }
    )
    manager.start_preload(registration["id"])
    definition = manager.get(registration["id"])
    assert definition and definition.preload_thread
    definition.preload_thread.join(timeout=60)
    status = manager.status(registration["id"])
    assert status["state"] == "complete", status
    assert status["completed"] == 2
    assert manager.frame(registration["id"], "2020-01-01-01").is_file()
    assert manager.frame(registration["id"], "2020-01-01-02").is_file()
