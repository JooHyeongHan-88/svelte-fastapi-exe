# packaging/release-dryrun.ps1
#
# Validates the full release pipeline locally without uploading to Nexus.
#
# Steps:
#   1. Run release.ps1 without -Upload (build + sha256 + latest.json)
#   2. Serve release/ via a local HTTP server (Nexus mock)
#   3. Fetch latest.json and print fields to confirm correct generation
#   4. Print manual verification scenarios
#
# Usage:
#   pwsh packaging/release-dryrun.ps1
#   pwsh packaging/release-dryrun.ps1 -Port 19800 -SkipBuild

param(
    [int]$Port = 19800,
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root

$nexusUrl = "http://127.0.0.1:$Port"

# Detect AppName from packaging/App.spec (same logic as release.ps1).
$specContent = Get-Content "packaging/App.spec" -Raw
if ($specContent -match "name\s*=\s*'([^']+)'") {
    $AppName = $Matches[1]
} else {
    $AppName = "App"
}

# 1. Build
if (-not $SkipBuild) {
    Write-Host "==> build (dryrun -- no upload)" -ForegroundColor Cyan
    & "$PSScriptRoot\release.ps1" -NexusBaseUrl $nexusUrl -Notes "dryrun build"
} else {
    Write-Host "==> SkipBuild: skipping build step" -ForegroundColor Yellow

    if (-not (Test-Path "release/latest.json")) {
        Write-Host "ERROR: release/latest.json not found. Remove -SkipBuild and run again." -ForegroundColor Red
        exit 1
    }
}

Write-Host ""
Write-Host "==> artifacts in release/" -ForegroundColor Cyan
Get-ChildItem release | Where-Object { $_.Extension -in ".exe",".json" } | Format-Table Name, Length, LastWriteTime

# 2. Start local Nexus mock (background job serving release/)
Write-Host "==> starting local Nexus mock: $nexusUrl  (serving release/)" -ForegroundColor Cyan

$serverJob = Start-Job -ScriptBlock {
    param($d, $p)
    Set-Location $d
    uv run python -m http.server $p --bind 127.0.0.1 2>&1
} -ArgumentList (Join-Path $root "release"), $Port

Start-Sleep -Seconds 1.5

if ($serverJob.State -eq "Failed") {
    Write-Host "ERROR: server failed to start" -ForegroundColor Red
    Receive-Job $serverJob
    exit 1
}

Write-Host "    server started  (Job ID: $($serverJob.Id))" -ForegroundColor Green

# 3. Fetch and display latest.json
Write-Host ""
Write-Host "==> fetching latest.json" -ForegroundColor Cyan
try {
    $latest = Invoke-RestMethod "$nexusUrl/latest.json"
    Write-Host "    version    : $($latest.version)"
    Write-Host "    url        : $($latest.url)"
    Write-Host "    sha256     : $($latest.sha256.Substring(0,16))..."
    Write-Host "    size       : $($latest.size) bytes"
} catch {
    Write-Host "ERROR: failed to fetch latest.json: $_" -ForegroundColor Red
}

# 4. Manual verification guide
Write-Host ""
Write-Host "------------------------------------------------------------" -ForegroundColor Cyan
Write-Host "  Manual verification scenarios  (app: $AppName)" -ForegroundColor Cyan
Write-Host "------------------------------------------------------------" -ForegroundColor Cyan
Write-Host ""
Write-Host "  [A] Run API server with local Nexus URL to test update detection:"
Write-Host "        `$env:APP_NEXUS_BASE_URL = '$nexusUrl'"
Write-Host "        uv run python backend/main.py"
Write-Host ""
Write-Host "  [B] Open browser: http://127.0.0.1:8765/api/update/check"
Write-Host "        -> update_available should be true"
Write-Host "        (latest.json version must be higher than current running version)"
Write-Host ""
Write-Host "  [C] Full self-replace test using the built EXE:"
Write-Host "        `$env:APP_NEXUS_BASE_URL = '$nexusUrl'"
Write-Host "        release/$AppName.exe"
Write-Host ""
Write-Host "  [D] Negative case -- sha256 mismatch:"
Write-Host "        Edit release/latest.json, set sha256 to a random value,"
Write-Host "        trigger update apply -> expect integrity check failure error"
Write-Host ""
Write-Host "------------------------------------------------------------" -ForegroundColor Cyan

# Wait for user, then clean up
Write-Host ""
Write-Host "Press Enter to stop the local server..." -ForegroundColor DarkGray
$null = Read-Host
Stop-Job $serverJob
Remove-Job $serverJob
Write-Host "Server stopped."
