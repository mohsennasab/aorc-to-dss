"""Live metadata discovery for the public NOAA AORC Zarr archive."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from ..exceptions import ArchiveError
from ..models import VariableMetadata

BUCKET = "noaa-nws-aorc-v1-1-1km"
BASE_URL = f"https://{BUCKET}.s3.amazonaws.com"
S3_URL = f"s3://{BUCKET}"

VARIABLE_HINTS: dict[str, dict[str, Any]] = {
    "APCP_surface": {
        "description": "One-hour liquid water equivalent depth ending at the timestamp",
        "aggregation": "sum",
        "dss_parameter": "PRECIP",
        "dss_units": "MM",
        "dss_data_type": 1,
    },
    "TMP_2maboveground": {
        "description": "Instantaneous air temperature at 2 m above ground",
        "aggregation": "mean",
        "dss_parameter": "AIRTEMP",
        "dss_units": "DEG C",
        "dss_data_type": 2,
    },
    "SPFH_2maboveground": {
        "description": "Instantaneous specific humidity at 2 m above ground",
        "aggregation": "mean",
        "dss_parameter": "SPEC-HUMID",
        "dss_units": "KG/KG",
        "dss_data_type": 2,
    },
    "DLWRF_surface": {
        "description": "Downward longwave radiation flux at the surface",
        "aggregation": "mean",
        "dss_parameter": "DLWRF",
        "dss_units": "W/M2",
        "dss_data_type": 0,
    },
    "DSWRF_surface": {
        "description": "Downward shortwave radiation flux at the surface",
        "aggregation": "mean",
        "dss_parameter": "DSWRF",
        "dss_units": "W/M2",
        "dss_data_type": 0,
    },
    "PRES_surface": {
        "description": "Instantaneous air pressure at the terrain surface",
        "aggregation": "mean",
        "dss_parameter": "PRESSURE",
        "dss_units": "PA",
        "dss_data_type": 2,
    },
    "UGRD_10maboveground": {
        "description": "Instantaneous west to east wind component at 10 m",
        "aggregation": "mean",
        "dss_parameter": "WIND-U",
        "dss_units": "M/S",
        "dss_data_type": 2,
    },
    "VGRD_10maboveground": {
        "description": "Instantaneous south to north wind component at 10 m",
        "aggregation": "mean",
        "dss_parameter": "WIND-V",
        "dss_units": "M/S",
        "dss_data_type": 2,
    },
}


def _request(url: str, timeout: int = 60) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "AORCtoDSS/0.1.6"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except Exception as exc:
        raise ArchiveError(
            f"Could not read AORC metadata from {url}",
            "Check the network connection and NOAA archive status, then retry.",
        ) from exc


class AORCCatalog:
    """Discover available years and variables without a fixed end date."""

    def __init__(self, base_url: str = BASE_URL, s3_url: str = S3_URL) -> None:
        self.base_url = base_url.rstrip("/")
        self.s3_url = s3_url.rstrip("/")

    @lru_cache(maxsize=1)
    def years(self) -> list[int]:
        """List complete annual Zarr stores in the archive."""

        query = urllib.parse.urlencode({"list-type": "2", "delimiter": "/"})
        root = ET.fromstring(_request(f"{self.base_url}/?{query}"))
        namespace = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
        years: list[int] = []
        for element in root.findall("s3:CommonPrefixes/s3:Prefix", namespace):
            prefix = element.text or ""
            if prefix.endswith(".zarr/") and prefix[:4].isdigit():
                years.append(int(prefix[:4]))
        if not years:
            raise ArchiveError(
                "The AORC archive did not return any annual stores",
                "Check the configured bucket and retry.",
            )
        return sorted(years)

    def store_url(self, year: int) -> str:
        """Return an S3 URL for one annual store."""

        if year not in self.years():
            raise ArchiveError(f"AORC data are not available for {year}")
        return f"{self.s3_url}/{year}.zarr"

    @lru_cache(maxsize=8)
    def consolidated_metadata(self, year: int) -> dict[str, Any]:
        """Read consolidated Zarr metadata for one year."""

        raw = _request(f"{self.base_url}/{year}.zarr/.zmetadata")
        try:
            return json.loads(raw.decode("utf-8"))["metadata"]
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ArchiveError(f"AORC metadata for {year} are malformed") from exc

    def variables(self) -> list[VariableMetadata]:
        """Return variables discovered in the newest annual store."""

        years = self.years()
        first_year = years[0]
        last_year = years[-1]
        metadata = self.consolidated_metadata(last_year)
        end = self._store_end(last_year, metadata)
        variables: list[VariableMetadata] = []
        for source_name, hint in VARIABLE_HINTS.items():
            attrs = metadata.get(f"{source_name}/.zattrs")
            if not isinstance(attrs, dict):
                continue
            variables.append(
                VariableMetadata(
                    source_name=source_name,
                    display_name=str(attrs.get("long_name", source_name)),
                    units=str(attrs.get("units", "")),
                    temporal_resolution="1 hour",
                    start=f"{first_year}-01-01T00:00:00Z",
                    end=end,
                    missing_value=float(attrs.get("missing_value", -32767)),
                    description=str(hint["description"]),
                    aggregation=hint["aggregation"],
                    dss_parameter=str(hint["dss_parameter"]),
                    dss_units=str(hint["dss_units"]),
                    dss_data_type=int(hint["dss_data_type"]),
                )
            )
        return variables

    def variable(self, source_name: str) -> VariableMetadata:
        """Return metadata for one source variable."""

        for variable in self.variables():
            if variable.source_name == source_name:
                return variable
        raise ArchiveError(f"AORC variable {source_name} is not available")

    @staticmethod
    def _store_end(year: int, metadata: dict[str, Any]) -> str:
        time_shape = metadata.get("time/.zarray", {}).get("shape", [0])
        count = int(time_shape[0]) if time_shape else 0
        if count <= 0:
            return f"{year}-12-31T23:00:00Z"
        start = datetime(year, 1, 1, tzinfo=timezone.utc)
        end = start.timestamp() + (count - 1) * 3600
        return datetime.fromtimestamp(end, tz=timezone.utc).isoformat().replace("+00:00", "Z")
