param(
    [switch]$SkipDependencies
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$serviceOutput = Join-Path $projectRoot "dist-service"
$serviceWork = Join-Path $projectRoot "build/service"

if (-not $SkipDependencies) {
    python -m pip install --upgrade ".[packaging]"
    if ($LASTEXITCODE -ne 0) {
        throw "Service build dependencies could not be installed"
    }
}

$projData = python -c "import pyproj; print(pyproj.datadir.get_data_dir())"
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $projData)) {
    throw "The PROJ data directory could not be found"
}

python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --noconsole `
    --name "AORCtoDSS-Service" `
    --paths (Join-Path $projectRoot "service") `
    --collect-binaries hecdss `
    --collect-data hecdss `
    --collect-binaries rasterio `
    --collect-data rasterio `
    --collect-submodules rasterio `
    --collect-binaries pyproj `
    --collect-data pyproj `
    --collect-binaries pyogrio `
    --collect-data pyogrio `
    --collect-submodules pyogrio `
    --add-data "$projData;pyproj/proj_dir/share/proj" `
    --hidden-import "numcodecs" `
    --hidden-import "aorctodss_service.__main__" `
    --exclude-module "black" `
    --exclude-module "cupy" `
    --exclude-module "h5py" `
    --exclude-module "IPython" `
    --exclude-module "jupyter" `
    --exclude-module "matplotlib" `
    --exclude-module "netCDF4" `
    --exclude-module "notebook" `
    --exclude-module "openpyxl" `
    --exclude-module "pytest" `
    --exclude-module "scipy" `
    --exclude-module "sklearn" `
    --exclude-module "torch" `
    --distpath $serviceOutput `
    --workpath $serviceWork `
    --specpath $serviceWork `
    (Join-Path $projectRoot "service/aorctodss_service/__main__.py")

if ($LASTEXITCODE -ne 0) {
    throw "AORCtoDSS Service build failed"
}

Write-Host "Built $serviceOutput\AORCtoDSS-Service.exe"
