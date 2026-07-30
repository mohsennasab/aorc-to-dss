"""Read-back validation for completed DSS grid sets."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from ..models import GridDefinition, ValidationItem
from .adapter import HecDssAdapter
from .pathname import DSSPathname


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
                    readback_means.append(float(values[valid].mean()))
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
            differences = []
            for source, projected, readback in zip(source_means, projected_means, readback_means):
                denominator = max(abs(source), 1.0e-6)
                differences.append(
                    {
                        "source_to_projected_percent": abs(projected - source) / denominator * 100,
                        "projected_to_dss_percent": abs(readback - projected) / max(abs(projected), 1.0e-6) * 100,
                    }
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
            elif max_source_difference > 5:
                status = "warning"
            checks.append(
                ValidationItem(
                    "Value preservation",
                    status,
                    f"Maximum reprojection mean difference {max_source_difference:.3f}% and DSS read-back difference {max_dss_difference:.6f}%",
                    {"hourly_differences": differences},
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
