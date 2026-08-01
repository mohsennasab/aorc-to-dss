"""On-demand AORC frames for GeoLibre's native Time Slider."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock, Semaphore, Thread
from typing import Any

import numpy as np
from dask.callbacks import Callback

from .aorc.catalog import AORCCatalog
from .aorc.subset import open_aorc_window
from .events.selection import custom_event
from .spatial.cog import write_wgs84_animation_cog
from .spatial.geometry import GeometrySummary, prepare_geometry
from .units import convert_values, output_units


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _frame_key(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d-%H")


@dataclass
class AnimationDefinition:
    """Validated event information and its lazy frame cache."""

    id: str
    area: GeometrySummary
    variable: str
    source_units: str
    calculation_units: str
    display_units: str
    missing_value: float
    aggregation: str
    times: list[datetime]
    directory: Path
    locks: dict[str, Lock] = field(default_factory=dict)
    locks_guard: Lock = field(default_factory=Lock)
    status_lock: Lock = field(default_factory=Lock)
    preload_state: str = "not_started"
    preload_progress: float = 0.0
    preload_completed: int = 0
    preload_message: str = "Ready to preload"
    preload_error: str | None = None
    preload_thread: Thread | None = None

    def lock_for(self, key: str) -> Lock:
        with self.locks_guard:
            return self.locks.setdefault(key, Lock())


class AnimationManager:
    """Register animations and materialize only frames requested by the dock."""

    def __init__(self, catalog: AORCCatalog, cache_dir: Path) -> None:
        self.catalog = catalog
        self.cache_dir = cache_dir / "animations"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.animations: dict[str, AnimationDefinition] = {}
        self.lock = Lock()
        self.download_slots = Semaphore(2)

    def register(self, payload: dict[str, Any]) -> dict[str, Any]:
        area = prepare_geometry(
            payload["geometry"],
            payload.get("source_crs", "EPSG:4326"),
            bool(payload.get("dissolve", True)),
        )
        event = custom_event(payload["event_start"], payload["event_end"])
        metadata = self.catalog.variable(payload["variable"])
        units = output_units(metadata, payload.get("unit_system", "metric"))
        offset = 1 if metadata.is_interval else 0
        times = [
            event.start + timedelta(hours=index + offset)
            for index in range(event.hours)
        ]
        if not times:
            raise ValueError("The selected event has no hourly animation frames")
        available_start = datetime.fromisoformat(metadata.start.replace("Z", "+00:00"))
        available_end = datetime.fromisoformat(metadata.end.replace("Z", "+00:00"))
        if times[0] < available_start or times[-1] > available_end:
            raise ValueError("The selected event is outside the available AORC archive")

        animation_id = uuid.uuid4().hex
        directory = self.cache_dir / animation_id
        directory.mkdir(parents=True, exist_ok=True)
        definition = AnimationDefinition(
            id=animation_id,
            area=area,
            variable=metadata.source_name,
            source_units=metadata.units,
            calculation_units=units.calculation,
            display_units=units.display,
            missing_value=metadata.missing_value,
            aggregation=metadata.aggregation,
            times=times,
            directory=directory,
        )
        with self.lock:
            self.animations[animation_id] = definition

        selected: list[float] = []
        for value in payload.get("selected_values", []):
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            if np.isfinite(numeric):
                selected.append(numeric)
        positive = [value for value in selected if value > 0]
        if metadata.source_name == "APCP_surface":
            minimum_max = 0.5 if units.display == "in" else 12.5
            scale_max = max(minimum_max, max(positive, default=0) * 5)
            # Radar-style blue/green/yellow/red ramp ending in magenta/pink.
            colormap = "gist_ncar"
        else:
            scale_min = min(selected, default=0)
            scale_max = max(selected, default=1)
            if scale_max <= scale_min:
                scale_max = scale_min + 1
            colormap = "viridis"
        return {
            "id": animation_id,
            "times": [_iso(value) for value in times],
            "url_template": (
                f"/animations/{animation_id}/"
                "{date:YYYY-MM-DD-HH}.tif"
            ),
            "bounds": list(area.geometry.bounds),
            "units": units.display,
            "colormap": colormap,
            "rescale": [
                0 if metadata.source_name == "APCP_surface" else float(scale_min),
                float(scale_max),
            ],
            "nodata": -9999,
        }

    def get(self, animation_id: str) -> AnimationDefinition | None:
        with self.lock:
            return self.animations.get(animation_id)

    def status(self, animation_id: str) -> dict[str, Any]:
        definition = self.get(animation_id)
        if definition is None:
            raise KeyError("Animation not found")
        with definition.status_lock:
            return {
                "id": animation_id,
                "state": definition.preload_state,
                "progress": definition.preload_progress,
                "completed": definition.preload_completed,
                "total": len(definition.times),
                "message": definition.preload_message,
                "error": definition.preload_error,
            }

    def start_preload(self, animation_id: str) -> dict[str, Any]:
        definition = self.get(animation_id)
        if definition is None:
            raise KeyError("Animation not found")
        with definition.status_lock:
            if definition.preload_state in {"queued", "running", "complete"}:
                thread = None
            else:
                definition.preload_state = "queued"
                definition.preload_progress = 0.0
                definition.preload_completed = 0
                definition.preload_message = "Queued animation download"
                definition.preload_error = None
                thread = Thread(
                    target=self._preload,
                    args=(definition,),
                    name=f"aorctodss-animation-{animation_id[:8]}",
                    daemon=True,
                )
                definition.preload_thread = thread
        if thread is not None:
            thread.start()
        return self.status(animation_id)

    def _set_preload_status(
        self,
        definition: AnimationDefinition,
        *,
        state: str | None = None,
        progress: float | None = None,
        completed: int | None = None,
        message: str | None = None,
        error: str | None = None,
    ) -> None:
        with definition.status_lock:
            if state is not None:
                definition.preload_state = state
            if progress is not None:
                definition.preload_progress = max(0.0, min(1.0, progress))
            if completed is not None:
                definition.preload_completed = completed
            if message is not None:
                definition.preload_message = message
            definition.preload_error = error

    def _preload(self, definition: AnimationDefinition) -> None:
        try:
            self._set_preload_status(
                definition,
                state="running",
                progress=0.01,
                message="Opening the selected AORC event window",
            )
            data = open_aorc_window(
                self.catalog,
                definition.variable,
                definition.times[0],
                definition.times[-1] + timedelta(hours=1),
                definition.area.geometry.bounds,
                progress=lambda value, message: self._set_preload_status(
                    definition,
                    progress=0.01 + value * 0.04,
                    message=message,
                ),
            )
            if data.sizes.get("time") != len(definition.times):
                raise ValueError(
                    f"Expected {len(definition.times)} AORC frames and "
                    f"found {data.sizes.get('time', 0)}"
                )

            task_total = 1
            task_done = 0

            def on_start(graph: Any) -> None:
                nonlocal task_total
                task_total = max(len(graph), 1)
                self._set_preload_status(
                    definition,
                    progress=0.05,
                    message=f"Downloading AORC chunks (0 of {task_total})",
                )

            def on_task(*_args: Any) -> None:
                nonlocal task_done
                task_done += 1
                self._set_preload_status(
                    definition,
                    progress=0.05 + 0.60 * task_done / task_total,
                    message=f"Downloading AORC chunks ({task_done} of {task_total})",
                )

            with self.download_slots, Callback(start=on_start, posttask=on_task):
                data.load()

            latitudes = np.asarray(data.latitude.values)
            longitudes = np.asarray(data.longitude.values)
            total = len(definition.times)
            for index, timestamp in enumerate(definition.times):
                key = _frame_key(timestamp)
                target = definition.directory / f"{key}.tif"
                with definition.lock_for(key):
                    if not target.is_file():
                        self._write_frame(
                            definition,
                            target,
                            np.asarray(data.isel(time=index).values),
                            latitudes,
                            longitudes,
                        )
                completed = index + 1
                self._set_preload_status(
                    definition,
                    progress=0.65 + 0.35 * completed / total,
                    completed=completed,
                    message=f"Prepared animation frame {completed} of {total}",
                )
            self._set_preload_status(
                definition,
                state="complete",
                progress=1.0,
                completed=total,
                message=f"All {total} animation frames are ready",
            )
        except Exception as exc:
            self._set_preload_status(
                definition,
                state="failed",
                message="Animation preload failed",
                error=str(exc),
            )

    def _write_frame(
        self,
        definition: AnimationDefinition,
        target: Path,
        values: np.ndarray,
        latitudes: np.ndarray,
        longitudes: np.ndarray,
    ) -> None:
        source = np.asarray(values, dtype=float)
        source[(~np.isfinite(source)) | (source == definition.missing_value)] = np.nan
        converted = convert_values(
            source,
            definition.source_units,
            definition.calculation_units,
        )
        partial = target.with_suffix(".partial.tif")
        partial.unlink(missing_ok=True)
        write_wgs84_animation_cog(
            partial,
            converted,
            latitudes,
            longitudes,
            definition.area.geometry,
            definition.display_units,
            transparent_zero=definition.variable == "APCP_surface",
        )
        partial.replace(target)

    def frame(self, animation_id: str, key: str) -> Path:
        definition = self.get(animation_id)
        if definition is None:
            raise KeyError("Animation not found")
        indexed = {_frame_key(value): value for value in definition.times}
        timestamp = indexed.get(key)
        if timestamp is None:
            raise KeyError("Animation frame is outside the selected event")
        target = definition.directory / f"{key}.tif"
        if target.is_file():
            return target
        with definition.lock_for(key):
            if target.is_file():
                return target
            with self.download_slots:
                data = open_aorc_window(
                    self.catalog,
                    definition.variable,
                    timestamp,
                    timestamp + timedelta(hours=1),
                    definition.area.geometry.bounds,
                )
                self._write_frame(
                    definition,
                    target,
                    np.asarray(data.isel(time=0).values),
                    np.asarray(data.latitude.values),
                    np.asarray(data.longitude.values),
                )
        return target
