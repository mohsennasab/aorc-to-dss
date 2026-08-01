"""Variable-aware names and folder layout for event exports."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .models import EventWindow, VariableMetadata


@dataclass(frozen=True)
class VariableNames:
    """Stable, human-readable terms used in exported artifact names."""

    variable: str
    summary: str
    hourly: str


VARIABLE_NAMES: dict[str, VariableNames] = {
    "APCP_surface": VariableNames(
        "precipitation", "cumulative_precipitation", "hourly_precipitation"
    ),
    "TMP_2maboveground": VariableNames(
        "air_temperature", "mean_air_temperature", "hourly_air_temperature"
    ),
    "SPFH_2maboveground": VariableNames(
        "specific_humidity", "mean_specific_humidity", "hourly_specific_humidity"
    ),
    "DLWRF_surface": VariableNames(
        "downward_longwave_radiation_flux",
        "mean_downward_longwave_radiation_flux",
        "hourly_downward_longwave_radiation_flux",
    ),
    "DSWRF_surface": VariableNames(
        "downward_shortwave_radiation_flux",
        "mean_downward_shortwave_radiation_flux",
        "hourly_downward_shortwave_radiation_flux",
    ),
    "PRES_surface": VariableNames(
        "surface_air_pressure", "mean_surface_air_pressure", "hourly_surface_air_pressure"
    ),
    "UGRD_10maboveground": VariableNames(
        "eastward_wind_component_10m",
        "mean_eastward_wind_component_10m",
        "hourly_eastward_wind_component_10m",
    ),
    "VGRD_10maboveground": VariableNames(
        "northward_wind_component_10m",
        "mean_northward_wind_component_10m",
        "hourly_northward_wind_component_10m",
    ),
}


def slug(value: str) -> str:
    """Convert arbitrary metadata text to a portable lowercase filename token."""

    cleaned = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return cleaned or "meteorological_variable"


def variable_names(metadata: VariableMetadata) -> VariableNames:
    """Return reviewed terms, with a safe fallback for future AORC variables."""

    reviewed = VARIABLE_NAMES.get(metadata.source_name)
    if reviewed is not None:
        return reviewed
    variable = slug(metadata.display_name or metadata.dss_parameter or metadata.source_name)
    statistic = "total" if metadata.aggregation == "sum" else "mean"
    return VariableNames(variable, f"{statistic}_{variable}", f"hourly_{variable}")


def resolution_token(cell_size: int) -> str:
    """Represent common SHG resolutions compactly without losing precision."""

    if cell_size >= 1000 and cell_size % 1000 == 0:
        return f"{cell_size // 1000}k"
    return f"{cell_size}m"


def event_identifier(
    event: EventWindow,
    cell_size: int,
    metadata: VariableMetadata,
) -> str:
    """Build the common identifier used by every artifact in one export."""

    start = event.start.strftime("%Y%m%dt%H%MZ").lower()
    duration = f"{event.hours:03d}h"
    return (
        f"aorc_{start}_{duration}_shg{resolution_token(cell_size)}_"
        f"{variable_names(metadata).variable}"
    )


@dataclass(frozen=True)
class OutputLayout:
    """All export paths derived from one event identifier."""

    root: Path
    identifier: str
    dss_file: Path
    cog_file: Path
    timeseries_csv: Path
    timeseries_parquet: Path
    aoi_file: Path
    event_summary: Path
    pathname_inventory: Path
    grid_metadata: Path
    validation_report: Path
    download_log: Path
    processing_log: Path
    animation_file: Path
    zarr_store: Path
    zarr_partial: Path
    weights_dir: Path


def output_layout(
    root: Path,
    event: EventWindow,
    cell_size: int,
    metadata: VariableMetadata,
    dss_filename: str | None = None,
) -> OutputLayout:
    """Create a predictable folder layout and variable-appropriate filenames."""

    identifier = event_identifier(event, cell_size, metadata)
    names = variable_names(metadata)
    event_prefix = identifier.removesuffix(f"_{names.variable}")
    source_code = slug(metadata.source_name.split("_", 1)[0])
    cache_prefix = f"{event_prefix}_{source_code}"
    requested_dss = Path((dss_filename or "").strip()).name
    if not requested_dss:
        requested_dss = f"{identifier}.dss"
    elif not requested_dss.lower().endswith(".dss"):
        requested_dss += ".dss"
    return OutputLayout(
        root=root,
        identifier=identifier,
        dss_file=root / "dss" / requested_dss,
        cog_file=root / "rasters" / f"{event_prefix}_{names.summary}.tif",
        timeseries_csv=(
            root
            / "timeseries"
            / f"{event_prefix}_aoi_area_weighted_average_{names.variable}.csv"
        ),
        timeseries_parquet=(
            root
            / "timeseries"
            / f"{event_prefix}_aoi_area_weighted_average_{names.variable}.parquet"
        ),
        aoi_file=root / "spatial" / f"{identifier}_study_area.gpkg",
        event_summary=root / "metadata" / f"{identifier}_event_summary.json",
        pathname_inventory=root / "metadata" / f"{identifier}_dss_pathnames.json",
        grid_metadata=root / "metadata" / f"{identifier}_shg_grid_metadata.json",
        validation_report=root / "metadata" / f"{identifier}_validation_report.json",
        download_log=root / "logs" / f"{identifier}_download.log",
        processing_log=root / "logs" / f"{identifier}_processing.log",
        animation_file=(
            root / "animation" / f"{event_prefix}_{names.hourly}_with_aoi_average.gif"
        ),
        zarr_store=root / "cache" / f"{cache_prefix}.zarr",
        zarr_partial=root / "cache" / f".{cache_prefix}.zarr.partial",
        weights_dir=root / "cache" / f"{cache_prefix}_weights",
    )
