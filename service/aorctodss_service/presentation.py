"""Presentation-ready event animations built without a plotting runtime."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .models import EventWindow, TimeSeriesPoint, VariableMetadata
from .naming import variable_names


CANVAS = (1120, 630)
BACKGROUND = (255, 255, 255)
PANEL = (248, 250, 252)
TEXT = (18, 24, 32)
MUTED = (75, 85, 99)
ACCENT = (0, 111, 143)
MARKER = (239, 68, 68)
AOI_BOUNDARY = (230, 100, 20)
PANEL_BORDER = (203, 213, 225)
CHART_GRID = (218, 226, 235)


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/seguisb.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


FONTS = {
    "title": _font(28, True),
    "subtitle": _font(15),
    "heading": _font(17, True),
    "body": _font(14),
    "small": _font(12),
    "timestamp": _font(18, True),
}


def _clean_label(value: str) -> str:
    return value.replace("_", " ").replace("10m", "10 m").title()


def _safe_values(points: list[TimeSeriesPoint]) -> np.ndarray:
    return np.asarray(
        [point.value if point.value is not None else np.nan for point in points],
        dtype=float,
    )


def _scale_range(metadata: VariableMetadata, values: np.ndarray) -> tuple[float, float]:
    valid = values[np.isfinite(values)]
    if metadata.source_name == "APCP_surface":
        return 0.0, max(float(np.nanmax(valid)) * 1.15, 0.5) if valid.size else 1.0
    if not valid.size:
        return 0.0, 1.0
    low = float(np.nanmin(valid))
    high = float(np.nanmax(valid))
    padding = max((high - low) * 0.12, abs(high) * 0.02, 1.0e-6)
    return low - padding, high + padding


def _colorize(
    values: np.ndarray,
    metadata: VariableMetadata,
    units: str,
    scale: tuple[float, float],
) -> tuple[np.ndarray, np.ndarray]:
    array = np.asarray(values, dtype=float)
    valid = np.isfinite(array)
    finite_array = np.where(valid, array, 0.0)
    rgb = np.full((*array.shape, 3), PANEL, dtype=np.uint8)
    if metadata.source_name == "APCP_surface":
        valid &= array > 0
        # Standard rainfall-like progression: blue, green, yellow, red, magenta.
        breaks = np.asarray([0, 0.1, 1, 2.5, 5, 10, 25, 50], dtype=float)
        if units.lower() == "in":
            breaks /= 25.4
        colors = np.asarray(
            [
                (64, 110, 180),
                (43, 144, 209),
                (35, 190, 110),
                (190, 220, 50),
                (255, 199, 35),
                (242, 90, 45),
                (206, 45, 110),
                (255, 143, 205),
            ],
            dtype=float,
        )
        clipped = np.clip(finite_array, breaks[0], breaks[-1])
        for channel in range(3):
            rgb[..., channel] = np.interp(clipped, breaks, colors[:, channel]).astype(np.uint8)
    else:
        low, high = scale
        normalized = np.clip((finite_array - low) / max(high - low, 1.0e-12), 0, 1)
        stops = np.asarray([0, 0.25, 0.5, 0.75, 1], dtype=float)
        colors = np.asarray(
            [(68, 1, 84), (59, 82, 139), (33, 145, 140), (94, 201, 98), (253, 231, 37)],
            dtype=float,
        )
        for channel in range(3):
            rgb[..., channel] = np.interp(normalized, stops, colors[:, channel]).astype(np.uint8)
    return rgb, valid


class EventGif:
    """Render hourly SHG grids beside the complete selected-event time series."""

    def __init__(
        self,
        path: Path,
        metadata: VariableMetadata,
        units: str,
        points: list[TimeSeriesPoint],
        event: EventWindow,
        cell_size: int,
        dataset_version: str,
        aoi_mask: np.ndarray,
        buffer_m: float = 0,
    ) -> None:
        self.path = path
        self.metadata = metadata
        self.units = units
        self.points = points
        self.values = _safe_values(points)
        self.event = event
        self.cell_size = cell_size
        self.dataset_version = dataset_version
        self.aoi_mask = np.asarray(aoi_mask, dtype=bool)
        self.buffer_m = buffer_m
        self.scale = _scale_range(metadata, self.values)
        self.frames: list[Image.Image] = []

    def add_frame(self, values: np.ndarray, timestamp: datetime, index: int) -> None:
        """Render and retain one optimized palette frame."""

        canvas = Image.new("RGB", CANVAS, BACKGROUND)
        draw = ImageDraw.Draw(canvas)
        variable = _clean_label(variable_names(self.metadata).variable)
        draw.text((38, 26), f"AORC Hourly {variable}", font=FONTS["title"], fill=TEXT)
        draw.text(
            (40, 67),
            "AOI area-weighted average with source-aligned SHG spatial distribution",
            font=FONTS["subtitle"],
            fill=MUTED,
        )
        timestamp_label = timestamp.strftime("%Y-%m-%d %H:%M UTC")
        prefix = "Hour ending" if self.metadata.is_interval else "Valid"
        right_text = f"{prefix} {timestamp_label}"
        right_width = draw.textbbox((0, 0), right_text, font=FONTS["timestamp"])[2]
        draw.text((CANVAS[0] - right_width - 38, 35), right_text, font=FONTS["timestamp"], fill=TEXT)

        map_box = (38, 112, 674, 538)
        chart_box = (700, 112, 1082, 538)
        draw.rounded_rectangle(map_box, radius=12, fill=PANEL, outline=PANEL_BORDER, width=1)
        draw.rounded_rectangle(chart_box, radius=12, fill=PANEL, outline=PANEL_BORDER, width=1)
        grid_label = f"SHG {self.cell_size / 1000:g} km grid"
        if self.buffer_m > 0:
            grid_label += f" | AOI + {self.buffer_m / 1000:g} km buffer"
        draw.text((58, 129), grid_label, font=FONTS["heading"], fill=TEXT)
        draw.text((720, 129), f"AOI Average {variable}", font=FONTS["heading"], fill=TEXT)

        rgb, valid = _colorize(values, self.metadata, self.units, self.scale)
        source = Image.fromarray(rgb)
        source_mask = Image.fromarray((valid * 255).astype(np.uint8))
        available = (596, 320)
        ratio = min(available[0] / source.width, available[1] / source.height)
        size = (max(1, round(source.width * ratio)), max(1, round(source.height * ratio)))
        source = source.resize(size, Image.Resampling.NEAREST)
        source_mask = source_mask.resize(size, Image.Resampling.NEAREST)
        location = (58 + (available[0] - size[0]) // 2, 166 + (available[1] - size[1]) // 2)
        canvas.paste(source, location, source_mask)
        if self.aoi_mask.shape != values.shape:
            raise ValueError("AOI mask dimensions must match each animation grid")
        aoi_mask = Image.fromarray((self.aoi_mask * 255).astype(np.uint8)).resize(
            size,
            Image.Resampling.NEAREST,
        )
        expanded = np.asarray(aoi_mask.filter(ImageFilter.MaxFilter(5)), dtype=np.int16)
        contracted = np.asarray(aoi_mask.filter(ImageFilter.MinFilter(5)), dtype=np.int16)
        edge_mask = Image.fromarray(
            np.where(expanded - contracted > 0, 255, 0).astype(np.uint8)
        )
        outline = Image.new("RGB", size, AOI_BOUNDARY)
        canvas.paste(outline, location, edge_mask)
        draw.line((58, 489, 78, 489), fill=AOI_BOUNDARY, width=3)
        draw.text((84, 480), "AOI boundary", font=FONTS["small"], fill=TEXT)
        self._draw_legend(draw, (80, 499, 632, 512))
        self._draw_chart(draw, index, (750, 176, 1058, 455))

        current = self.values[index] if index < len(self.values) else np.nan
        current_text = f"{current:,.3f} {self.units}" if np.isfinite(current) else "No valid AOI value"
        draw.text((720, 499), f"Current AOI average: {current_text}", font=FONTS["body"], fill=TEXT)
        footer = (
            f"{self.dataset_version}  |  {self.event.hours} hourly grids  |  "
            f"{self.event.start:%Y-%m-%d %H:%M} to {self.event.end:%Y-%m-%d %H:%M} UTC"
        )
        draw.text((40, 578), footer, font=FONTS["small"], fill=MUTED)
        brand = "AORCtoDSS"
        website = "www.hydromohsen.com"
        brand_width = draw.textbbox((0, 0), brand, font=FONTS["heading"])[2]
        website_width = draw.textbbox((0, 0), website, font=FONTS["small"])[2]
        draw.text((1080 - brand_width, 568), brand, font=FONTS["heading"], fill=TEXT)
        draw.text((1080 - website_width, 594), website, font=FONTS["small"], fill=TEXT)
        self.frames.append(
            canvas.quantize(colors=192, method=Image.Quantize.FASTOCTREE)
        )

    def _draw_legend(self, draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
        x0, y0, x1, y1 = box
        steps = max(x1 - x0, 1)
        if self.metadata.source_name == "APCP_surface":
            legend_range = (0.0, 2.0 if self.units.lower() == "in" else 50.0)
        else:
            legend_range = self.scale
        sample = np.linspace(legend_range[0], legend_range[1], steps).reshape(1, -1)
        rgb, _ = _colorize(sample, self.metadata, self.units, self.scale)
        legend = Image.fromarray(rgb).resize((steps, y1 - y0), Image.Resampling.BILINEAR)
        draw._image.paste(legend, (x0, y0))
        draw.rectangle(box, outline=(110, 130, 151), width=1)
        if self.metadata.source_name == "APCP_surface":
            labels = ("Trace", f"50 {self.units}" if self.units.lower() != "in" else "2 in+")
        else:
            labels = (f"{self.scale[0]:.2f}", f"{self.scale[1]:.2f} {self.units}")
        draw.text((x0, y1 + 4), labels[0], font=FONTS["small"], fill=MUTED)
        width = draw.textbbox((0, 0), labels[1], font=FONTS["small"])[2]
        draw.text((x1 - width, y1 + 4), labels[1], font=FONTS["small"], fill=MUTED)

    def _draw_chart(
        self,
        draw: ImageDraw.ImageDraw,
        active: int,
        box: tuple[int, int, int, int],
    ) -> None:
        x0, y0, x1, y1 = box
        low, high = self.scale
        for fraction in (0, 0.25, 0.5, 0.75, 1):
            y = round(y1 - fraction * (y1 - y0))
            draw.line((x0, y, x1, y), fill=CHART_GRID, width=1)
            label = f"{low + fraction * (high - low):.2f}"
            label_width = draw.textbbox((0, 0), label, font=FONTS["small"])[2]
            draw.text((x0 - label_width - 7, y - 8), label, font=FONTS["small"], fill=MUTED)
        count = max(len(self.values), 1)

        def point(index: int, value: float) -> tuple[int, int]:
            x = x0 if count == 1 else round(x0 + index / (count - 1) * (x1 - x0))
            y = round(y1 - np.clip((value - low) / max(high - low, 1.0e-12), 0, 1) * (y1 - y0))
            return x, y

        segments: list[list[tuple[int, int]]] = []
        segment: list[tuple[int, int]] = []
        for i, value in enumerate(self.values):
            if np.isfinite(value):
                segment.append(point(i, float(value)))
            elif segment:
                segments.append(segment)
                segment = []
        if segment:
            segments.append(segment)
        for line in segments:
            if len(line) > 1:
                draw.line(line, fill=ACCENT, width=3, joint="curve")
            elif line:
                draw.ellipse((line[0][0] - 2, line[0][1] - 2, line[0][0] + 2, line[0][1] + 2), fill=ACCENT)
        if active < len(self.values) and np.isfinite(self.values[active]):
            x, y = point(active, float(self.values[active]))
            draw.line((x, y0, x, y1), fill=(239, 68, 68), width=2)
            draw.ellipse((x - 8, y - 8, x + 8, y + 8), fill=MARKER, outline=(255, 255, 255), width=2)
        draw.line((x0, y1, x1, y1), fill=(110, 130, 151), width=1)
        draw.text((x0, y1 + 8), "Event start", font=FONTS["small"], fill=MUTED)
        end_label = "Event end"
        width = draw.textbbox((0, 0), end_label, font=FONTS["small"])[2]
        draw.text((x1 - width, y1 + 8), end_label, font=FONTS["small"], fill=MUTED)

    def save(self) -> Path:
        """Write the animated GIF with a slightly longer final hold."""

        if not self.frames:
            raise ValueError("Cannot create an event animation without frames")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        durations = [550] * len(self.frames)
        durations[-1] = 1600
        self.frames[0].save(
            self.path,
            save_all=True,
            append_images=self.frames[1:],
            duration=durations,
            loop=0,
            optimize=False,
            disposal=2,
        )
        return self.path
