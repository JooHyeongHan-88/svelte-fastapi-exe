# 업데이트 & 릴리즈 아키텍처

## 자동 업데이트 — 4단계 흐름

```
① check_latest()    GitHub REST API: GET {api_base}/repos/{owner}/{repo}/releases/latest
                    (api_base·owner·repo 는 APP_REPO_BASE_URL 에서 유도, 5분 캐시)
                    → assets[] 에서 latest.json 에셋의 API url 찾아 octet-stream 으로 받아 파싱
                    → 같은 응답에서 EXE 에셋 API url 역참조해 meta["_download_url"] stash
                    QA 채널은 이 단계 직전 즉시 차단(update_available=False, 네트워크 호출 없음)
                    url(브라우저) prefix·sha256 hex(64자) 검증 → 실패 시 silently False
② apply_update()    meta["_download_url"](EXE 에셋 API url)을 read-only PAT + octet-stream 으로
                    인증 스트리밍 다운로드 → sha256 검증 → {stem}.new.exe staging
                    → DETACHED Updater.exe Popen(pid, new, current) → 1s 후 server.should_exit
③ Updater.exe       부모 pid 폴링(최대 60s) → POST_EXIT_GRACE 3s 추가 대기
④ rename-to-backup  current → .old (rename은 잠긴 파일도 허용)
                    → new → current → 실패 시 .old 복원 후 재기동
                    → 새 EXE spawn 후 .old 재시도 삭제(cleanup_backup, 잠금 풀릴 때까지)
                      + SHChangeNotify 로 탐색기 강제 새로고침(notify_shell)
                    → 새 EXE 기동 시 cleanup_stale_backup 이 잔존 .old 1회 스윕(안전망)
```

**절대 변경 금지 ①**: 방금 종료된 EXE의 잔존 잠금 + AV 스캔 때문에 `os.replace(new, current)` 직접 시도는
`ERROR_ACCESS_DENIED` 발생. **rename-to-backup 전략**으로 30회 × 0.5s 재시도. 이 전략으로 회귀시키지 말 것.

**절대 변경 금지 ② (private 레포 다운로드 경로)**: 릴리즈 에셋을 브라우저 다운로드 URL
(`.../releases/latest/download/<asset>` 또는 `.../releases/download/<tag>/<asset>`)로 받지 말 것.
그 경로는 **웹 세션 쿠키 인증 전용**이라 `Authorization: token <PAT>` 헤더를 무시하고, private 레포면
**404**(403 아님 — 존재 은닉)를 돌려준다. 반드시 REST API 에셋 엔드포인트
(`.../api/v3/repos/.../releases/assets/{id}`)에 `Accept: application/octet-stream` 헤더로 받아야
PAT 인증이 통하고 바이너리 본문이 온다(octet-stream 없으면 에셋 메타데이터 JSON 반환). latest.json 의
`url`(브라우저 경로)은 **다운로드에 쓰지 않고 EXE 파일명 추출용**으로만 쓴다(`_exe_asset_name`).

진행 상태: `GET /api/update/status` → `{status, progress, total, message, target_version}`  
(`idle|downloading|verifying|staging|restarting|error`)

### httpx TLS 동작

- `APP_REPO_TLS_VERIFY=false`: SSL 검증 비활성화 (사내 자체 서명 CA 최후 수단).
- Windows frozen: `ssl.create_default_context()`로 Windows 인증서 저장소를 사용 — certifi가 읽지 못하는 사내 CA를 자동 신뢰. 인증서 관리자가 CA를 Windows에 등록하면 이 설정 불필요.
- Linux/Mac(dev): certifi 기본값.
- `github_api.SSL_VERIFY`(공용 모듈 상수) → updater·content_sync 의 모든 `httpx.Client` 에 적용.
  인증 헤더(`auth_headers`/`api_headers`)와 함께 `core/github_api.py` 로 공용화돼 있다.

---

## 콘텐츠 동기화 — SKILLS/AGENTS/PROMPTS 런타임 갱신 (`backend/core/content_sync.py`)

frozen EXE 가 **기동 시 매핑된 GitHub 브랜치에서 마크다운을 가져와** EXE 재빌드 없이 콘텐츠를
갱신한다. updater 와 같은 private 레포·PAT·TLS 를 쓰므로 인증/SSL 헬퍼는 `core/github_api.py`
(`auth_headers`·`api_headers`·`SSL_VERIFY`)로 공용화돼 있다.

| 빌드 | 콘텐츠 소스 |
|---|---|
| dev (비-frozen) | 로컬 워킹트리 (동기화 안 함 — mtime 핫리로드 유지) |
| frozen `qa` | 원격 `dev` 브랜치 |
| frozen `prod` | 원격 `main` 브랜치 |

채널 매핑은 `_target_branch()`(qa→dev, prod→main). `APP_CONTENT_SYNC_BRANCH` 로 오버라이드해
**`dev` 를 보는 prod-맥락 카나리** 검증이 가능하다. `main.py` 가 레지스트리 `load()` **직전에**
`sync_agent_content()` 를 호출하고, 반환된 디렉터리로 `prompt/skill/agent_registry.use_directory()`
재지정한다(빈 dict 면 번들 그대로).

```
sync_agent_content() -> dict[str, Path]
 ① 게이트: not frozen | CONTENT_SYNC_ENABLED=false | owner·repo 미설정 → {} (네트워크 0회)
 ② 각 디렉터리: GET /repos/{o}/{r}/contents/<DIR>?ref=<branch> (JSON+PAT) → .md·blob 만, 파일명 검증
 ③ manifest(.manifest.json) 의 blob sha 와 비교 → 변경/신규만 GET /git/blobs/<sha> (base64) — 증분
 ④ 전부 성공 시에만 디스크 반영 + manifest 갱신 (all-or-nothing — 반쪽 동기화 방지)
 ⑤ 효과 디렉터리 = manifest 와 디스크가 정합할 때만 content/<DIR>, 아니면 {} (last-good→번들)
```

- **저장 위치**: `%APPDATA%/{APP_NAME}/content/{PROMPTS,SKILLS,AGENTS}/` + `.manifest.json`
  (settings.json·workspace·result 와 동일 패턴 — MEIPASS 는 read-only 라 그곳에 못 쓴다).
- **graceful degradation**: 네트워크·404(브랜치/디렉터리 부재)·TLS·파싱 어떤 실패도 `raise` 하지
  않고 last-good(직전 성공분) → 번들로 내려간다. **`dev` 브랜치가 없어도 부팅은 깨지지 않는다.**
- **절대 변경 금지 ③**: 콘텐츠도 `download_url`(raw 호스트)·브라우저 URL 로 받지 말 것 — private
  레포에서 PAT 가 무시돼 404. 반드시 Contents/Blobs REST API + PAT 헤더(`②③`).
- **path 안전성**: 원격이 준 파일명에 경로 구분자·`..`·dotfile 이 있으면 거부 후에만 디스크 기록.

> **App.spec 의 PROMPTS/SKILLS/AGENTS 번들은 그대로 유지**된다 — 동기화 실패 시 폴백(안전망).
> 테스트: `backend/tests/test_content_sync.py`.

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
- **dev 프론트 빌드**: `build-dev.ps1` 은 EXE/업데이터·업로드 없이 메인+확장 프론트만 빌드해
  backend 정적 서빙(`build/web/`·`/ext/<tool>/`)으로 확인하게 한다. release.ps1 과 달리 `tracer`
  (dev 디버그 뷰어)도 포함한다.

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
