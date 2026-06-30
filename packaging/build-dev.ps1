# packaging/build-dev.ps1
#
# Dev frontend build — builds ALL frontends (main + every extension incl. tracer)
# so the backend can serve them locally without running the Vite dev server.
#
# Unlike release.ps1 this does NOT build the EXE/updater, bake a channel, check git,
# or upload. It only produces the static frontend bundles the backend serves:
#   frontend              -> build/web/                          (backend serves at /)
#   extensions/*/frontend -> extensions/<tool>/frontend/dist/    (served at /ext/<tool>/)
#
# tracer(디버그 뷰어)는 dev 전용이라 release.ps1 은 제외하지만, 이 dev 빌드는 포함한다.
#
# Usage:
#   pwsh packaging/build-dev.ps1
#
# After building, run the backend to serve everything:
#   uv run python backend/main.py

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root

# 1. main frontend -> build/web/  (essential — failure is fatal)
Write-Host "==> frontend build  (-> build/web/)"
Push-Location frontend
try {
    if (-not (Test-Path "node_modules")) {
        if (Test-Path "package-lock.json") { npm ci } else { npm install }
        if ($LASTEXITCODE -ne 0) { throw "dependency install failed" }
    }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "frontend build failed" }
} finally {
    Pop-Location
}

# 2. extension frontends -> extensions/<tool>/frontend/dist/
# 폴더 컨벤션으로 자동 발견하므로 새 확장을 추가해도 이 스크립트 수정은 불필요하다.
# release.ps1 과 달리 tracer 를 제외하지 않는다(dev 디버그 뷰어). 한 확장의 빌드 실패는
# 다른 확장·dev 흐름을 막지 않는다(격리 원칙 — 경고 후 계속).
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
            } finally {
                Pop-Location
            }
        }
} else {
    Write-Host "    (no extensions/ dir -- skip)"
}

Write-Host ""
Write-Host "==> done. Serve with:  uv run python backend/main.py"
