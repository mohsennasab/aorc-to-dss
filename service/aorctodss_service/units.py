"""Reviewed unit choices and conversions for AORC outputs."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .models import TimeSeriesPoint, VariableMetadata


@dataclass(frozen=True)
class OutputUnits:
    """Units used for calculations, display, and DSS metadata."""

    calculation: str
    display: str
    dss: str


def output_units(metadata: VariableMetadata, unit_system: str = "metric") -> OutputUnits:
    """Return the requested output units for one AORC variable."""

    customary = unit_system == "us-customary"
    if metadata.source_name == "APCP_surface":
        return OutputUnits("IN", "in", "IN") if customary else OutputUnits("MM", "mm", "MM")
    if metadata.source_name == "TMP_2maboveground":
        return (
            OutputUnits("DEG F", "°F", "DEG F")
            if customary
            else OutputUnits("DEG C", "°C", "DEG C")
        )
    return OutputUnits(metadata.units, metadata.units, metadata.dss_units)


def convert_values(
    values: np.ndarray | float,
    source_units: str,
    target_units: str,
) -> np.ndarray:
    """Convert supported precipitation and temperature values."""

    data = np.asarray(values, dtype=float)
    source = source_units.strip().upper().replace("²", "^2")
    target = target_units.strip().upper()
    if source in {"KG/M^2", "KG M^-2"}:
        if target == "MM":
            return data
        if target == "IN":
            return data / 25.4
    if source == "K":
        if target == "DEG C":
            return data - 273.15
        if target == "DEG F":
            return (data - 273.15) * 9 / 5 + 32
    return data


def convert_points(
    points: list[TimeSeriesPoint],
    source_units: str,
    target: OutputUnits,
) -> list[TimeSeriesPoint]:
    """Convert a time series and apply its user-facing unit label."""

    converted: list[TimeSeriesPoint] = []
    for point in points:
        value = None
        if point.value is not None:
            value = float(convert_values(point.value, source_units, target.calculation))
        converted.append(TimeSeriesPoint(point.time, value, target.display, point.quality))
    return converted
