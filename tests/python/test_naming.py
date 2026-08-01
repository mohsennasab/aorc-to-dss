"""Descriptive, variable-aware export artifact naming."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from aorctodss_service.models import EventWindow, VariableMetadata
from aorctodss_service.naming import event_identifier, output_layout, variable_names


def metadata(source: str, display: str, aggregation: str = "mean") -> VariableMetadata:
    return VariableMetadata(
        source_name=source,
        display_name=display,
        units="unit",
        temporal_resolution="1 hour",
        start="2020-01-01T00:00:00Z",
        end="2020-01-02T00:00:00Z",
        missing_value=-32767,
        description="Test variable",
        aggregation=aggregation,
        dss_parameter="TEST",
        dss_units="UNIT",
        dss_data_type=2,
    )


EVENT = EventWindow(
    datetime(2020, 1, 2, 3, tzinfo=timezone.utc),
    datetime(2020, 1, 4, 3, tzinfo=timezone.utc),
)


@pytest.mark.parametrize(
    ("source", "summary"),
    [
        ("APCP_surface", "cumulative_precipitation"),
        ("TMP_2maboveground", "mean_air_temperature"),
        ("SPFH_2maboveground", "mean_specific_humidity"),
        ("PRES_surface", "mean_surface_air_pressure"),
        ("UGRD_10maboveground", "mean_eastward_wind_component_10m"),
    ],
)
def test_reviewed_variable_summary_names(source: str, summary: str) -> None:
    assert variable_names(metadata(source, source)).summary == summary


def test_event_identifier_contains_required_metadata() -> None:
    value = event_identifier(EVENT, 2000, metadata("APCP_surface", "Precipitation", "sum"))
    assert value == "aorc_20200102t0300z_048h_shg2k_precipitation"


def test_output_layout_organizes_and_describes_artifacts(tmp_path: Path) -> None:
    layout = output_layout(tmp_path, EVENT, 4000, metadata("TMP_2maboveground", "Air Temperature"))
    assert layout.dss_file == tmp_path / "dss" / "aorc_20200102t0300z_048h_shg4k_air_temperature.dss"
    assert layout.cog_file.parent.name == "rasters"
    assert layout.cog_file.name.endswith("_mean_air_temperature.tif")
    assert layout.animation_file.parent.name == "animation"
    assert layout.animation_file.name.endswith("_hourly_air_temperature_with_aoi_average.gif")
    assert layout.zarr_store.parent.name == "cache"


def test_custom_dss_name_is_kept_inside_dss_folder(tmp_path: Path) -> None:
    layout = output_layout(
        tmp_path,
        EVENT,
        2000,
        metadata("APCP_surface", "Precipitation", "sum"),
        "../My Event",
    )
    assert layout.dss_file == tmp_path / "dss" / "My Event.dss"
