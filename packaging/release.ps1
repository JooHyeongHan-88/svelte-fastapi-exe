# packaging/release.ps1
#
# Steps:
#   1. Read version from pyproject.toml (App.spec generates _version.py at build time)
#   2. Frontend build (Vite)             -> build/web/
#   3. Extension frontends (Vite)        -> extensions/*/frontend/dist/  (bundled by App.spec)
#   4. Updater.exe build                 -> build/updater/Updater.exe
#   5. App EXE build (channel baked in)  -> release/{AppName}.exe
#   6. Compute sha256 + generate          release/latest.json
#   7. Publish GitHub Release via gh CLI (requires -Upload flag)
#
# -Channel qa|prod is MANDATORY:
#   qa   -> Mock provider visible, auto-update disabled, published as --prerelease
#   prod -> Mock provider hidden, auto-update enabled, published as full release
# The channel is injected as APP_BUILD_CHANNEL; App.spec bakes it into the bundled .env.
#
# App name is read automatically from the name= field in packaging/App.spec.
# To rename the output EXE, change name='...' in packaging/App.spec — no other edits needed.
#
# Output layout:
#   build/    intermediate artifacts (bundled into the EXE, never uploaded)
#   release/  final artifacts (attached to the GitHub Release)
#
# Usage:
#   pwsh packaging/release.ps1 -Channel qa
#   pwsh packaging/release.ps1 -Channel prod -Upload -Notes "변경사항 요약"
#
# 저장소 루트 URL 은 .env(APP_REPO_BASE_URL)에서 읽는다. 업로드 인증은 gh CLI 가 담당한다
# (`gh auth login --hostname <ghe-host>` 또는 GH_HOST + GH_TOKEN). 선택적 APP_GH_REPO 로
# 레포를 명시할 수 있다(미설정 시 gh 가 local git origin 에서 추론).

