# Developer Guide

## Module boundaries

The GeoLibre plugin is under `src`.

- `plugin.ts` owns activation, deactivation, state persistence, and host panels
- `ui/workbench.ts` owns the guided workflow
- `ui/aoi-map.ts` owns temporary map interaction and AOI display
- `ui/timeseries-chart.ts` owns plot interaction
- `api/client.ts` owns the loopback HTTP contract
- `animation.ts` owns Time Slider registration and cached frame playback
- `core` contains browser-side geometry, time, event, and pathname helpers

The processing service is under `service/aorctodss_service`.

- `aorc` owns archive discovery, chunked reads, and watershed averages
- `spatial` owns geometry checks, polygon weights, SHG definitions,
  reprojection, and COG output
- `events` owns UTC event calculations
- `dss` owns pathname rules, the official HEC adapter, and validation
- `jobs.py` owns background execution and cancellation
- `server.py` owns the loopback API and output file range requests
- `pipeline.py` coordinates an export without placing processing in the UI

Dependencies enter through the catalog, adapter, and job boundaries. Core
geometry and event functions can be tested without network access.

## Developer setup

```powershell
npm install
python -m pip install -e ".[dev,packaging]"
```

Build the GeoLibre bundle:

```powershell
npm run build
```

Start the service:

```powershell
python -m aorctodss_service
```

Package and install the plugin through GeoLibre:

```powershell
npm run package:plugin
```

## Test groups

Fast tests do not access NOAA:

```powershell
python -m pytest
npm test
```

The Python suite covers geometry repair, reprojection, weights, missing data,
events, UTC rules, pathnames, SHG alignment, configuration, and HEC-DSS grid
round-trip.

The TypeScript suite covers GeoJSON handling, event calculations, pathname
previews, polygon drawing, animation registration, and workbench behavior.

Run the live metadata check:

```powershell
$env:AORCTODSS_RUN_INTEGRATION = "1"
python -m pytest -m integration
```

Use a short event and small polygon for full manual integration. Confirm:

1. AORC metadata loads
2. The time series has every requested hour
3. Event hours match the requested interval
4. The COG displays in GeoLibre
5. Animation preload reaches 100 percent
6. The Time Slider plays the cached COG frames
7. HEC-DSS pathnames match the event
8. The validation report has no unexplained failures
9. HEC-HMS can select the grid set

## Packaging

`npm run package:plugin` builds the external ES module and creates the plugin
archive in `release`.

`scripts/build-service.ps1` creates a one-file Windows service with PyInstaller.
After building it, verify the packaged native libraries and loopback API:

```powershell
.\scripts\test-packaged-service.ps1
```

The check writes and reads a small SHG grid through HEC-DSS, then requests a
grid estimate from the packaged service.
The build collects native and data files from:

- `hecdss`
- Rasterio and GDAL
- PyProj and PROJ
- Zarr codecs
- Pillow GIF support

`scripts/build-release.ps1` runs both builds and copies the installer script and
license into `release`.

Inspect the plugin archive before release. It must contain only:

- `plugin.json`
- `dist/index.js`
- `dist/index.js.map`
- `dist/style.css`
- Public icons

The package script rejects private, working-memory, handoff, and Markdown files.

## Release checklist

1. Update the version files listed in the main README.
2. Update `CHANGELOG.md`.
3. Run Python and TypeScript tests.
4. Run the live metadata test.
5. Run TypeScript type checking.
6. Build the plugin.
7. Build the service on a clean Windows runner.
8. Install into a clean GeoLibre profile.
9. Run a short precipitation export.
10. Open the output in a current HEC application.
11. Review the packaged license notices.
12. Inspect the archive and repository privacy checks.
13. Tag the release and attach the release files.

## Updating the AORC period

Normal archive growth does not require a code change. `AORCCatalog.years`
lists annual prefixes and `.zmetadata` supplies the newest time dimension.

When NOAA adds a variable or changes a source name:

1. Inspect the newest annual `.zmetadata`.
2. Add a reviewed processing rule to `VARIABLE_HINTS`.
3. Decide whether the variable is accumulated, averaged, or instantaneous.
4. Choose an HEC parameter, output units, and DSS data type.
5. Add unit and event tests.
6. Run a small live integration.
7. Document the variable in the README.

Do not add a display-only variable rule without a reviewed DSS meaning.

## Updating HEC-DSS components

1. Review the HEC-DSS and `hec-dss-python` release notes.
2. Confirm that both projects retain redistribution terms compatible with the
   release.
3. Update the `hecdss` bound in `pyproject.toml`.
4. Build the service on each supported operating system.
5. Run the DSS round-trip test.
6. Write several hourly grids and read every record back.
7. Compare the resulting catalog and metadata in HEC-DSSVue or HEC-HMS.
8. Check the packaged native library dependencies.
9. Retain the official license notices.

Do not replace the official library with a file copied from a workstation.

## Logging and failure reports

Normal interface messages should state what failed and the next user action.
Tracebacks belong in the job error payload and processing log.

When reporting a failure, include:

- Plugin and service versions
- GeoLibre version
- Operating system
- Variable and event period
- AOI area and bounds without private project attributes
- SHG cell size and dimensions
- Processing log
- Validation report

Remove project names and local paths when they are sensitive.
