# packaging/release.ps1
#
# Steps:
#   1. Read version from pyproject.toml (App.spec generates _version.py at build time)
#   2. Frontend build (Vite)             -> build/web/
#   3. Extension frontends (Vite)        -> extensions/*/frontend/dist/  (bundled by App.spec)
#   4. Updater.exe build                 -> build/updater/Updater.exe
#   5. App EXE build                     -> release/{AppName}.exe
#   6. Compute sha256 + generate          release/latest.json
#   7. Upload to remote raw repo (currently Nexus; requires -Upload flag)
#
# App name is read automatically from the name= field in packaging/App.spec.
# To rename the output EXE, change name='...' in packaging/App.spec — no other edits needed.
#
# Output layout:
#   build/    intermediate artifacts (bundled into the EXE, never uploaded)
#   release/  final artifacts (uploaded to the remote repo)
#
# Usage:
#   pwsh packaging/release.ps1
#   pwsh packaging/release.ps1 -Upload -Notes "변경사항 요약"
#
# 저장소 URL/자격증명은 .env(APP_REPO_BASE_URL, APP_REPO_USER, APP_REPO_PASSWORD)에서 읽는다.
# 업로드 실행은 packaging/upload.py 에 위임된다.

param(
    [switch]$Upload,
    [switch]$Force,
    [string]$Notes = ""
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root

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
        Where-Object { $_.Name -notmatch '^[._]' } |
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
    url                   = "$_repoBase/$AppName.exe"
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

# 7. upload — Python 스크립트에 위임 (프록시·SSL 설정은 upload.py 에서 처리)
if ($Upload) {
    Write-Host "==> uploading via packaging/upload.py"
    uv run packaging/upload.py
    if ($LASTEXITCODE -ne 0) { throw "upload failed (packaging/upload.py exited $LASTEXITCODE)" }
} else {
    Write-Host ""
    Write-Host "Skipping upload. Add -Upload flag to push to the remote repo."
}
