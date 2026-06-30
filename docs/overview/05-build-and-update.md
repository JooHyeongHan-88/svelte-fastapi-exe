# ⑤ 빌드 & 배포 & 자동 업데이트

> **대상 독자**: 빌드 파이프라인·릴리즈·업데이트 메커니즘을 파악하려는 개발자
> **이 문서의 목표**: `.env` 단일 진실 공급원 → 빌드 파이프라인 → GitHub Enterprise Releases 배포
> → 자동 업데이트 전 과정을 이해한다.

---

## 1. 빌드 & 릴리즈 파이프라인 (`packaging/release.ps1`)

`pwsh packaging/release.ps1 -Channel <qa|prod>` 한 줄이 아래 단계를 순서대로 수행한다.
**`-Channel`은 필수**다 — 생략하면 즉시 에러로 막힌다 (qa/prod 빌드를 혼동하지 않게).

```
[사전 검사]  -Channel 확인(생략 시 throw) → APP_BUILD_CHANNEL 주입 · git tree clean 확인(-Force 우회) · .env 로드
     │
① 버전 확인          pyproject.toml version 읽기 (App.spec이 빌드 시 _version.py 생성)
② 메인 Frontend 빌드  npm run build → build/web/
③ 확장 Frontend 빌드  extensions/*/frontend → 각 dist/  (App.spec 보다 먼저 — 폴더 컨벤션 자동 발견, 격리)
④ Updater 빌드     PyInstaller(Updater.spec) → build/updater/Updater.exe
⑤ App EXE 빌드     PyInstaller(App.spec) → release/{AppName}.exe  (채널별 번들)
⑥ 메타데이터 생성   EXE sha256·크기 계산 → release/latest.json
⑦ 업로드 (선택)     -Upload 시 gh release create — EXE 먼저, latest.json 마지막 순서
```

> **③ 확장 Frontend 빌드가 ⑤ App.spec 보다 먼저**여야 한다. App.spec은 `frontend/dist`가
> "있을 때만" 번들하므로, 빌드를 건너뛰면 stale/누락 dist가 EXE에 박힌다. 한 확장의 빌드
> 실패는 메인 릴리즈를 막지 않는다 (경고 후 계속 — 격리).

### 빌드 채널 — qa vs prod

`-Channel` 값(`APP_BUILD_CHANNEL`로 EXE에 주입)이 빌드의 성격을 결정한다.

| 채널 | Mock 시나리오 | 자동 업데이트 | 콘텐츠 동기화 브랜치 | 릴리즈 게시 |
|---|---|---|---|---|
| `qa` | **노출** (하니스·UI 검증용) | **차단** | `dev` | `--prerelease` (releases/latest 포인터에 안 잡힘) |
| `prod` | 제외 | 활성 | `main` | full release (releases/latest 갱신) |

qa를 `--prerelease`로 올리는 이유: prod EXE가 QA 빌드를 업데이트로 오인하지 않게 격리하기 위함.

**`App.spec`이 EXE에 내장하는 것** (`sys._MEIPASS`로 임베드):

| 내장 항목 | 이유 |
|---|---|
| `build/web/` → `web/` | 프론트 정적 자산 |
| `build/updater/Updater.exe` → `updater/` | 자가 교체용 헬퍼 |
| `PROMPTS/` `SKILLS/` `AGENTS/` | 에이전트 동작 정의 (파일 추가만으로 다음 빌드 반영) |
| `.env` | 빌드 시점 설정 박제 |
| `backend/scripts/` 전체 서브모듈 | `collect_submodules('scripts')` 자동 수집 |
| `APP_ALLOWED_LIBRARIES`의 각 패키지 | `.env`를 읽어 `collect_all()` — **env 한 줄 = 번들 자동 포함** |
| `extensions/<tool>/backend` + `frontend/dist` | 확장 도구 — 폴더 글롭으로 **있을 때만** 선별 번들 (런타임 필요분만, src·node_modules·tests 제외) |

