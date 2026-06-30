# 환경 변수

`.env`는 **빌드 파이프라인의 단일 진실 공급원**. frozen EXE는 빌드 시 `MEIPASS/.env`에 박제된
`.env`를 `load_dotenv(override=False)`로 읽는다. OS 환경 변수가 있으면 그쪽이 우선
(`override=False`)하므로, 런타임 오버라이드는 OS 환경 변수로 가능하지만 근본 변경은 재빌드가 필요하다.

> 전체 목록·기본값 로직은 `backend/core/config.py`, `backend/agent/config.py` 참고.
> `.env` 값의 `# 인라인 주석`은 파서가 자동 제거한다.

| 환경 변수 | 기본값 | 설명 |
|---|---|---|
| `APP_NAME` | `MyAgent` | EXE 파일명, settings.json 경로 |
| `APP_PORT` | (APP_NAME 해시) | **frozen 전용** 고정 포트. 기본값은 `47100 + sha256(APP_NAME) % 1900` (47100–48999). `0` 이면 동적(대화 기록이 실행마다 격리됨). 충돌 시 +1..+4 후보 체인 자동 폴백 — `core.server_socket` |
| `APP_DEV_PORT` | `8765` | **dev 전용** 백엔드 포트 (Vite 프록시 타겟과 공유). frozen 은 APP_PORT 로 결정 — `core.server_socket`. 호스트는 `127.0.0.1` 코드 고정(env 미노출) |
| `APP_LLM_PROVIDER` | `mock` | 초기 settings.json 시드용 (`mock` \| `dtgpt` \| `openai_compatible`) |
| `APP_DTGPT_BASE_URL` | — | DTGPT 엔드포인트 (UI 비노출, factory가 직접 읽음) |
| `APP_SYSTEM_PROMPT` | (내장 한국어) | LLM 시스템 프롬프트 |
| `APP_MAX_AGENT_ITERATIONS` | `12` | 한 턴당 provider→tool 반복 상한. 잔여 2회 시점에 wind-down 지시 자동 주입(R7) |
| `APP_MAX_AGENT_CALLS_PER_TURN` | `20` | 오케스트레이터+서브에이전트 합산 provider 호출 상한 |
| `APP_MAX_PARALLEL_SUBAGENTS` | `3` | `call_sub_agents_parallel` 한 번에 동시 실행할 서브에이전트 수 상한 (semaphore) |
| `APP_TOOL_DEFAULT_TIMEOUT` | `30` | Tool 1회 실행 timeout (초) |
| `APP_DEBUG_TRACE` | `false` | **dev 전용** 디버그 트레이스 토글. 켜면 턴마다 provider in/out(프롬프트 전문·raw 응답)과 하니스 결정점(루프가드·슬롯가드·wind-down 등)을 `result/<session>/_trace/<turn>.jsonl` 로 기록 — `tracer` 확장(런처 드롭다운)으로 타임라인 조회. frozen EXE 는 강제 비활성 — `agent.debug.trace` |
| `APP_ALLOWED_LIBRARIES` | `scripts,polars` | 런타임에 노출할 패키지 루트 CSV — EXE 빌드 시 자동 번들링. `scripts`(고수준 래퍼) 우선은 프롬프트가 유도; CSV 순서는 해석 우선순위와 무관 |
| `APP_MAX_HISTORY_MESSAGES` | `40` | store 가 client 한 명당 보관하는 메시지 수 상한(system 제외). 초과 시 앞에서 트림되며 버린 턴은 압축 요약으로 보존(R10) — `agent.config` |
| `APP_COMPACTION_ENABLED` | `true` | summarize-then-drop 압축 토글. 히스토리 윈도우가 메시지를 버리기 직전 LLM 으로 요약해 `state.progress_summary` 에 보존(망각 방지). best-effort — 실패해도 직전 요약 유지·턴 진행. happy path 전용 — `agent.config` (R10) |
| `APP_OBJECTIVE_MAX_CHARS` | `500` | 세션 첫 턴 user_message 를 `state.objective`(원래 목표 앵커, `# 이전 진행 요약` 재주입)로 박제할 때 길이 상한 — `agent.config` (R10) |
| `APP_ORCHESTRATOR_API_REFS` | (빈 값) | 오케스트레이터 baseline api_refs CSV. 지정 시 활성 SKILL 없이도 그 함수들의 시그니처·docstring 을 `# Available Library APIs` 로 상시 주입(런타임 메타 도구는 원래 항상 노출이라, 이 변수가 주는 건 prompt 의 docstring). 빈 값=기존 SKILL 주도 동작. 잘못된 경로는 skip — 무오류 |
| `APP_REPO_BASE_URL` | — | GitHub 레포 루트 URL — updater가 REST API base(`.../api/v3`)·owner/repo 유도 |
| `APP_REPO_READ_TOKEN` | — | 읽기 전용 Classic PAT — EXE에 번들, REST API 릴리즈 메타·에셋 다운로드 인증용 (콘텐츠 동기화와 공유) |
| `APP_BUILD_CHANNEL` | (`qa`/`prod`) | App.spec이 주입 — 소스 `.env`에 두지 않음. `qa`: Mock 노출·업데이트 차단·콘텐츠 `dev` 브랜치; `prod`: Mock 제외·업데이트 활성·콘텐츠 `main` 브랜치 |
| `APP_CONTENT_SYNC_ENABLED` | frozen=`true`, dev=`false` | frozen 기동 시 SKILLS/AGENTS/PROMPTS를 원격 브랜치에서 동기화(EXE 재빌드 없이 콘텐츠 갱신). 실패 시 번들 폴백 — `core.content_sync` |
| `APP_CONTENT_SYNC_BRANCH` | — | 채널 매핑(qa→dev, prod→main) 무시하고 이 브랜치 강제 — frozen 카나리 검증용 |
| `APP_CONTENT_SYNC_TIMEOUT` | `5` | 기동 시 콘텐츠 동기화 블로킹 상한 (초) |
