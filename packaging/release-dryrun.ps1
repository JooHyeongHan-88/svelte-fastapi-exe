# packaging/release-dryrun.ps1
#
# Validates the full release pipeline locally without uploading to the remote repo.
#
# Steps:
#   1. Run release.ps1 without -Upload (build incl. extension frontends + sha256 + latest.json)
#   2. Serve release/ via a local HTTP server (remote repo mock)
#   3. Fetch latest.json + confirm extension dist/router bundles are present
#   4. Print manual verification scenarios
#
# Usage:
#   pwsh packaging/release-dryrun.ps1
#   pwsh packaging/release-dryrun.ps1 -Port 19800 -SkipBuild

param(
    [int]$Port = 19800,
    [switch]$SkipBuild,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root

$repoUrl = "http://127.0.0.1:$Port"

# Load .env file into environment variables
$envPath = Join-Path $root ".env"
if (Test-Path $envPath) {
    Get-Content $envPath -Encoding UTF8 | Where-Object { $_ -match '^\s*([^#\s][^=]*)=(.*)$' } | ForEach-Object {
        $key = $Matches[1].Trim()
        # Strip inline comment (e.g. "MyAgent  # description") then remove surrounding quotes
        $val = ($Matches[2] -split '\s+#', 2)[0].Trim().Trim('"').Trim("'")
        if (-not (Test-Path "env:$key")) {
            [Environment]::SetEnvironmentVariable($key, $val)
        }
    }
}

# Detect AppName from environment (set by .env)
$AppName = $env:APP_NAME
if (-not $AppName) {
    $AppName = "MyAgent"
}

# 1. Build
if (-not $SkipBuild) {
    Write-Host "==> build (dryrun -- no upload)" -ForegroundColor Cyan
    
    # release.ps1 reads the repo URL from $env:APP_REPO_BASE_URL.
    $env:APP_REPO_BASE_URL = $repoUrl

    $releaseArgs = @{
        Notes = "dryrun build"
    }
    if ($Force) { $releaseArgs["Force"] = $true }

    & "$PSScriptRoot\release.ps1" @releaseArgs
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

# 2. Start local remote-repo mock (background job serving release/)
Write-Host "==> starting local repo mock: $repoUrl  (serving release/)" -ForegroundColor Cyan

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
    $latest = Invoke-RestMethod "$repoUrl/latest.json"
    Write-Host "    version    : $($latest.version)"
    Write-Host "    url        : $($latest.url)"
    Write-Host "    sha256     : $($latest.sha256.Substring(0,16))..."
    Write-Host "    size       : $($latest.size) bytes"

    # Verify both EXE files exist in release/
    $plainExe = "release/$AppName.exe"
    $versionedExe = Get-ChildItem "release/$AppName-*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    Write-Host ""
    Write-Host "    plain exe  : $(if (Test-Path $plainExe) { 'OK' } else { 'MISSING' })"
    Write-Host "    versioned  : $(if ($versionedExe) { $versionedExe.Name } else { 'MISSING' })"
    Write-Host "    url target : $AppName.exe (version-less)"
} catch {
    Write-Host "ERROR: failed to fetch latest.json: $_" -ForegroundColor Red
}

# 3b. Confirm extension bundles (release.ps1 builds dist/, App.spec bundles it into the EXE).
Write-Host ""
Write-Host "==> extension bundles  (App.spec bundles dist/ + backend/ into the EXE)" -ForegroundColor Cyan
$extRoot = Join-Path $root "extensions"
if (Test-Path $extRoot) {
    $extDirs = Get-ChildItem $extRoot -Directory | Where-Object { $_.Name -notmatch '^[._]' }
    if ($extDirs) {
        foreach ($ext in $extDirs) {
            $distOk = Test-Path (Join-Path $ext.FullName "frontend\dist\index.html")
            $apiOk = Test-Path (Join-Path $ext.FullName "backend\router.py")
            Write-Host ("    {0,-18} dist:{1}  router:{2}" -f `
                $ext.Name, `
                $(if ($distOk) { 'OK' } else { '--' }), `
                $(if ($apiOk) { 'OK' } else { '--' }))
        }
    } else {
        Write-Host "    (none)"
    }
} else {
    Write-Host "    (no extensions/ dir)"
}

# 4. Manual verification guide
Write-Host ""
Write-Host "------------------------------------------------------------" -ForegroundColor Cyan
Write-Host "  Manual verification scenarios  (app: $AppName)" -ForegroundColor Cyan
Write-Host "------------------------------------------------------------" -ForegroundColor Cyan
Write-Host ""
Write-Host "  [A] Run API server with local repo URL to test update detection:"
Write-Host "        `$env:APP_REPO_BASE_URL = '$repoUrl'"
Write-Host "        uv run python backend/main.py"
Write-Host ""
Write-Host "  [B] Open browser: http://127.0.0.1:8765/api/update/check"
Write-Host "        -> update_available should be true"
Write-Host "        (latest.json version must be higher than current running version)"
Write-Host ""
Write-Host "  [C] Full self-replace test using the built EXE:"
Write-Host "        `$env:APP_REPO_BASE_URL = '$repoUrl'"
Write-Host "        release/$AppName.exe"
Write-Host ""
Write-Host "  [D] Negative case -- sha256 mismatch:"
Write-Host "        Edit release/latest.json, set sha256 to a random value,"
Write-Host "        trigger update apply -> expect integrity check failure error"
Write-Host ""
Write-Host "  [E] Extension entry (served by the same backend EXE):"
Write-Host "        http://127.0.0.1:8765/ext/evaluator/?path=result/<session>/<ts>/<file>.parquet"
Write-Host "        -> extension SPA loads + /api/ext/evaluator/* responds"
Write-Host ""
Write-Host "------------------------------------------------------------" -ForegroundColor Cyan

# Wait for user, then clean up
Write-Host ""
Write-Host "Press Enter to stop the local server..." -ForegroundColor DarkGray
$null = Read-Host
Stop-Job $serverJob
Remove-Job $serverJob
Write-Host "Server stopped."