업로드는 `gh release create`로 GitHub Enterprise에 게시한다. 순서가 "EXE 먼저,
latest.json 마지막"인 이유: 메타데이터가 먼저 올라가면 클라이언트가 아직 존재하지 않는
EXE(404)를 다운로드하려고 시도할 수 있기 때문. 업로드 인증은 gh CLI(쓰기 PAT)가 담당하며,
**쓰기 토큰은 소스 `.env`·EXE에 두지 않는다**.

> EXE 빌드 없이 메인·확장 프론트만 빌드해 backend 정적 서빙으로 확인하는 `build-dev.ps1`도 제공된다.

---

## 2. 자동 업데이트 구조

배포 후 재설치 없이 새 버전이 도달하는 메커니즘. 저장소는 **GitHub Enterprise Releases**이며,
**다운로드 무결성(sha256)과 실행 파일 잠금 문제**를 모두 처리한다.

```
① 확인     GHE REST API GET {api_base}/repos/{owner}/{repo}/releases/latest (5분 캐시)
            └ owner/repo·api_base 는 APP_REPO_BASE_URL 에서 유도, 읽기 PAT 로 인증
            └ assets[] 에서 latest.json 을 octet-stream 으로 받아 파싱 → EXE 에셋 url 역참조
            └ URL prefix·sha256 형식 검증 실패 시 조용히 "업데이트 없음" 처리
            └ QA 채널은 이 단계 직전 즉시 차단 (네트워크 호출 0회)
② 적용     EXE 에셋을 REST API(assets/{id} + octet-stream + PAT)로 스트리밍 다운로드
            → sha256 검증 → {이름}.new.exe 로 스테이징
            └ Updater.exe 를 분리(DETACHED) 프로세스로 실행 후 1초 뒤 서버 자진 종료
③ 대기     Updater.exe 가 부모 프로세스 종료를 폴링 (최대 60초 + 3초 추가 유예)
④ 교체     rename-to-backup 전략:
            현재.exe → .old (rename은 잠긴 파일도 허용)
            → new.exe → 현재.exe → 새 버전 재기동
            → 실패 시 .old 복원 후 기존 버전 재기동 (롤백)
```

`os.replace` 직접 덮어쓰기가 아닌 **rename-to-backup**인 이유: 방금 종료된 EXE의 잔존
파일 잠금 + 백신 스캔 때문에 직접 교체는 `ACCESS_DENIED`가 발생한다. rename은 잠긴
파일에도 허용되므로 30회 × 0.5초 재시도로 안전하게 교체한다.

> **private 레포 다운로드 주의**: 릴리즈 에셋을 브라우저 다운로드 URL로 받으면 PAT 헤더가
> 무시돼 private 레포에서 404가 난다. 반드시 REST API 에셋 엔드포인트(`assets/{id}`)에
> `Accept: application/octet-stream` 헤더로 받아야 인증이 통한다 — latest.json의 `url`은
> 다운로드가 아닌 EXE 파일명 추출용으로만 쓴다.

사용자 화면에는 업데이트 배너 → 진행률 모달(다운로드/검증/재시작)로 표시된다
(→ [③ 구현된 UX/UI](03-ux-ui.md)).

---

## 3. 콘텐츠 동기화 — SKILLS/AGENTS/PROMPTS 런타임 갱신

EXE 재빌드 없이 에이전트 콘텐츠를 갱신하는 메커니즘. **frozen EXE가 기동 시 매핑된
GitHub 브랜치에서 마크다운을 가져와** SKILLS/AGENTS/PROMPTS를 갱신한다.

```
frozen 기동 → sync_agent_content()  (updater와 같은 레포·PAT·TLS 공유)
  ① 게이트   dev이거나 동기화 비활성이면 네트워크 0회로 즉시 종료
  ② 비교     채널 매핑 브랜치(qa→dev, prod→main)의 디렉터리 목록을 Contents REST API 로 조회
  ③ 증분     manifest(blob sha) 와 비교해 변경/신규 .md 만 Blobs REST API 로 받음
  ④ 반영     전부 성공할 때만 디스크 반영 (all-or-nothing — 반쪽 동기화 방지)
            저장 위치: %APPDATA%/{APP_NAME}/content/{PROMPTS,SKILLS,AGENTS}/
```

