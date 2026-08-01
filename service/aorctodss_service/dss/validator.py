"""Read-back validation for completed DSS grid sets."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from ..models import GridDefinition, ValidationItem
from .adapter import HecDssAdapter
from .pathname import DSSPathname


def _weighted_mean(values: np.ndarray, weights: np.ndarray) -> float:
    """Calculate a mean over the valid portion of normalized AOI weights."""

    valid = np.isfinite(values) & (values > -3.0e38) & (weights > 0)
    valid_weight = float(weights[valid].sum())
    if valid_weight <= 0:
        return float("nan")
    return float(np.sum(values[valid] * weights[valid]) / valid_weight)


def _parse_dss_time(value: str) -> datetime:
    if value.upper().endswith(":2400"):
        date_part = value[:-5]
        return (
            datetime.strptime(date_part.upper(), "%d%b%Y")
            .replace(tzinfo=timezone.utc)
            + timedelta(days=1)
        )
    return datetime.strptime(value.upper(), "%d%b%Y:%H%M").replace(tzinfo=timezone.utc)


def validate_dss(
    dss_path: Path,
    pathnames: list[str],
    grid: GridDefinition,
    units: str,
    expected_start: datetime,
    expected_end: datetime,
    source_means: list[float],
    projected_means: list[float],
    validation_weights: np.ndarray,
    aggregation: str = "sum",
) -> list[ValidationItem]:
    """Reopen a file and validate record count, metadata, time, and values."""

    checks: list[ValidationItem] = []
    try:
        with HecDssAdapter(dss_path) as adapter:
            inventory = adapter.list_pathnames()
            missing = [pathname for pathname in pathnames if pathname not in inventory]
            checks.append(
                ValidationItem(
                    "Expected pathnames",
                    "failure" if missing else "pass",
                    f"{len(pathnames) - len(missing)} of {len(pathnames)} records found",
                    {"missing": missing},
                )
            )
            checks.append(
                ValidationItem(
                    "Record count",
                    "pass" if len(pathnames) == len(inventory) else "warning",
                    f"Expected {len(pathnames)} records and found {len(inventory)}",
                )
            )
            parsed = [DSSPathname.parse(pathname) for pathname in pathnames]
            starts = [_parse_dss_time(path.d) for path in parsed]
            ends = [_parse_dss_time(path.e) if path.e else start for path, start in zip(parsed, starts)]
            interval_records = bool(parsed and parsed[0].e)
            if interval_records:
                continuous = all(
                    starts[index] == ends[index - 1]
                    for index in range(1, len(starts))
                )
            else:
                continuous = all(
                    starts[index] == starts[index - 1] + timedelta(hours=1)
                    for index in range(1, len(starts))
                )
            checks.append(
                ValidationItem(
                    "Hourly continuity",
                    "pass" if continuous else "failure",
                    "DSS record intervals are continuous" if continuous else "A gap or overlap was found",
                )
            )
            if interval_records:
                boundary_ok = bool(starts) and starts[0] == expected_start and ends[-1] == expected_end
            else:
                boundary_ok = (
                    bool(starts)
                    and starts[0] == expected_start
                    and starts[-1] == expected_end - timedelta(hours=1)
                )
            checks.append(
                ValidationItem(
                    "Event boundaries",
                    "pass" if boundary_ok else "failure",
                    f"First interval starts {starts[0].isoformat()} and last ends {ends[-1].isoformat()}",
                )
            )
            all_null: list[str] = []
            metadata_problems: dict[str, list[str]] = {}
            readback_means: list[float] = []
            for pathname in pathnames:
                record = adapter.read_grid_record(pathname)
                values = np.asarray(record.data, dtype=float)
                valid = np.isfinite(values) & (values > -3.0e38)
                if not np.any(valid):
                    all_null.append(pathname)
                    readback_means.append(float("nan"))
                else:
                    # DSS stores row zero at the southern edge, while the
                    # reprojection array and its weights are north-up.
                    readback_means.append(
                        _weighted_mean(values, np.flipud(validation_weights))
                    )
                problems = adapter.validate_grid_record(pathname, grid, units)
                if problems:
                    metadata_problems[pathname] = problems
            checks.append(
                ValidationItem(
                    "Grid metadata",
                    "failure" if metadata_problems else "pass",
                    "All grid dimensions, units, indices, and SHG metadata match"
                    if not metadata_problems
                    else "One or more grid metadata fields do not match",
                    metadata_problems,
                )
            )
            checks.append(
                ValidationItem(
                    "Non-null grids",
                    "failure" if all_null else "pass",
                    "No all-null grids found" if not all_null else f"{len(all_null)} all-null grids found",
                    {"pathnames": all_null},
                )
            )
            differences: list[dict[str, float]] = []
            for source, projected, readback in zip(source_means, projected_means, readback_means):
                if not all(np.isfinite(value) for value in (source, projected, readback)):
                    continue
                source_to_projected_absolute = abs(projected - source)
                projected_to_dss_absolute = abs(readback - projected)
                differences.append(
                    {
                        "source_aoi_mean": source,
                        "projected_aoi_mean": projected,
                        "dss_aoi_mean": readback,
                        "source_to_projected_absolute": source_to_projected_absolute,
                        "source_to_projected_percent": (
                            source_to_projected_absolute / max(abs(source), 1.0e-6) * 100
                        ),
                        "projected_to_dss_absolute": projected_to_dss_absolute,
                        "projected_to_dss_percent": (
                            projected_to_dss_absolute
                            / max(abs(projected), 1.0e-6)
                            * 100
                        ),
                    }
                )
            finite_source = [value for value in source_means if np.isfinite(value)]
            finite_projected = [value for value in projected_means if np.isfinite(value)]
            if aggregation == "sum":
                summary_name = "event_total"
                summary_label = "Event-total"
                source_summary = float(np.sum(finite_source))
                projected_summary = float(np.sum(finite_projected))
            else:
                summary_name = "event_mean"
                summary_label = "Event-mean"
                source_summary = float(np.mean(finite_source)) if finite_source else float("nan")
                projected_summary = (
                    float(np.mean(finite_projected)) if finite_projected else float("nan")
                )
            event_absolute = abs(projected_summary - source_summary)
            event_percent = event_absolute / max(abs(source_summary), 1.0e-6) * 100
            max_source_absolute = max(
                (item["source_to_projected_absolute"] for item in differences),
                default=0,
            )
            max_source_difference = max(
                (item["source_to_projected_percent"] for item in differences),
                default=0,
            )
            max_dss_difference = max(
                (item["projected_to_dss_percent"] for item in differences),
                default=0,
            )
            status = "pass"
            if max_dss_difference > 0.01:
                status = "failure"
            elif event_percent > 5:
                status = "warning"
            checks.append(
                ValidationItem(
                    "Value preservation",
                    status,
                    (
                        f"{summary_label} area-weighted difference {event_absolute:.6f} "
                        f"{units} ({event_percent:.3f}%); maximum hourly absolute "
                        f"difference {max_source_absolute:.6f} {units}; DSS "
                        f"read-back difference {max_dss_difference:.6f}%"
                    ),
                    {
                        "comparison": (
                            "Area-weighted AOI means before and after reprojection"
                        ),
                        "units": units,
                        summary_name: {
                            "source_aoi_summary": source_summary,
                            "projected_aoi_summary": projected_summary,
                            "absolute_difference": event_absolute,
                            "percent_difference": event_percent,
                        },
                        "maximum_hourly_absolute_difference": max_source_absolute,
                        "maximum_hourly_percent_difference": max_source_difference,
                        "maximum_dss_readback_percent_difference": max_dss_difference,
                        "hourly_differences": differences,
                    },
                )
            )
    except Exception as exc:
        checks.append(
            ValidationItem(
                "DSS reopen",
                "failure",
                f"The DSS file could not be reopened: {exc}",
            )
        )
    else:
        checks.insert(0, ValidationItem("DSS reopen", "pass", "The DSS file reopened successfully"))
    return checks
