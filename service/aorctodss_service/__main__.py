"""Command line entry point."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from aorctodss_service.server import serve


def _self_test() -> None:
    """Exercise the packaged native DSS library with a small grid round trip."""

    import numpy as np
    import geopandas as gpd
    from shapely.geometry import box

    from aorctodss_service.dss.adapter import HecDssAdapter
    from aorctodss_service.dss.pathname import DSSPathname
    from aorctodss_service.spatial.shg import build_shg_grid

    grid = build_shg_grid(box(-90, 35, -89.98, 35.02), 2000)
    pathname = str(
        DSSPathname.grid(
            "SELFTEST",
            "PRECIP",
            datetime(2020, 1, 1, tzinfo=timezone.utc),
            datetime(2020, 1, 1, 1, tzinfo=timezone.utc),
            2000,
        )
    )
    values = np.arange(grid.width * grid.height, dtype=np.float32).reshape(
        grid.height,
        grid.width,
    )
    with TemporaryDirectory(prefix="aorctodss-self-test-") as directory:
        dss_path = Path(directory) / "roundtrip.dss"
        with HecDssAdapter(dss_path) as adapter:
            adapter.write_grid_record(pathname, values, grid, "MM", 1)
            record = adapter.read_grid_record(pathname)
            if not np.allclose(np.flipud(record.data), values):
                raise RuntimeError("HEC-DSS grid readback did not match the source")
            problems = adapter.validate_grid_record(pathname, grid, "MM")
            if problems:
                raise RuntimeError(", ".join(problems))
        gpkg_path = Path(directory) / "study_area.gpkg"
        gpd.GeoDataFrame(
            [{"name": "SELFTEST"}],
            geometry=[box(-90, 35, -89.98, 35.02)],
            crs="EPSG:4326",
        ).to_file(gpkg_path, layer="study_area", driver="GPKG", engine="pyogrio")
        if not gpkg_path.is_file():
            raise RuntimeError("GeoPackage write check did not create an output file")


def main() -> None:
    """Start the local processing service."""

    parser = argparse.ArgumentParser(description="AORCtoDSS local processing service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        _self_test()
        return
    serve(args.host, args.port)


if __name__ == "__main__":
    main()
