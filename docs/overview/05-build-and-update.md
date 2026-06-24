# ⑤ 빌드 & 배포 & 자동 업데이트

> **대상 독자**: 빌드 파이프라인·릴리즈·업데이트 메커니즘을 파악하려는 개발자
> **이 문서의 목표**: `.env` 단일 진실 공급원 → 빌드 파이프라인 → Nexus 배포 → 자동 업데이트
> 4단계 전 과정을 이해한다.

---

## 1. 빌드 & 릴리즈 파이프라인 (`packaging/release.ps1`)

`pwsh packaging/release.ps1` 한 줄이 아래 6단계를 순서대로 수행한다.

```
[사전 검사]  git working tree clean 확인 (-Force 로 우회 가능) · .env 로드
     │
① 버전 확인          pyproject.toml version 읽기 (App.spec이 빌드 시 _version.py 생성)
② Frontend 빌드    npm run build → build/web/
③ Updater 빌드     PyInstaller(Updater.spec) → build/updater/Updater.exe
④ App EXE 빌드     PyInstaller(App.spec) → release/{AppName}.exe
⑤ 메타데이터 생성   EXE sha256·크기 계산 → release/latest.json
⑥ 업로드 (선택)     -Upload 플래그 시 Nexus 에 EXE 먼저 → latest.json 마지막 순서로 업로드
```

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

업로드 순서가 "EXE 먼저, latest.json 마지막"인 이유: 메타데이터가 먼저 올라가면
클라이언트가 아직 존재하지 않는 EXE(404)를 다운로드하려고 시도할 수 있기 때문.

> 네트워크 없이 업데이트 파이프라인 전체를 검증하는 `release-dryrun.ps1`도 제공된다.

---

## 2. 자동 업데이트 구조

배포 후 재설치 없이 새 버전이 도달하는 메커니즘. **다운로드 무결성(sha256)과
실행 파일 잠금 문제**를 모두 처리한다.

```
① 확인     앱이 {Nexus}/latest.json GET (5분 캐시)
            └ URL prefix·sha256 형식 검증 실패 시 조용히 "업데이트 없음" 처리
② 적용     새 EXE 스트리밍 다운로드 → sha256 검증 → {이름}.new.exe 로 스테이징
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

사용자 화면에는 업데이트 배너 → 진행률 모달(다운로드/검증/재시작)로 표시된다
(→ [③ 구현된 UX/UI](03-ux-ui.md)).

---

## 3. 환경 변수 — `.env` 단일 진실 공급원

`.env` 파일 하나가 **dev 런타임·EXE 빌드·릴리즈 스크립트** 세 곳에서 공통으로 읽힌다.

```
.env ──┬─ backend (load_dotenv)        : 런타임 상수
       ├─ frontend (vite.config.js)    : dev 프록시 타겟 (APP_DEV_PORT)
       ├─ packaging/App.spec           : EXE 이름·번들 라이브러리 결정
       └─ packaging/release.ps1        : 앱 이름·저장소 자격증명
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
| `APP_ALLOWED_LIBRARIES` | `scripts,polars` | 에이전트 런타임에 노출할 Python 패키지 CSV — **EXE 빌드 시 자동 번들링**. 나열 순서는 해석 우선순위와 무관 |
| `APP_ORCHESTRATOR_API_REFS` | (빈 값) | 오케스트레이터 baseline api_refs CSV — 활성 SKILL 없이도 그 함수 시그니처·docstring 을 `# Available Library APIs` 로 상시 주입. 빈 값=기존(SKILL 주도) 동작, 잘못된 경로는 skip(무오류) |

**업데이트·배포 저장소**

| 변수 | 기본값 | 의미 |
|---|---|---|
| `APP_REPO_BASE_URL` | (내부 Nexus) | 업데이트 저장소 URL (저장소 중립적 변수명) |
| `APP_REPO_USER` / `APP_REPO_PASSWORD` | — | release.ps1 업로드 자격증명 |
| `APP_UPDATE_CHECK_CACHE_TTL` | `300` | latest.json 확인 캐시 (초) |

> 전체 목록과 정확한 로딩 위치: `backend/core/config.py`, `backend/agent/config.py`

---

**이전 문서**: [④ Backend 동작 흐름](04-backend-flow.md)
