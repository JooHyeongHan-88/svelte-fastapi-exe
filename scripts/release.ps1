# scripts/release.ps1
#
# Steps:
#   1. Sync version from pyproject.toml -> backend/_version.py
#   2. Frontend build (Vite)             -> build/web/
#   3. Updater.exe build                 -> build/updater/Updater.exe
#   4. App EXE build                     -> release/{AppName}.exe
#   5. Compute sha256 + generate          release/latest.json
#   6. Upload to Nexus raw repo (requires -Upload flag)
#
# App name is read automatically from the name= field in App.spec.
# To rename the output EXE, change name='...' in App.spec — no other edits needed.
#
# Output layout:
#   build/    intermediate artifacts (bundled into the EXE, never uploaded)
#   release/  final artifacts (uploaded to Nexus)
#
# Usage:
#   pwsh scripts/release.ps1
#   pwsh scripts/release.ps1 -Upload -NexusBaseUrl https://nexus.internal/repository/myapp -NexusUser foo -NexusPass bar

param(
    [switch]$Upload,
    [string]$NexusBaseUrl = "",
    [string]$NexusUser,
    [string]$NexusPass,
    [string]$Notes = ""
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root

# Ensure output directories exist.
New-Item -ItemType Directory -Force -Path "build", "release" | Out-Null

# Detect AppName from App.spec's  name='...'  field.
$specContent = Get-Content "App.spec" -Raw
if ($specContent -match "name\s*=\s*'([^']+)'") {
    $AppName = $Matches[1]
} else {
    throw "Could not detect app name from App.spec (expected: name='...')"
}
Write-Host "==> app name  : $AppName"

# Fall back to a sensible Nexus default if not provided.
if (-not $NexusBaseUrl) {
    $NexusBaseUrl = "https://nexus.internal/repository/$($AppName.ToLower())"
}

# 1. version sync: pyproject.toml -> backend/_version.py
$pyproject = Get-Content "pyproject.toml" -Raw
if ($pyproject -notmatch '(?m)^version\s*=\s*"([^"]+)"') {
    throw "version field not found in pyproject.toml"
}
$version = $Matches[1]
Write-Host "==> version   : $version"

[System.IO.File]::WriteAllText(
    (Join-Path (Get-Location).Path "backend/_version.py"),
    "__version__ = `"$version`"`n",
    (New-Object System.Text.UTF8Encoding $false)
)

# 2. frontend build -> build/web/
Write-Host "==> frontend build  (-> build/web/)"
Push-Location frontend
npm run build
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "frontend build failed" }
Pop-Location

# 3. Updater.exe -> build/updater/Updater.exe
Write-Host "==> updater build   (-> build/updater/)"
uv run pyinstaller --noconfirm --clean `
    --distpath build/updater `
    --workpath build/pyi-updater `
    Updater.spec
if ($LASTEXITCODE -ne 0) { throw "updater build failed" }

if (-not (Test-Path "build/updater/Updater.exe")) {
    throw "build/updater/Updater.exe was not created"
}

# 4. App EXE -> release/{AppName}.exe
Write-Host "==> app build       (-> release/)"
uv run pyinstaller --noconfirm --clean `
    --distpath release `
    --workpath build/pyi-app `
    App.spec
if ($LASTEXITCODE -ne 0) { throw "app build failed" }

$exePath = "release/$AppName.exe"
if (-not (Test-Path $exePath)) {
    throw "$exePath was not created"
}

# 5. sha256 + latest.json
$sha256 = (Get-FileHash $exePath -Algorithm SHA256).Hash.ToLower()
$size   = (Get-Item $exePath).Length
$releasedAt = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")

$versionedName = "$AppName-$version.exe"
$versionedPath = "release/$versionedName"
Copy-Item $exePath $versionedPath -Force

$latest = [ordered]@{
    version               = $version
    url                   = "$NexusBaseUrl/$versionedName"
    sha256                = $sha256
    size                  = $size
    released_at           = $releasedAt
    min_supported_version = "0.0.0"
    notes                 = $Notes
}

$latestJsonPath = "release/latest.json"
# Must write UTF-8 without BOM: PowerShell 5.1 Set-Content -Encoding utf8 adds BOM,
# which breaks Invoke-RestMethod JSON parsing on the receiving end.
$jsonContent = $latest | ConvertTo-Json -Depth 5
[System.IO.File]::WriteAllText(
    (Join-Path (Get-Location).Path $latestJsonPath),
    $jsonContent,
    (New-Object System.Text.UTF8Encoding $false)
)

Write-Host ""
Write-Host "==> artifacts"
Write-Host "    $versionedPath  ($size bytes)"
Write-Host "    sha256 : $sha256"
Write-Host "    $latestJsonPath"

# 6. upload
if ($Upload) {
    if (-not $NexusUser -or -not $NexusPass) {
        Write-Host "WARNING: -NexusUser/-NexusPass not set; proceeding with anonymous PUT." -ForegroundColor Yellow
    }

    $headers = @{}
    if ($NexusUser -and $NexusPass) {
        $pair = "$NexusUser`:$NexusPass"
        $b64  = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($pair))
        $headers["Authorization"] = "Basic $b64"
    }

    # Upload EXE first -- latest.json must go last so clients never see a metadata
    # pointer to a non-existent file.
    Write-Host "==> uploading $versionedName"
    Invoke-WebRequest -Uri "$NexusBaseUrl/$versionedName" `
        -Method Put -InFile $versionedPath -Headers $headers `
        -ContentType "application/octet-stream" | Out-Null

    Write-Host "==> uploading latest.json"
    Invoke-WebRequest -Uri "$NexusBaseUrl/latest.json" `
        -Method Put -InFile $latestJsonPath -Headers $headers `
        -ContentType "application/json" | Out-Null

    Write-Host "uploaded: $NexusBaseUrl/$versionedName"
    Write-Host "uploaded: $NexusBaseUrl/latest.json"
} else {
    Write-Host ""
    Write-Host "Skipping upload. Add -Upload flag to push to Nexus."
}
