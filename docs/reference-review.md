# Reference Review

This review was completed before the architecture was selected. It records what
each requested source contributed and which ideas were carried into the plugin.

## GeoLibre documentation and source

[GeoLibre](https://geolibre.app/) documents a Tauri, React, TypeScript, and
MapLibre application. Version 2.4 has a curated external plugin loader, docked
plugin panels, toolbar menus, COG layers, Zarr layers, temporal adapters, and a
desktop file bridge.

[GeoLibre plugin development](https://plugins.geolibre.app/develop/) defines an
external plugin as a trusted, self-contained ES module with `plugin.json`,
`index.js`, and optional global CSS. The module exports `activate` and
`deactivate`. Plugin entry and manifest identity fields must match.

The GeoLibre source was used to confirm these current host capabilities:

- `registerRightPanel` for a docked workbench
- `pickVectorFilesWithSidecars` for desktop vector import
- `addCogLayer` for the event summary
- `addZarrLayer` and `setZarrLayerSelector` for event playback
- `exportTextFile` for browser and desktop downloads
- Project-state hooks for persisted plugin settings

This required changing the proposed QGIS and PyQt package structure. A Python
plugin would not load in GeoLibre 2.4. Python remains in a local service because
raster libraries and HEC-DSS need native code.

## GeoLibre plugin template

The
[official template](https://github.com/opengeos/geolibre-plugin-template)
provided the build pattern, host API type definitions, plugin lifecycle, panel
registration pattern, and release archive layout. AORCtoDSS follows the same
bundle contract and keeps all relative imports inside the Vite output.

## Open Climate Service GeoLibre plugin

The
[Open Climate Service plugin](https://github.com/dhis2/open-climate-service-geolibre-plugin)
shows a current production plugin that reads climate metadata, creates a native
GeoLibre layer, persists state, and drives a time selector. Its metadata-first
approach supported the decision to read variable names and dimensions from
AORC Zarr metadata instead of presenting an unverified list. Its current
`registerTemporalLayer` adapter pattern was also used to bind completed event
Zarr layers to GeoLibre's native time slider.

No Open Climate Service source was copied.

## NOAA AORC viewer

The
[NOAA AORC viewer](https://github.com/mohsennasab/noaa-aorc-viewer)
uses direct start and end controls, a prominent time-series plot, unit-aware
labels, and explicit chart margins. Those patterns supported the simplified
manual event controls, the selected-event plot, and additional space between
the vertical-axis title and tick labels.

No NOAA AORC viewer source was copied.

## NOAA AORC registry and archive

The [AORC registry](https://registry.opendata.aws/noaa-nws-aorc/) provides:

- Public bucket `noaa-nws-aorc-v1-1-1km` in `us-east-1`
- Annual Zarr stores
- 30 arc-second latitude and longitude cells
- One-hour temporal resolution
- Eight meteorologic variables
- A 144 by 128 by 256 time, latitude, and longitude chunk layout
- Public-use and attribution terms

The live bucket listing exposed annual stores from 1979 through 2025 during
development. The annual `.zmetadata` files confirmed source names, units, scale
factors, missing value `-32767`, array shape, and EPSG:4326.

The chunk layout supports bounding-box reads without full-raster downloads.
The service opens each required annual store anonymously, applies the spatial
and time selections before array computation, and writes only an event subset
for animation.

NOAA announced on April 2, 2026 that a small fraction of rows had been masked
incorrectly and that Zarr files were being regenerated. The plugin therefore
discovers the archive period and reads current metadata at run time.

## StormHub

[StormHub](https://github.com/Dewberry/stormhub) is an MIT-licensed Python
library for hydrometeorologic catalogs and storm transposition. The
`stormhub/met` package contains AORC access, polygon masking, event analysis,
SHG reprojection, and DSS export.

Useful concepts identified during review:

- Anonymous S3 access to annual AORC Zarr stores
- Variable and time selection before data computation
- Bounding-box reads followed by polygon work
- Chunked time processing for event grids
- A true SHG Albers projection
- Lower-left SHG cell indices derived from aligned projected coordinates
- Reversing north-up raster rows for the DSS lower-left row convention
- One DSS grid record per time interval
- Separate precipitation and instantaneous-variable time conventions

AORCtoDSS does not depend on StormHub and does not contain StormHub source.
The service uses its own data models, error handling, polygon weight cache,
reprojection functions, job controls, output reports, and validation. The
reviewed concepts are standard geospatial and HEC interoperability practices.

StormHub's MIT license permits reuse with notice, but avoiding a dependency
keeps installation smaller and matches the project requirement.

## StormCatalog mass-curve script

The requested
[StormCatalog mass-curve script](https://github.com/mohsennasab/meteorology-tools/tree/main/Scripts/StormCatalog_MassCurve)
reads event items, calculates hourly and cumulative precipitation, and reports
both a maximum-grid-cell series and a watershed-mean series.

The review supported these interface choices:

- Keep the watershed mean as the main screening series
- Keep event-duration shortcuts beside the manual UTC date controls
- Keep event-total raster creation separate from the hourly series
- Use one fixed event window for the full export

The script works from an existing StormHub catalog. AORCtoDSS instead starts
from a GeoLibre area and reads AORC directly.

## HEC-DSS source and Python wrapper

[HEC-DSS](https://github.com/HydrologicEngineeringCenter/hec-dss) is MIT
licensed. Current Windows builds provide a self-contained `hecdss.dll` with
static zlib and Microsoft runtime linkage.

The
[official Python wrapper](https://github.com/HydrologicEngineeringCenter/hec-dss-python)
supports gridded data creation and read-back through `GriddedData` and
`HecDss`. The current wheel includes Windows and Linux native libraries.

AORCtoDSS uses the official wrapper instead of StormHub's DSS path. The adapter
owns all native handles, writes incrementally, closes on failure, lists
pathnames, reads records, and checks grid metadata.

The MIT license permits bundling. Binary releases must retain the HEC license
notice and should be rebuilt when the official wrapper or native library is
updated.

## HEC gridded data and SHG guidance

HEC documentation defines SHG as an NAD83 Albers equal-area grid with:

- Standard parallels 29.5 and 45.5 degrees north
- Central meridian 96 degrees west
- Latitude of origin 23 degrees north
- Zero false easting and northing
- Cell indices measured from the projected origin

HEC supports 10, 20, 50, 100, 200, 500, 1000, 2000, 4000, 5000, and 10000 m SHG
cells. A bare `SHG` A-part means the default 2000 m grid.

HEC gridded pathname guidance assigns:

- A-part to the grid reference system
- B-part to the region or watershed
- C-part to the parameter
- D and E to the grid interval
- F-part to the source or processing version

These conventions replaced the initial prompt example that put the watershed in
the A-part.

## Optional sample DSS file

The prompt identifies a local sample DSS file for precipitation and temperature
comparison. It is not distributed with this repository and no automated test
changes it. A release reviewer can use it as a read-only comparison file when
the path is available.

Normal tests create a small temporary DSS file, write one SHG grid, reopen it,
and compare data and metadata. Temporary fixtures keep test runs independent
from private or organization-specific files.
