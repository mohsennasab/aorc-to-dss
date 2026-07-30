"""Shared request and result models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal


@dataclass(frozen=True)
class VariableMetadata:
    """Metadata for one variable in the active AORC archive."""

    source_name: str
    display_name: str
    units: str
    temporal_resolution: str
    start: str
    end: str
    missing_value: float
    description: str
    aggregation: Literal["sum", "mean", "instant"]
    dss_parameter: str
    dss_units: str
    dss_data_type: int

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready mapping."""

        return asdict(self)


@dataclass(frozen=True)
class TimeSeriesPoint:
    """One UTC watershed time-series value."""

    time: str
    value: float | None
    units: str
    quality: str = "ok"

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready mapping."""

        return asdict(self)


@dataclass(frozen=True)
class EventWindow:
    """A half-open UTC event interval."""

    start: datetime
    end: datetime

    @property
    def hours(self) -> int:
        """Return the number of hourly records."""

        return int((self.end - self.start).total_seconds() / 3600)


@dataclass(frozen=True)
class GridDefinition:
    """A regular SHG raster definition."""

    cell_size: int
    min_x: float
    min_y: float
    max_x: float
    max_y: float
    width: int
    height: int
    crs_wkt: str

    @property
    def lower_left_cell_x(self) -> int:
        """Return the SHG column index at the lower left corner."""

        return round(self.min_x / self.cell_size)

    @property
    def lower_left_cell_y(self) -> int:
        """Return the SHG row index at the lower left corner."""

        return round(self.min_y / self.cell_size)


@dataclass
class ValidationItem:
    """One validation check."""

    name: str
    status: Literal["pass", "warning", "failure"]
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProcessingResult:
    """Files and metadata produced by an event export."""

    output_dir: Path
    dss_file: Path
    timeseries_file: Path
    timeseries_parquet: Path | None
    aoi_file: Path | None
    event_summary: Path
    download_log: Path
    processing_log: Path
    pathname_inventory: Path
    grid_metadata: Path
    validation_report: Path
    cog_file: Path
    animation_file: Path | None
    zarr_store: Path | None
    visualization: dict[str, Any]
    pathnames: list[str]
    validation: list[ValidationItem]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready result."""

        payload = asdict(self)
        for key, value in list(payload.items()):
            if isinstance(value, Path):
                payload[key] = str(value)
        return payload
