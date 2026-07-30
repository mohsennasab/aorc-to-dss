$ErrorActionPreference = "Stop"

$releaseRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pluginArchive = Get-ChildItem -LiteralPath $releaseRoot -Filter "AORCtoDSS-plugin-*.zip" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
$serviceSource = Join-Path $releaseRoot "AORCtoDSS-Service.exe"

if (-not $pluginArchive) {
    throw "The AORCtoDSS GeoLibre plugin archive is missing"
}
if (-not (Test-Path -LiteralPath $serviceSource)) {
    throw "AORCtoDSS-Service.exe is missing"
}

$pluginDirectory = Join-Path $env:APPDATA "org.geolibre.desktop/plugins"
$installDirectory = Join-Path $env:LOCALAPPDATA "AORCtoDSS/bin"
$startupDirectory = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupDirectory "AORCtoDSS Service.lnk"

New-Item -ItemType Directory -Path $pluginDirectory -Force | Out-Null
New-Item -ItemType Directory -Path $installDirectory -Force | Out-Null

$installedPlugin = Join-Path $pluginDirectory "aorctodss.zip"
$installedService = Join-Path $installDirectory "AORCtoDSS-Service.exe"

# A running executable cannot be replaced on Windows. Stop only instances that
# are running from this plugin's per-user install directory.
$installedServiceFullPath = [System.IO.Path]::GetFullPath($installedService)
function Get-InstalledServiceProcessIds {
    @(
        Get-CimInstance Win32_Process -Filter "Name='AORCtoDSS-Service.exe'" |
            Where-Object {
                $_.ExecutablePath -and
                [string]::Equals(
                    [System.IO.Path]::GetFullPath($_.ExecutablePath),
                    $installedServiceFullPath,
                    [System.StringComparison]::OrdinalIgnoreCase
                )
            } |
            Select-Object -ExpandProperty ProcessId
    )
}

# PyInstaller's one-file runtime uses a parent and child process. Re-enumerate
# after each stop so neither process can keep the executable mapped.
foreach ($attempt in 1..10) {
    $installedProcessIds = Get-InstalledServiceProcessIds
    if ($installedProcessIds.Count -eq 0) {
        break
    }
    $installedProcessIds | ForEach-Object {
        Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Milliseconds 400
}
$remainingProcessIds = Get-InstalledServiceProcessIds
if ($remainingProcessIds.Count -gt 0) {
    throw "The installed AORCtoDSS service could not be stopped. Process IDs: $($remainingProcessIds -join ', ')"
}

Copy-Item -LiteralPath $pluginArchive.FullName -Destination $installedPlugin -Force
$serviceCopied = $false
foreach ($attempt in 1..20) {
    try {
        Copy-Item -LiteralPath $serviceSource -Destination $installedService -Force
        $serviceCopied = $true
        break
    }
    catch {
        if ($attempt -eq 20) {
            throw
        }
        Start-Sleep -Milliseconds 500
    }
}
if (-not $serviceCopied) {
    throw "AORCtoDSS-Service.exe could not be updated"
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $installedService
$shortcut.WorkingDirectory = $installDirectory
$shortcut.WindowStyle = 7
$shortcut.Description = "AORCtoDSS local processing service"
$shortcut.Save()

Start-Process -FilePath $installedService -WorkingDirectory $installDirectory -WindowStyle Hidden

Write-Host "AORCtoDSS was installed for the current user."
Write-Host "Restart GeoLibre Desktop, then activate AORCtoDSS from the Plugins menu."
