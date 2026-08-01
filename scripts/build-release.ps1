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
    $releaseService = Join-Path $releaseRoot "AORCtoDSS-Service.exe"
    $serviceIsCurrent =
        (Test-Path -LiteralPath $releaseService) -and
        ((Get-FileHash -LiteralPath $serviceExe -Algorithm SHA256).Hash -eq
            (Get-FileHash -LiteralPath $releaseService -Algorithm SHA256).Hash)
    if ($serviceIsCurrent) {
        Write-Host "The release service is already current"
    }
    else {
        Copy-Item -LiteralPath $serviceExe -Destination $releaseService -Force
    }
}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "install-windows.ps1") -Destination $releaseRoot -Force
Copy-Item -LiteralPath (Join-Path $projectRoot "LICENSE") -Destination $releaseRoot -Force

$checksumFiles = @(
    Get-ChildItem -LiteralPath $releaseRoot -Filter "AORCtoDSS-plugin-*.zip" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    Get-Item -LiteralPath (Join-Path $releaseRoot "AORCtoDSS-Service.exe") -ErrorAction SilentlyContinue
    Get-Item -LiteralPath (Join-Path $releaseRoot "install-windows.ps1")
) | Where-Object { $_ }
$checksumLines = $checksumFiles | ForEach-Object {
    $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash  $($_.Name)"
}
Set-Content -LiteralPath (Join-Path $releaseRoot "SHA256SUMS.txt") -Value $checksumLines -Encoding utf8

Write-Host "Release files are in $releaseRoot"
