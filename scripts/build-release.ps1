param(
    [switch]$SkipServiceBuild
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$releaseRoot = Join-Path $projectRoot "release"

npm run package:plugin
if ($LASTEXITCODE -ne 0) {
    throw "GeoLibre plugin packaging failed"
}

if (-not $SkipServiceBuild) {
    & (Join-Path $PSScriptRoot "build-service.ps1")
}

New-Item -ItemType Directory -Path $releaseRoot -Force | Out-Null
$serviceExe = Join-Path $projectRoot "dist-service/AORCtoDSS-Service.exe"
if (Test-Path -LiteralPath $serviceExe) {
    Copy-Item -LiteralPath $serviceExe -Destination $releaseRoot -Force
}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "install-windows.ps1") -Destination $releaseRoot -Force
Copy-Item -LiteralPath (Join-Path $projectRoot "LICENSE") -Destination $releaseRoot -Force

Write-Host "Release files are in $releaseRoot"
