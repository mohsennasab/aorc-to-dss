"""Loopback HTTP API used by the GeoLibre plugin."""

from __future__ import annotations

import base64
import binascii
import json
import mimetypes
import os
import re
import subprocess
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .animation import AnimationManager
from .aorc.catalog import AORCCatalog
from .configuration import ServiceConfiguration
from .dss.adapter import HecDssAdapter
from .jobs import JobManager
from .pipeline import estimate_export
from .spatial.geometry import prepare_geometry

ALLOWED_ORIGINS = {
    "https://web.geolibre.app",
    "http://localhost",
    "https://localhost",
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
}


def _origin_allowed(origin: str) -> bool:
    if origin in ALLOWED_ORIGINS:
        return True
    return bool(re.fullmatch(r"https?://(localhost|127\.0\.0\.1)(:\d+)?", origin))


class AORCRequestHandler(BaseHTTPRequestHandler):
    """JSON and range-file routes for the local service."""

    manager: JobManager
    animation_manager: AnimationManager
    catalog: AORCCatalog
    server_version = "AORCtoDSS/0.1.6"
    max_body = 12 * 1024 * 1024

    def log_message(self, format_string: str, *args: Any) -> None:
        return

    def _cors(self) -> None:
        origin = self.headers.get("Origin", "")
        if _origin_allowed(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, POST, DELETE, OPTIONS")

    def _json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _payload(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > self.max_body:
            raise ValueError("Request body is empty or too large")
        body = self.rfile.read(length)
        value = json.loads(body)
        if not isinstance(value, dict):
            raise ValueError("Request body must be a JSON object")
        return value

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            self._json(
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "version": self.server_version.split("/")[-1],
                    "dss": HecDssAdapter.dependency_status(),
                },
            )
            return
        if path == "/metadata/variables":
            try:
                values = [variable.to_dict() for variable in self.catalog.variables()]
                self._json(HTTPStatus.OK, {"variables": values, "years": self.catalog.years()})
            except Exception as exc:
                self._json(HTTPStatus.BAD_GATEWAY, {"error": str(exc)})
            return
        animation_match = re.fullmatch(
            r"/animations/([a-f0-9]+)/(\d{4}-\d{2}-\d{2}-\d{2})\.tif",
            path,
        )
        if animation_match:
            try:
                target = self.animation_manager.frame(
                    animation_match.group(1),
                    animation_match.group(2),
                )
            except KeyError as exc:
                self._json(HTTPStatus.NOT_FOUND, {"error": str(exc.args[0])})
            except Exception as exc:
                self._json(
                    HTTPStatus.BAD_GATEWAY,
                    {"error": f"Animation frame could not be created: {exc}"},
                )
            else:
                self._send_file(target, cache_control="public, max-age=31536000, immutable")
            return
        animation_status_match = re.fullmatch(r"/animations/([a-f0-9]+)", path)
        if animation_status_match:
            try:
                result = self.animation_manager.status(animation_status_match.group(1))
            except KeyError as exc:
                self._json(HTTPStatus.NOT_FOUND, {"error": str(exc.args[0])})
            else:
                self._json(HTTPStatus.OK, result)
            return
        match = re.fullmatch(r"/jobs/([a-f0-9]+)", path)
        if match:
            job = self.manager.get(match.group(1))
            if job is None:
                self._json(HTTPStatus.NOT_FOUND, {"error": "Job not found"})
            else:
                self._json(HTTPStatus.OK, job.snapshot())
            return
        file_match = re.fullmatch(r"/jobs/([a-f0-9]+)/files/(.+)", path)
        if file_match:
            self._send_job_file(file_match.group(1), unquote(file_match.group(2)))
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "Route not found"})

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            payload = self._payload()
            if path == "/geometry/validate":
                result = prepare_geometry(
                    payload["geometry"],
                    payload.get("source_crs", "EPSG:4326"),
                    bool(payload.get("dissolve", True)),
                )
                self._json(HTTPStatus.OK, result.to_dict())
                return
            if path == "/estimate":
                self._json(HTTPStatus.OK, estimate_export(payload))
                return
            if path == "/jobs/timeseries":
                job = self.manager.submit_timeseries(payload)
                self._json(HTTPStatus.ACCEPTED, job.snapshot())
                return
            if path == "/jobs/export":
                job = self.manager.submit_export(payload)
                self._json(HTTPStatus.ACCEPTED, job.snapshot())
                return
            if path == "/animations":
                result = self.animation_manager.register(payload)
                self._json(HTTPStatus.CREATED, result)
                return
            animation_preload_match = re.fullmatch(
                r"/animations/([a-f0-9]+)/preload",
                path,
            )
            if animation_preload_match:
                result = self.animation_manager.start_preload(
                    animation_preload_match.group(1)
                )
                self._json(HTTPStatus.ACCEPTED, result)
                return
            if path == "/dialogs/folder":
                self._json(HTTPStatus.OK, {"path": self._choose_directory()})
                return
            if path == "/dialogs/save-png":
                self._json(HTTPStatus.OK, {"path": self._save_png(payload)})
                return
            if path == "/open-folder":
                folder = Path(payload["path"]).expanduser().resolve()
                if not folder.is_dir():
                    raise ValueError("Output folder does not exist")
                self._open_directory(folder)
                self._json(HTTPStatus.OK, {"opened": True})
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "Route not found"})
        except KeyError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": f"Missing field {exc.args[0]}"})
        except Exception as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    @staticmethod
    def _choose_directory() -> str:
        """Open the platform folder picker from the local desktop service."""

        try:
            import tkinter
            from tkinter import filedialog

            root = tkinter.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            try:
                return filedialog.askdirectory(title="Choose AORCtoDSS output folder")
            finally:
                root.destroy()
        except Exception as exc:
            raise ValueError(f"The folder picker could not be opened: {exc}") from exc

    @staticmethod
    def _save_png(payload: dict[str, Any]) -> str:
        """Prompt for a PNG destination and save a validated canvas image."""

        data_url = str(payload.get("data_url", ""))
        prefix = "data:image/png;base64,"
        if not data_url.startswith(prefix):
            raise ValueError("The exported chart is not a PNG image")
        try:
            image = base64.b64decode(data_url[len(prefix):], validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("The exported PNG data are invalid") from exc
        if not image.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("The exported chart does not contain a valid PNG signature")

        suggested = Path(str(payload.get("suggested_name", "aorc-timeseries.png"))).name
        if not suggested.lower().endswith(".png"):
            suggested += ".png"
        try:
            import tkinter
            from tkinter import filedialog

            root = tkinter.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            try:
                selected = filedialog.asksaveasfilename(
                    title="Save AORC time-series image",
                    initialfile=suggested,
                    defaultextension=".png",
                    filetypes=[("PNG image", "*.png")],
                )
            finally:
                root.destroy()
        except Exception as exc:
            raise ValueError(f"The image save dialog could not be opened: {exc}") from exc
        if not selected:
            return ""
        destination = Path(selected).expanduser().resolve()
        destination.write_bytes(image)
        return str(destination)

    @staticmethod
    def _open_directory(path: Path) -> None:
        """Open an existing output folder with the operating system."""

        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path
        match = re.fullmatch(r"/jobs/([a-f0-9]+)", path)
        if not match:
            self._json(HTTPStatus.NOT_FOUND, {"error": "Route not found"})
            return
        cancelled = self.manager.cancel(match.group(1))
        self._json(
            HTTPStatus.ACCEPTED if cancelled else HTTPStatus.CONFLICT,
            {"cancelled": cancelled},
        )

    def _send_job_file(self, job_id: str, relative: str) -> None:
        job = self.manager.get(job_id)
        if job is None or job.output_dir is None:
            self._json(HTTPStatus.NOT_FOUND, {"error": "Job output not found"})
            return
        root = job.output_dir.resolve()
        target = (root / relative).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            self._json(HTTPStatus.FORBIDDEN, {"error": "Invalid output path"})
            return
        if not target.is_file():
            self._json(HTTPStatus.NOT_FOUND, {"error": "Output file not found"})
            return
        self._send_file(target)

    def _send_file(self, target: Path, cache_control: str | None = None) -> None:
        """Send one approved file with HTTP byte-range support."""

        size = target.stat().st_size
        start = 0
        end = size - 1
        status = HTTPStatus.OK
        range_header = self.headers.get("Range", "")
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header)
        if match:
            if match.group(1):
                start = int(match.group(1))
            if match.group(2):
                end = min(int(match.group(2)), end)
            if start > end or start >= size:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self._cors()
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            status = HTTPStatus.PARTIAL_CONTENT
        length = end - start + 1
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", content_type)
        self.send_header("Accept-Ranges", "bytes")
        if cache_control:
            self.send_header("Cache-Control", cache_control)
        self.send_header("Content-Length", str(length))
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if self.command == "HEAD":
            return
        with target.open("rb") as stream:
            stream.seek(start)
            remaining = length
            while remaining:
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)


def create_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    configuration: ServiceConfiguration | None = None,
) -> ThreadingHTTPServer:
    """Create a configured loopback server."""

    config = configuration or ServiceConfiguration.load()
    config.ensure_directories()
    catalog = AORCCatalog()
    manager = JobManager(
        max_workers=2,
        catalog=catalog,
        cache_dir=Path(config.cache),
    )
    animation_manager = AnimationManager(catalog, Path(config.cache))
    handler = type(
        "ConfiguredAORCRequestHandler",
        (AORCRequestHandler,),
        {
            "manager": manager,
            "animation_manager": animation_manager,
            "catalog": catalog,
        },
    )
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    """Run until interrupted."""

    server = create_server(host, port)
    try:
        server.serve_forever()
    finally:
        server.RequestHandlerClass.manager.shutdown()
        server.server_close()