param(
    [ValidateSet("qa", "prod")][string]$Channel,
    [switch]$Upload,
    [switch]$Force,
    [string]$Notes = ""
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root

# Channel is mandatory (explicit selection enforced — no accidental prod builds).
# ValidateSet checks the value when present; this throw catches omission without
# triggering an interactive Mandatory prompt (which would hang -NonInteractive).
if (-not $Channel) {
    throw "ERROR: -Channel qa|prod is required. (qa = mock on / auto-update off, prod = release build)"
}
Write-Host "==> channel   : $Channel"
# App.spec reads APP_BUILD_CHANNEL to bake the channel into the bundled .env.
$env:APP_BUILD_CHANNEL = $Channel

# 0. Pre-flight checks
if (-not $Force) {
    # Check for uncommitted changes
    $gitStatus = git status --porcelain
    if ($gitStatus) {
        Write-Host "ERROR: Git working directory is not clean. Commit your changes before releasing, or use -Force to bypass." -ForegroundColor Red
        Write-Host $gitStatus -ForegroundColor Yellow
        exit 1
    }
}

# Ensure output directories exist.
New-Item -ItemType Directory -Force -Path "build", "release" | Out-Null

# Load .env file into environment variables
$envPath = Join-Path $root ".env"
if (Test-Path $envPath) {
    Write-Host "==> loading .env configuration"
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
Write-Host "==> app name  : $AppName"

# 1. Read version from pyproject.toml (for latest.json / EXE filename)
$pyproject = Get-Content "pyproject.toml" -Raw
if ($pyproject -notmatch '(?m)^version\s*=\s*"([^"]+)"') {
    throw "version field not found in pyproject.toml"
}
$version = $Matches[1]
Write-Host "==> version   : $version"


# 2. frontend build -> build/web/
Write-Host "==> frontend build  (-> build/web/)"
Push-Location frontend
npm run build
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "frontend build failed" }
Pop-Location

# 3. extension frontends -> extensions/<tool>/frontend/dist/  (App.spec 가 번들)
# 각 확장의 SPA 를 빌드해 dist/ 를 만든다. App.spec 은 dist/ 가 "있을 때만" 번들하므로,
# 여기서 빌드하지 않으면 stale/누락 dist 가 EXE 에 들어간다. 확장은 폴더 컨벤션으로
# 자동 발견되므로 새 확장을 추가해도 이 스크립트 수정은 불필요하다.
# 한 확장의 빌드 실패는 메인 앱 릴리즈를 막지 않는다(격리 원칙 — 경고 후 계속;
# App.spec 은 그 경우 기존 dist/ 만 번들하거나, 없으면 건너뛴다).
Write-Host "==> extension builds  (-> extensions/*/frontend/dist/)"
$extRoot = Join-Path $root "extensions"
if (Test-Path $extRoot) {
    Get-ChildItem $extRoot -Directory |
        Where-Object { $_.Name -notmatch '^[._]' -and $_.Name -ne 'tracer' } |
        ForEach-Object {
            $extName = $_.Name
            $feDir = Join-Path $_.FullName "frontend"
            if (-not (Test-Path (Join-Path $feDir "package.json"))) {
                return  # 프론트가 없는 확장(라우터 전용)은 건너뛴다
            }
            Write-Host "    - $extName"
            Push-Location $feDir
            try {
                if (-not (Test-Path "node_modules")) {
                    if (Test-Path "package-lock.json") { npm ci } else { npm install }
                    if ($LASTEXITCODE -ne 0) { throw "dependency install failed" }
                }
                npm run build
                if ($LASTEXITCODE -ne 0) { throw "vite build failed" }
            } catch {
                Write-Host "    WARNING: extension '$extName' build skipped: $_" -ForegroundColor Yellow
                Write-Host "             (App.spec bundles existing dist/ only -- isolation principle)" -ForegroundColor Yellow
            } finally {
                Pop-Location
            }
        }
} else {
    Write-Host "    (no extensions/ dir -- skip)"
}

# 4. Updater.exe -> build/updater/Updater.exe
Write-Host "==> updater build   (-> build/updater/)"
uv run pyinstaller --noconfirm --clean `
    --distpath build/updater `
    --workpath build/pyi-updater `
    packaging/Updater.spec
if ($LASTEXITCODE -ne 0) { throw "updater build failed" }

if (-not (Test-Path "build/updater/Updater.exe")) {
    throw "build/updater/Updater.exe was not created"
}

# 5. App EXE -> release/{AppName}.exe
Write-Host "==> app build       (-> release/)"
uv run pyinstaller --noconfirm --clean `
    --distpath release `
    --workpath build/pyi-app `
    packaging/App.spec
if ($LASTEXITCODE -ne 0) { throw "app build failed" }

$exePath = "release/$AppName.exe"
if (-not (Test-Path $exePath)) {
    throw "$exePath was not created"
}

# 6. sha256 + latest.json
$sha256 = (Get-FileHash $exePath -Algorithm SHA256).Hash.ToLower()
$size   = (Get-Item $exePath).Length
$releasedAt = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")

$versionedName = "$AppName-$version.exe"
$versionedPath = "release/$versionedName"
Copy-Item $exePath $versionedPath -Force

$_repoBase = $env:APP_REPO_BASE_URL
if (-not $_repoBase) { $_repoBase = "https://nexus.internal/repository/$($AppName.ToLower())" }
$_repoBase = $_repoBase.TrimEnd('/')

$latest = [ordered]@{
    version               = $version
    # GitHub Release 의 버전-핀 에셋 경로. _repoBase = repo 루트(.../<org>/<repo>).
    # 버전을 박아 결정론적으로 받게 한다(latest 포인터의 race 회피).
    url                   = "$_repoBase/releases/download/v$version/$AppName.exe"
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

# 7. publish — GitHub Release via gh CLI.
# gh 가 local git origin(=GHE 앱 레포)에서 레포를 추론하고 태그 v$version 을 생성한다.
# qa 는 --prerelease 라 prod 의 releases/latest 포인터에 잡히지 않는다(prod EXE 격리).
# 인증은 gh 가 담당한다: `gh auth login --hostname <ghe-host>` 또는
# GH_HOST + GH_TOKEN(write PAT) 환경변수. write 토큰은 .env/EXE 에 두지 않는다.
if ($Upload) {
    Write-Host "==> publishing GitHub release ($Channel) via gh CLI"
    $tag = "v$version"
    $ghArgs = @(
        "release", "create", $tag,
        "--title", $tag,
        "--notes", $Notes,
        $versionedPath, $exePath, $latestJsonPath
    )
    if ($Channel -eq "qa") { $ghArgs += "--prerelease" }
    if ($env:APP_GH_REPO) { $ghArgs += @("--repo", $env:APP_GH_REPO) }
    & gh @ghArgs
    if ($LASTEXITCODE -ne 0) { throw "gh release create failed (exit $LASTEXITCODE)" }
    Write-Host "    released $tag"
} else {
    Write-Host ""
    Write-Host "Skipping publish. Add -Upload flag to create the GitHub release."
}