- **graceful degradation**: 네트워크·404(브랜치 부재)·TLS·파싱 어떤 실패도 raise 하지
  않고 직전 성공분(last-good) → 번들 콘텐츠로 폴백한다. **`dev` 브랜치가 없어도 부팅은
  깨지지 않는다.** App.spec의 PROMPTS/SKILLS/AGENTS 번들은 그대로 유지(안전망).
- 콘텐츠도 updater와 같은 이유로 **raw·브라우저 URL이 아니라 Contents/Blobs REST API + PAT**로
  받는다 (private 레포에서 PAT 무시·404 회피).
- dev는 동기화하지 않는다 — 로컬 워킹트리 + mtime 핫리로드를 그대로 쓴다.

---

## 4. 환경 변수 — `.env` 단일 진실 공급원

`.env` 파일 하나가 **dev 런타임·EXE 빌드·릴리즈 스크립트** 세 곳에서 공통으로 읽힌다.

```
.env ──┬─ backend (load_dotenv)        : 런타임 상수
       ├─ frontend (vite.config.js)    : dev 프록시 타겟 (APP_DEV_PORT)
       ├─ packaging/App.spec           : EXE 이름·번들 라이브러리·채널(APP_BUILD_CHANNEL) 주입
       └─ packaging/release.ps1        : 앱 이름·릴리즈 게시 (업로드 쓰기 토큰은 gh CLI 가 별도 관리)
```

frozen EXE는 빌드 시 박제된 `.env`를 `override=False`로 읽으므로, **OS 환경 변수가
있으면 그쪽이 우선**한다 — 런타임 임시 오버라이드는 가능하지만 근본 변경은 재빌드가 필요하다.
값 뒤의 `# 인라인 주석`은 파서가 자동 제거한다.

### 주요 환경 변수 (기능 그룹별)

**앱 정체성·네트워크**

| 변수 | 기본값 | 의미 |
|---|---|---|
| `APP_NAME` | `MyAgent` | EXE 파일명, `%APPDATA%` 하위 폴더명, settings.json 경로. **앱 이름 변경은 이 값 하나만 바꾸면 끝** |
| `APP_PORT` | (APP_NAME 해시) | **frozen 전용** 고정 포트. 기본값 `47100 + sha256(APP_NAME) % 1900`. `0`이면 동적 할당. 충돌 시 +1..+4 폴백 체인 — `core.server_socket` |
| `APP_DEV_PORT` | `8765` | dev 전용 백엔드 포트 (Vite 프록시 타겟과 공유). frozen은 `APP_PORT` 또는 APP_NAME 해시 기반 고정 포트를 쓴다 |

**생명주기 (presence/watchdog)**

| 변수 | 기본값 | 의미 |
|---|---|---|
| `APP_STARTUP_GRACE` | `60` | 첫 브라우저 연결까지 기다리는 상한 (초) |
| `APP_SHUTDOWN_GRACE` | `2` | 마지막 클라이언트가 사라진 후 서버 종료까지 대기 (초) |
| `APP_PRESENCE_RECONNECT_GRACE` | `2` | F5·네트워크 블립 시 재연결 허용 유예 (초) |
| `APP_PRESENCE_KEEPALIVE_INTERVAL` | `30` | SSE ping 주기 — 중간 프록시 idle timeout 방지 (초) |

**LLM·에이전트 한도**

