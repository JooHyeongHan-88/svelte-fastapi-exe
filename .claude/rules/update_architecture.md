# 업데이트 & 릴리즈 아키텍처

## 자동 업데이트 — 4단계 흐름

```
① check_latest()    APP_LATEST_JSON_URL(GitHub Releases) GET, 5분 캐시
                    QA 채널은 이 단계에서 즉시 차단(update_available=False, 네트워크 호출 없음)
                    URL prefix(REPO_BASE_URL startswith)·sha256 hex(64자) 검증 → 실패 시 silently False
② apply_update()    APP_REPO_READ_TOKEN(read-only PAT)으로 인증 스트리밍 다운로드
                    → sha256 검증 → {stem}.new.exe staging
                    → DETACHED Updater.exe Popen(pid, new, current) → 1s 후 server.should_exit
③ Updater.exe       부모 pid 폴링(최대 60s) → POST_EXIT_GRACE 3s 추가 대기
④ rename-to-backup  current → .old (rename은 잠긴 파일도 허용)
                    → new → current → 실패 시 .old 복원 후 재기동
```

**절대 변경 금지**: 방금 종료된 EXE의 잔존 잠금 + AV 스캔 때문에 `os.replace(new, current)` 직접 시도는
`ERROR_ACCESS_DENIED` 발생. **rename-to-backup 전략**으로 30회 × 0.5s 재시도. 이 전략으로 회귀시키지 말 것.

진행 상태: `GET /api/update/status` → `{status, progress, total, message, target_version}`  
(`idle|downloading|verifying|staging|restarting|error`)

### httpx TLS 동작

- `APP_REPO_TLS_VERIFY=false`: SSL 검증 비활성화 (사내 자체 서명 CA 최후 수단).
- Windows frozen: `ssl.create_default_context()`로 Windows 인증서 저장소를 사용 — certifi가 읽지 못하는 사내 CA를 자동 신뢰. 인증서 관리자가 CA를 Windows에 등록하면 이 설정 불필요.
- Linux/Mac(dev): certifi 기본값.
- `_make_ssl_verify()` / `_SSL_VERIFY` 모듈 상수 → `updater.py` 의 두 `httpx.Client` 모두 적용.

---

## Release 빌드 순서 (extensions 포함)

`release.ps1` 빌드 순서: ① `-Channel` 확인(생략 시 즉시 에러) + `APP_BUILD_CHANNEL` 주입 → ② pyproject 버전 읽기 → ③ **메인 프론트**(`frontend` → `build/web/`)
→ ④ **확장 프론트**(`extensions/*/frontend` → 각 `dist/`) → ⑤ Updater.exe → ⑥ App EXE(App.spec — 채널 번들)
→ ⑦ sha256·latest.json → ⑧ `gh release create`(`-Upload`).

- **③ 확장 프론트 빌드가 ⑤ App.spec 보다 먼저**여야 한다. `App.spec` 은 `extensions/<tool>/frontend/dist`
  가 **있을 때만** 번들하므로(→ `extensions_architecture.md`), 빌드를 건너뛰면 stale/누락 dist 가
  EXE 에 박힌다. 확장은 폴더 컨벤션(`*/frontend/package.json`)으로 자동 발견 — 새 확장을 추가해도
  release.ps1 수정 불필요.
- **격리**: 한 확장의 `npm` 빌드 실패는 메인 앱 릴리즈를 막지 않는다(경고 후 계속). App.spec 은 그 경우
  기존 dist 만 번들하거나, 없으면 그 확장을 건너뛴다(빈손 no-op).
- `node_modules` 부재 시에만 설치(`package-lock.json` 있으면 `npm ci`, 없으면 `npm install`) 후 `npm run build`.
- `release-dryrun.ps1` 은 release.ps1 을 호출하므로 확장 빌드를 그대로 상속하며, 끝에 각 확장의
  `dist`/`router` 번들 존재를 확인 출력한다. 수동 검증 시나리오 `[E]` 가 `/ext/<tool>/` 진입을 안내한다.

## Release 스크립트 — PowerShell 5.1 주의점

- `param()` 블록은 **반드시 첫 실행문** (앞에 `[Console]::OutputEncoding=` 두면 파싱 에러)
- `-Channel` 파라미터: `[ValidateSet("qa","prod")]` + 생략 시 `throw`(인터랙티브 Mandatory 프롬프트 방지)
- `latest.json`은 **BOM 없는 UTF-8** — `[System.IO.File]::WriteAllText(path, content, (New-Object System.Text.UTF8Encoding $false))` 사용  
  (`Set-Content -Encoding utf8`은 BOM 붙어 JSON 파싱 실패)
- `backend/_version.py`는 gitignored 생성물. **App.spec이 Analysis 전에** `tomllib`으로 pyproject.toml 파싱 후 자동 생성한다. release.ps1은 더 이상 이 파일을 쓰지 않는다.
- `Write-Host` 한글 깨짐 → 스크립트 출력은 영어 유지
- **업로드 인증**: `gh auth login --hostname <ghe-host>` 또는 `GH_HOST`+`GH_TOKEN`(write PAT) 환경변수. `.env`/EXE에 쓰기 토큰을 두지 않는다.
- **QA vs Prod 채널**:
  - `qa`: `gh release create --prerelease` → `releases/latest` 포인터에 잡히지 않음 (prod EXE가 QA 빌드를 업데이트로 인식하는 것 방지)
  - `prod`: full release → `releases/latest/download/latest.json` 포인터 갱신
- `latest.json`의 `url` 필드는 **버전 핀 경로** (`releases/download/v{version}/{AppName}.exe`) — `releases/latest` 포인터 race 조건 회피
