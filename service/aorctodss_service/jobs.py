"""Threaded job manager with progress and cooperative cancellation."""

from __future__ import annotations

import traceback
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Lock
from typing import Any, Callable

from .aorc.catalog import AORCCatalog
from .aorc.timeseries import watershed_timeseries
from .events.selection import parse_utc
from .exceptions import AORCToDSSError, CancelledError
from .pipeline import run_export
from .spatial.geometry import prepare_geometry
from .units import convert_points, output_units


@dataclass
class Job:
    """Mutable state for one background operation."""

    id: str
    kind: str
    created: str
    state: str = "queued"
    progress: float = 0
    message: str = "Queued"
    result: Any = None
    error: dict[str, Any] | None = None
    output_dir: Path | None = None
    cancel: Event = field(default_factory=Event)
    future: Future[Any] | None = None
    lock: Lock = field(default_factory=Lock)

    def update(self, value: float, message: str) -> None:
        """Set bounded progress and a concise message."""

        with self.lock:
            self.progress = max(0, min(1, value))
            self.message = message

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-ready state copy."""

        with self.lock:
            result = self.result
            if hasattr(result, "to_dict"):
                result = result.to_dict()
            return {
                "id": self.id,
                "kind": self.kind,
                "created": self.created,
                "state": self.state,
                "progress": self.progress,
                "message": self.message,
                "result": result,
                "error": self.error,
            }


class JobManager:
    """Run processing jobs on a bounded thread pool."""

    def __init__(
        self,
        max_workers: int = 2,
        catalog: AORCCatalog | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        self.catalog = catalog or AORCCatalog()
        self.cache_dir = cache_dir
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="aorctodss")
        self.jobs: dict[str, Job] = {}
        self.lock = Lock()

    def _new(self, kind: str) -> Job:
        job = Job(
            id=uuid.uuid4().hex,
            kind=kind,
            created=datetime.now(timezone.utc).isoformat(),
        )
        with self.lock:
            self.jobs[job.id] = job
        return job

    def submit_timeseries(self, payload: dict[str, Any]) -> Job:
        """Queue a watershed-average time series."""

        job = self._new("timeseries")

        def work() -> dict[str, Any]:
            summary = prepare_geometry(
                payload["geometry"],
                payload.get("source_crs", "EPSG:4326"),
                bool(payload.get("dissolve", True)),
            )
            points = watershed_timeseries(
                self.catalog,
                summary.geometry,
                payload["variable"],
                parse_utc(payload["start"]),
                parse_utc(payload["end"]),
                "area-weighted",
                (
                    Path(payload["cache_dir"]) / "weights"
                    if payload.get("cache_dir")
                    else self.cache_dir / "weights"
                    if self.cache_dir
                    else None
                ),
                job.cancel,
                job.update,
            )
            metadata = self.catalog.variable(payload["variable"])
            points = convert_points(
                points,
                metadata.units,
                output_units(metadata, payload.get("unit_system", "metric")),
            )
            return {
                "area": summary.to_dict(),
                "points": [point.to_dict() for point in points],
            }

        job.future = self.executor.submit(self._run, job, work)
        return job

    def submit_export(self, payload: dict[str, Any]) -> Job:
        """Queue the complete SHG and DSS export."""

        job = self._new("export")
        job.output_dir = Path(payload["output_dir"]).expanduser().resolve()
        job.future = self.executor.submit(
            self._run,
            job,
            lambda: run_export(payload, job.cancel, job.update, self.catalog),
        )
        return job

    @staticmethod
    def _run(job: Job, operation: Callable[[], Any]) -> None:
        with job.lock:
            job.state = "running"
            job.message = "Starting"
        try:
            result = operation()
            if job.cancel.is_set():
                raise CancelledError("Operation cancelled")
            with job.lock:
                job.result = result
                job.progress = 1
                job.state = "complete"
                job.message = "Complete"
        except CancelledError as exc:
            with job.lock:
                job.state = "cancelled"
                job.message = str(exc)
                job.error = {"code": exc.code, "message": str(exc), "retryable": False}
        except AORCToDSSError as exc:
            with job.lock:
                job.state = "failed"
                job.message = str(exc)
                job.error = {
                    "code": exc.code,
                    "message": str(exc),
                    "guidance": exc.guidance,
                    "retryable": exc.retryable,
                }
        except Exception as exc:
            with job.lock:
                job.state = "failed"
                job.message = str(exc)
                job.error = {
                    "code": "unexpected_error",
                    "message": str(exc),
                    "guidance": "Review the processing log and report the traceback if the problem repeats.",
                    "retryable": False,
                    "traceback": traceback.format_exc(),
                }

    def get(self, job_id: str) -> Job | None:
        """Return one job."""

        with self.lock:
            return self.jobs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        """Signal cancellation for a queued or running job."""

        job = self.get(job_id)
        if job is None or job.state not in {"queued", "running"}:
            return False
        job.cancel.set()
        job.update(job.progress, "Cancelling")
        return True

    def shutdown(self) -> None:
        """Stop accepting jobs and signal active work."""

        with self.lock:
            for job in self.jobs.values():
                if job.state in {"queued", "running"}:
                    job.cancel.set()
        self.executor.shutdown(wait=False, cancel_futures=True)
