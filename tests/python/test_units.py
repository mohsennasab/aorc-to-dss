"""Output unit selection and conversion tests."""

import numpy as np

from aorctodss_service.models import TimeSeriesPoint, VariableMetadata
from aorctodss_service.units import convert_points, convert_values, output_units


def metadata(source_name: str, units: str, dss_units: str) -> VariableMetadata:
    return VariableMetadata(
        source_name=source_name,
        display_name=source_name,
        units=units,
        temporal_resolution="1 hour",
        start="2000-01-01T00:00:00Z",
        end="2000-01-01T01:00:00Z",
        missing_value=-32767,
        description="test",
        aggregation="sum" if source_name == "APCP_surface" else "mean",
        dss_parameter="TEST",
        dss_units=dss_units,
        dss_data_type=1,
    )


def test_precipitation_converts_to_inches() -> None:
    target = output_units(metadata("APCP_surface", "kg/m^2", "MM"), "us-customary")
    assert target.display == "in"
    assert target.dss == "IN"
    assert convert_values(np.array([25.4]), "kg/m^2", target.calculation)[0] == 1


def test_temperature_converts_to_celsius_and_fahrenheit() -> None:
    source = np.array([273.15, 293.15])
    assert np.allclose(convert_values(source, "K", "DEG C"), [0, 20])
    assert np.allclose(convert_values(source, "K", "DEG F"), [32, 68])


def test_time_series_uses_display_units() -> None:
    target = output_units(metadata("TMP_2maboveground", "K", "DEG C"), "metric")
    points = convert_points(
        [TimeSeriesPoint("2000-01-01T00:00:00Z", 273.15, "K")],
        "K",
        target,
    )
    assert points[0].value == 0
    assert points[0].units == "°C"
