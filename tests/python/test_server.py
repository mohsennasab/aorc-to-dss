"""Local desktop service helpers."""

from __future__ import annotations

import base64
import json
import sys
import urllib.request
from http.server import ThreadingHTTPServer
from threading import Thread
from types import ModuleType, SimpleNamespace

from aorctodss_service.server import AORCRequestHandler


def test_save_png_uses_selected_destination(tmp_path, monkeypatch) -> None:
    destination = tmp_path / "selected-chart.png"

    class Root:
        def withdraw(self) -> None:
            pass

        def attributes(self, *_args) -> None:
            pass

        def destroy(self) -> None:
            pass

    tkinter = ModuleType("tkinter")
    tkinter.Tk = Root
    tkinter.filedialog = SimpleNamespace(
        asksaveasfilename=lambda **_kwargs: str(destination)
    )
    monkeypatch.setitem(sys.modules, "tkinter", tkinter)

    image = b"\x89PNG\r\n\x1a\nsynthetic"
    result = AORCRequestHandler._save_png(
        {
            "data_url": "data:image/png;base64," + base64.b64encode(image).decode(),
            "suggested_name": "chart.png",
        }
    )

    assert result == str(destination.resolve())
    assert destination.read_bytes() == image


def test_animation_cog_route_supports_browser_byte_ranges(tmp_path) -> None:
    frame = tmp_path / "frame.tif"
    frame.write_bytes(b"0123456789")

    class AnimationManager:
        @staticmethod
        def frame(animation_id: str, key: str):
            assert animation_id == "a" * 32
            assert key == "2020-01-01-01"
            return frame

        @staticmethod
        def start_preload(animation_id: str):
            return {
                "id": animation_id,
                "state": "queued",
                "progress": 0,
                "completed": 0,
                "total": 2,
                "message": "Queued",
                "error": None,
            }

        @staticmethod
        def status(animation_id: str):
            return {
                "id": animation_id,
                "state": "running",
                "progress": 0.5,
                "completed": 1,
                "total": 2,
                "message": "Prepared frame 1 of 2",
                "error": None,
            }

    handler = type(
        "TestHandler",
        (AORCRequestHandler,),
        {"animation_manager": AnimationManager()},
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/animations/"
            f"{'a' * 32}/2020-01-01-01.tif",
            headers={
                "Range": "bytes=2-5",
                "Origin": "tauri://localhost",
            },
        )
        with urllib.request.urlopen(request) as response:
            assert response.status == 206
            assert response.read() == b"2345"
            assert response.headers["Content-Range"] == "bytes 2-5/10"
            assert response.headers["Access-Control-Allow-Origin"] == "tauri://localhost"
            assert response.headers["Cache-Control"] == "public, max-age=31536000, immutable"
        preload_request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/animations/{'a' * 32}/preload",
            data=b"{}",
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(preload_request) as response:
            assert response.status == 202
            assert json.load(response)["state"] == "queued"
        with urllib.request.urlopen(
            f"http://127.0.0.1:{server.server_port}/animations/{'a' * 32}"
        ) as response:
            status = json.load(response)
            assert status["progress"] == 0.5
            assert status["completed"] == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
