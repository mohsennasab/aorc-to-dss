# GeoLibre marketplace submission

The GeoLibre marketplace keeps a reviewed list of plugins in
[`opengeos/geolibre-plugins`](https://github.com/opengeos/geolibre-plugins).
AORCtoDSS should be submitted as an unpacked plugin folder. The manual-install
ZIP and the Windows service stay in the AORCtoDSS release page.

## Before opening the pull request

Build and test the AORCtoDSS release from its own repository:

```powershell
npm ci
npm run check
python -m pytest
npm run package:plugin
```

Publish the plugin ZIP, Windows service, installer, and checksum file on the
[AORCtoDSS releases page](https://github.com/mohsennasab/aorc-to-dss/releases).
Marketplace users download the service and installer into the same folder, then
run the installer with the `ServiceOnly` option. Sign the service executable
when a Windows code-signing certificate is available.

## Add AORCtoDSS to the marketplace repository

1. Fork [`opengeos/geolibre-plugins`](https://github.com/opengeos/geolibre-plugins)
   to your GitHub account.
2. Clone your fork and create a branch:

   ```powershell
   git clone https://github.com/YOUR-GITHUB-NAME/geolibre-plugins.git
   Set-Location geolibre-plugins
   git switch -c add-aorctodss-0.2.0
   ```

3. Create the plugin folder:

   ```powershell
   New-Item -ItemType Directory -Force plugins\aorctodss\dist
   ```

4. Copy these files from the AORCtoDSS repository:

   ```text
   geolibre-plugin/plugin.json     -> plugins/aorctodss/plugin.json
   geolibre-plugin/dist/index.js   -> plugins/aorctodss/dist/index.js
   geolibre-plugin/dist/style.css  -> plugins/aorctodss/dist/style.css
   ```

   Do not copy the plugin ZIP, Windows executable, source map, or source icon.

5. Add this object to the `plugins` array in `plugin-registry.json`:

   ```json
   {
     "id": "aorctodss",
     "name": "AORCtoDSS",
     "version": "0.2.0",
     "description": "Prepare NOAA AORC watershed time series, variable-aware event summaries, animations, and SHG HEC-DSS grids. Requires Windows and the AORCtoDSS companion service.",
     "author": "Mohsen Tahmasebi Nasab",
     "homepage": "https://github.com/mohsennasab/aorc-to-dss",
     "manifestUrl": "plugins/aorctodss/plugin.json",
     "categories": ["Climate", "Raster", "Data"],
     "minGeoLibreVersion": "2.4.0"
   }
   ```

6. Run the marketplace repository checks:

   ```powershell
   npm ci
   npm run minify
   npm run minify:check
   npm run validate
   ```

   Commit the minified bundle. The marketplace workflow cannot write the
   minified result back to a contributor's fork.

## Preview the marketplace entry

Serve the marketplace repository with CORS enabled on port 8090. For example:

```powershell
npx http-server . -p 8090 --cors
```

In a separate PowerShell window, set the registry URL before starting a local
GeoLibre build:

```powershell
$env:VITE_GEOLIBRE_PLUGIN_REGISTRY_URL = "http://localhost:8090/plugin-registry.json"
```

Open **Settings > Manage Plugins** and install AORCtoDSS. Check both cases:

1. With the service stopped, the panel shows the Windows service and setup links.
2. After running `install-windows.ps1 -ServiceOnly`, Retry connects successfully.
3. A small AOI can complete a time series, animation, raster, and DSS export.
4. Deactivating the plugin removes its panel, toolbar menu, and map control.

## Open the pull request

Review the changes and push the branch:

```powershell
git status --short
git diff --check
git add plugins/aorctodss plugin-registry.json
git commit -m "Add AORCtoDSS plugin v0.2.0"
git push -u origin add-aorctodss-0.2.0
```

Open a pull request from the branch to `opengeos/geolibre-plugins:main`. In the
description, state that the browser plugin uses a loopback-only Windows service,
link to the service source and release, and list the tests that passed. Include
one screenshot of the workbench and one screenshot of a completed result.

After the pull request is merged, the marketplace site publishes the new entry.
Future releases require a version bump in both `plugin.json` and
`plugin-registry.json`, followed by a fresh copy of the built JavaScript and CSS.
