"""Output file helpers."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

from .models import TimeSeriesPoint, ValidationItem


def write_timeseries_csv(path: Path, points: list[TimeSeriesPoint]) -> Path:
    """Write the time series with units and quality flags."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["time", "value", "units", "quality"])
        writer.writeheader()
        writer.writerows(point.to_dict() for point in points)
    return path


def write_timeseries_parquet(path: Path, points: list[TimeSeriesPoint]) -> Path:
    """Write a typed Parquet copy when PyArrow is available."""

    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(point.to_dict() for point in points)
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
    frame.to_parquet(path, index=False)
    return path


def write_json(path: Path, payload: Any) -> Path:
    """Write readable JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def validation_payload(checks: list[ValidationItem]) -> dict[str, Any]:
    """Build a summary count and detailed check list."""

    counts = {"pass": 0, "warning": 0, "failure": 0}
    for check in checks:
        counts[check.status] += 1
    return {
        "summary": counts,
        "checks": [asdict(check) for check in checks],
    }
