param(
    [int]$Port = 8876
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$serviceExecutable = Join-Path $projectRoot "dist-service/AORCtoDSS-Service.exe"

if (-not (Test-Path -LiteralPath $serviceExecutable)) {
    throw "Build the packaged service before running this check"
}

$selfTestProcess = Start-Process `
    -FilePath $serviceExecutable `
    -ArgumentList "--self-test" `
    -WorkingDirectory (Split-Path -Parent $serviceExecutable) `
    -WindowStyle Hidden `
    -PassThru `
    -Wait
if ($selfTestProcess.ExitCode -ne 0) {
    throw "The packaged HEC-DSS grid round-trip check failed with exit code $($selfTestProcess.ExitCode)"
}

$serviceProcess = Start-Process `
    -FilePath $serviceExecutable `
    -ArgumentList "--port", $Port `
    -WorkingDirectory (Split-Path -Parent $serviceExecutable) `
    -WindowStyle Hidden `
    -PassThru

try {
    $health = $null
    foreach ($attempt in 1..30) {
        try {
            $health = Invoke-RestMethod `
                -Uri "http://127.0.0.1:$Port/health" `
                -TimeoutSec 3
            break
        }
        catch {
            Start-Sleep -Seconds 2
        }
    }
    if (-not $health) {
        throw "The packaged service did not become healthy"
    }

    $payload = @"
{
  "geometry": {
    "type": "Polygon",
    "coordinates": [[
      [-97.1, 38.9],
      [-96.9, 38.9],
      [-96.9, 39.1],
      [-97.1, 39.1],
      [-97.1, 38.9]
    ]]
  },
  "source_crs": "EPSG:4326",
  "event_start": "2025-06-01T00:00:00Z",
  "event_end": "2025-06-01T06:00:00Z",
  "cell_size": 2000,
  "buffer_m": 0
}
"@

    $estimate = Invoke-RestMethod `
        -Uri "http://127.0.0.1:$Port/estimate" `
        -Method Post `
        -ContentType "application/json" `
        -Body $payload `
        -TimeoutSec 30

    if ($health.status -ne "ok" -or -not $health.dss.available) {
        $dssStatus = $health.dss | ConvertTo-Json -Compress
        throw "The packaged service did not load its HEC-DSS dependency: $dssStatus"
    }
    if ($estimate.grid.width -lt 1 -or $estimate.grid.height -lt 1) {
        throw "The packaged service returned an invalid SHG estimate"
    }

    [pscustomobject]@{
        ProcessId = $serviceProcess.Id
        Healthy = $health.status -eq "ok"
        Version = $health.version
        DSS = $health.dss.available
        GridWidth = $estimate.grid.width
        GridHeight = $estimate.grid.height
        Hours = $estimate.grid.hours
    } | Format-List
}
finally {
    $listener = Get-NetTCPConnection `
        -LocalPort $Port `
        -State Listen `
        -ErrorAction SilentlyContinue
    if ($listener) {
        Stop-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
    }
    if (-not $serviceProcess.HasExited) {
        Stop-Process -Id $serviceProcess.Id -ErrorAction SilentlyContinue
    }
    $serviceProcess.WaitForExit()
}