| 변수 | 기본값 | 의미 |
|---|---|---|
| `APP_LLM_PROVIDER` | `mock` | 최초 기동 시 settings.json 시드값 (`mock` \| `dtgpt` \| `openai_compatible`) |
| `APP_DTGPT_BASE_URL` | — | DTGPT 엔드포인트 (UI 비노출, 환경 변수로 고정 주입) |
| `APP_LLM_TEMPERATURE` / `APP_LLM_MAX_TOKENS` | `0.7` / 무제한 | 생성 파라미터 (UI 비노출) |
| `APP_MAX_AGENT_ITERATIONS` | `12` | 한 턴당 provider→도구 반복 상한 |
| `APP_MAX_AGENT_CALLS_PER_TURN` | `20` | 오케스트레이터+서브 에이전트 합산 LLM 호출 예산 |
| `APP_MAX_PARALLEL_SUBAGENTS` | `3` | 병렬 서브 에이전트 동시 실행 상한 |
| `APP_TOOL_DEFAULT_TIMEOUT` | `30` | 도구 1회 실행 타임아웃 (초) |
| `APP_MAX_HISTORY_MESSAGES` | `40` | 클라이언트당 보관하는 대화 히스토리 상한 |
| `APP_ALLOWED_LIBRARIES` | `scripts,polars` | 에이전트 런타임에 노출할 Python 패키지 CSV — **EXE 빌드 시 자동 번들링**. 나열 순서는 해석 우선순위와 무관 (현재 `.env`는 `scripts,numpy,polars,pandas`) |
| `APP_NAMESPACE_MEMORY_THRESHOLD` / `APP_NAMESPACE_MAX_VARS` | `10MB` / `20` | 세션 namespace 변수의 in-memory 한계·개수 상한 (초과분 디스크 spill) |
| `APP_ORCHESTRATOR_API_REFS` | (빈 값) | 오케스트레이터 baseline api_refs CSV — 활성 SKILL 없이도 그 함수 시그니처·docstring 을 `# Available Library APIs` 로 상시 주입. 빈 값=기존(SKILL 주도) 동작, 잘못된 경로는 skip(무오류) |

**업데이트·배포 저장소 (GitHub Enterprise Releases)**

| 변수 | 기본값 | 의미 |
|---|---|---|
| `APP_REPO_BASE_URL` | — | GHE 레포 루트 URL — updater가 REST API base(`.../api/v3`)·owner/repo 유도 |
| `APP_REPO_READ_TOKEN` | — | **읽기 전용** Classic PAT (scope: repo). EXE에 번들 — 릴리즈 메타·EXE 다운로드·콘텐츠 동기화 인증 공용. 업로드용 쓰기 토큰은 gh CLI가 별도 관리 |
| `APP_BUILD_CHANNEL` | (`qa`/`prod`) | App.spec이 release.ps1 `-Channel`에서 주입 — 소스 `.env`에 두지 않음. Mock 노출·업데이트·콘텐츠 브랜치를 결정 (1절 표) |
| `APP_REPO_TLS_VERIFY` | `true` | 사내 자체 서명 CA로 SSLError 시 `false` (Windows는 시스템 인증서 저장소 자동 사용 — 보통 불필요) |
| `APP_UPDATE_CHECK_TIMEOUT` / `APP_UPDATE_DOWNLOAD_TIMEOUT` | `5` / `60` | 릴리즈 메타 GET · EXE 다운로드 타임아웃 (초) |
| `APP_UPDATE_CHECK_CACHE_TTL` | `300` | 릴리즈 메타 확인 캐시 (초) |

**콘텐츠 동기화 (3절)**

| 변수 | 기본값 | 의미 |
|---|---|---|
| `APP_CONTENT_SYNC_ENABLED` | frozen=`true`, dev=`false` | frozen 기동 시 SKILLS/AGENTS/PROMPTS를 원격 브랜치에서 동기화 (실패 시 번들 폴백) |
| `APP_CONTENT_SYNC_BRANCH` | — | 채널 매핑(qa→dev, prod→main) 무시하고 이 브랜치 강제 — frozen 카나리 검증용 |
| `APP_CONTENT_SYNC_TIMEOUT` | `5` | 기동 시 콘텐츠 동기화 블로킹 상한 (초) |

**디버그 (dev 전용)**

| 변수 | 기본값 | 의미 |
|---|---|---|
| `APP_DEBUG_TRACE` | `false` | 켜면 턴마다 provider wire in/out + 하니스 결정점을 `result/<session>/_trace/<turn>.jsonl`에 기록 → **tracer 확장**(패널 런처)에서 타임라인 조회. frozen EXE는 강제 비활성 |

> 전체 목록과 정확한 로딩 위치: `backend/core/config.py`, `backend/agent/config.py`

---

**이전 문서**: [④ Backend 동작 흐름](04-backend-flow.md)
