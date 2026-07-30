"""Small adapter around the official HEC-DSS Python package."""

from __future__ import annotations

from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

import numpy as np

from ..exceptions import DSSDependencyError, DSSWriteError
from ..models import GridDefinition

GRID_NULL_VALUE = np.float32(-3.4028234663852886e38)


class HecDssAdapter(AbstractContextManager["HecDssAdapter"]):
    """Own a DSS handle and expose grid-specific operations."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._dss: Any = None

    @staticmethod
    def dependency_status() -> dict[str, str | bool]:
        """Report whether the official Python wrapper and native library load."""

        try:
            import hecdss
            from hecdss.native import _Native

            _Native()

            return {
                "available": True,
                "package": str(Path(hecdss.__file__).resolve()),
                "message": "Official hecdss package is ready",
            }
        except Exception as exc:
            return {
                "available": False,
                "package": "",
                "message": str(exc),
            }

    def open_dss_file(self) -> "HecDssAdapter":
        """Open or create the configured DSS file."""

        try:
            from hecdss import HecDss
        except Exception as exc:
            raise DSSDependencyError(
                "The HEC-DSS component could not be loaded",
                "Reinstall the AORCtoDSS desktop package. It includes the native library.",
            ) from exc
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._dss = HecDss(str(self.path))
        except Exception as exc:
            raise DSSWriteError(
                f"Could not open {self.path}",
                "Check folder permissions and confirm that another program is not locking the file.",
            ) from exc
        return self

    def create_dss_file(self) -> "HecDssAdapter":
        """Create a new file or open an existing file."""

        return self.open_dss_file()

    def close_dss_file(self) -> None:
        """Close the native handle."""

        if self._dss is not None:
            try:
                self._dss.close()
            finally:
                self._dss = None

    def __enter__(self) -> "HecDssAdapter":
        return self.open_dss_file()

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close_dss_file()

    def _require_open(self) -> Any:
        if self._dss is None:
            raise DSSWriteError("The DSS file is not open")
        return self._dss

    def list_pathnames(self) -> list[str]:
        """List all complete pathnames in the file."""

        catalog = self._require_open().get_catalog()
        values = getattr(catalog, "uncondensed_paths", None)
        if values is None:
            values = getattr(catalog, "rawCatalog", list(catalog))
        return [str(path) for path in values]

    def write_grid_record(
        self,
        pathname: str,
        values_north_up: np.ndarray,
        grid: GridDefinition,
        units: str,
        data_type: int,
        overwrite: bool = False,
    ) -> None:
        """Write one SHG grid and keep rows in the DSS lower-left convention."""

        dss = self._require_open()
        if pathname in self.list_pathnames() and not overwrite:
            raise DSSWriteError(
                f"DSS pathname already exists: {pathname}",
                "Choose overwrite or change the pathname settings.",
            )
        try:
            from hecdss.gridded_data import GriddedData

            values = np.asarray(values_north_up, dtype=np.float32)
            south_up = np.flipud(values)
            record = GriddedData.create(
                path=pathname,
                type=420,
                dataType=data_type,
                lowerLeftCellX=grid.lower_left_cell_x,
                lowerLeftCellY=grid.lower_left_cell_y,
                srsDefinitionType=0,
                timeZoneRawOffset=0,
                isInterval=1 if data_type in (0, 1) else 0,
                isTimeStamped=1,
                dataUnits=units,
                dataSource="AORC",
                srsName="WKT",
                srsDefinition=grid.crs_wkt,
                timeZoneID="UTC",
                cellSize=float(grid.cell_size),
                xCoordOfGridCellZero=0,
                yCoordOfGridCellZero=0,
                nullValue=float(GRID_NULL_VALUE),
                data=south_up,
            )
            # Let GriddedData calculate its min/mean/null metadata from NaNs,
            # then replace them with HEC's explicit grid-null sentinel before
            # the native write.
            record.data = np.where(
                np.isfinite(record.data),
                record.data,
                GRID_NULL_VALUE,
            ).astype(np.float32)
            status = dss.put(record)
        except DSSWriteError:
            raise
        except Exception as exc:
            raise DSSWriteError(
                f"Could not write DSS grid {pathname}",
                "Review the processing log for native HEC-DSS details.",
            ) from exc
        if status != 0:
            raise DSSWriteError(f"HEC-DSS returned status {status} for {pathname}")

    def read_grid_record(self, pathname: str) -> Any:
        """Read one gridded record."""

        try:
            return self._require_open().get(pathname)
        except Exception as exc:
            raise DSSWriteError(f"Could not read DSS grid {pathname}") from exc

    def validate_grid_record(
        self,
        pathname: str,
        grid: GridDefinition,
        units: str,
    ) -> list[str]:
        """Return field-level problems for one record."""

        record = self.read_grid_record(pathname)
        problems: list[str] = []
        if record.numberOfCellsX != grid.width:
            problems.append("Grid width does not match")
        if record.numberOfCellsY != grid.height:
            problems.append("Grid height does not match")
        if not np.isclose(record.cellSize, grid.cell_size):
            problems.append("Grid cell size does not match")
        if record.lowerLeftCellX != grid.lower_left_cell_x:
            problems.append("Lower-left X index does not match")
        if record.lowerLeftCellY != grid.lower_left_cell_y:
            problems.append("Lower-left Y index does not match")
        if record.dataUnits.upper() != units.upper():
            problems.append("Units do not match")
        if "ALBERS" not in record.srsDefinition.upper():
            problems.append("SHG Albers metadata is missing")
        return problems
