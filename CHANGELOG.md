# Changelog

## 0.1.8

- Use `all_touched=True` source clipping with nearest-neighbor SHG reprojection
- Calculate DSS lower-left indices by flooring the minimum projected pixel-center coordinates
- Use area-weighted averaging as the single AOI time-series method
- Require event boundaries to fall exactly on UTC hours
- Compare source, projected, and DSS values with the same area-weighted AOI footprint
- Report absolute, percentage, and event-total differences during DSS validation
- Style the event-summary COG with the radar precipitation palette and transparent zero and NoData pixels
- Add an on-map rainfall color scale and synchronize a red event-chart marker with Time Slider playback
- Replace the plugin SVG with the new PNG icon
- Simplify the workflow navigation to large Tan and Camel step numbers
- Refresh the README workbench animation
- Add developer and project-support links

## 0.1.7

- Show archive, polygon weighting, and hourly averaging as separate progress phases
- Keep the progress bar below 100 percent until the time series is complete
- Skip polygon intersections for AORC cells that are fully inside or outside the study area
- Report area-weight row-block progress for large or detailed watershed boundaries
- Allow cancellation while area weights are being calculated

## 0.1.6

- Create Time Slider animations only from an explicit Step 4 download button
- Preload all selected-event frames and warm GeoLibre's cache with visible progress
- Open the native Time Slider only after every frame is cached and ready
- Use the radar-style `gist_ncar` precipitation scale with pink high intensities
- Add a 96-hour event shortcut and 4000 m SHG cell size
- Show live polygon edges, fill, and vertices while drawing, with Undo and Finish actions
- Disable map double-click zoom during polygon drawing and remove duplicate finish vertices
- Extend local-service startup and reconnect waiting to 30 seconds

## 0.1.5

- Populate GeoLibre's native Time Slider automatically when a Step 4 event is selected
- Stream hourly AOI frames from NOAA on demand through locally cached dated COGs
- Remove the obsolete solid-color Zarr animation layer from export results
- Write true COG output with explicit EPSG:5070 summary and EPSG:4326 animation CRS
- Clip summary and animation rasters to the selected polygon
- Apply a rainfall blue ramp and render precipitation zero and NoData pixels transparently

## 0.1.4

- Reworded chunk progress to describe watershed-average calculation
- Removed the duplicate in-panel animation controls and fixed native Time Slider playback
- Masked COG and DSS grids to the selected polygon instead of the rectangular SHG extent
- Compared reprojection means over the watershed rather than the source bounding box
- Wrote midnight interval ends with HEC's required preceding-date `2400` notation

## 0.1.3

- Made Run analysis wait visibly for the local service without opening Settings
- Added request timeouts and explicit service connection progress
- Removed the in-app hourly CSV table while retaining CSV export
- Packaged all Pyogrio binary modules required for GeoPackage output
- Added a packaged GeoPackage write to the executable self-test
- Fixed the system-profile WindowsApps access-denied export failure
- Hardened in-place installer shutdown for the packaged parent and child processes

## 0.1.2

- Load AORC variables automatically and recover when the local service starts late
- Added an explicit service retry control and automatic health checks
- Removed rolling-maximum statistics and automatic precipitation event separation
- Simplified event selection to manual dates and 24, 48, or 72-hour durations
- Added a selected-event time-series plot
- Added a native PNG save-location dialog and improved chart axis spacing
- Registered event animation with GeoLibre's native time slider
- Fixed sliced AORC Zarr chunk alignment and incomplete-store recovery

## 0.1.1

- Fixed projected GeoJSON import and direct reading from GeoLibre's file picker
- Added automatic EPSG CRS detection and WGS84 analysis reprojection
- Removed the Paste GeoJSON action
- Added metric and US-customary precipitation and temperature outputs
- Fixed timezone-compatible annual AORC time selection
- Added a live test across the 2000 and 2001 annual stores
- Reduced time-series chunks once and vectorized large-area polygon weights
- Enabled the configured persistent weight cache for screening analyses

## 0.1.0

- Added a GeoLibre 2.4 docked workflow
- Added polygon drawing, loaded-feature capture, and vector import
- Added live AORC annual-store and variable metadata discovery
- Added chunked Zarr reads and cached polygon weights
- Added watershed time-series plot, table, CSV export, and precipitation rolling totals
- Added custom, preset, rolling-maximum, and dry-gap event selection
- Added origin-aligned SHG reprojection and output estimates
- Added official HEC-DSS gridded record writing
- Added COG event summaries and Zarr time animation
- Added DSS read-back validation and processing reports
- Added Windows service packaging and per-user installation
