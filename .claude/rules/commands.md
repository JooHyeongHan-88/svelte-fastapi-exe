# 주요 명령어

- Python 패키지 관리: `uv` / JS 패키지 관리: `npm`
- 빌드 산출물 흐름: **`build/` (중간)** → **`release/` (GitHub Release 첨부 대상)**

```powershell
# 개발 서버 (백엔드 먼저, Vite가 /api를 프록시)
uv run python backend/main.py          # 터미널 1
cd frontend; npm run dev               # 터미널 2 — http://localhost:5173

# 의존성
uv sync --dev
cd frontend; npm install

# 린트/포맷 — Python 변경 후 반드시 실행
uv run ruff format . && uv run ruff check --fix .

# 테스트 전체
uv run python -m pytest backend/tests/ -v
```

> `pyproject.toml`에 `[tool.pytest.ini_options] asyncio_mode = "auto"` 설정 — `async def test_*` 함수가 마커 없이 자동 실행된다.

---

## 주요 테스트 파일 단독 실행 (커버리지 맵)

```powershell
uv run python -m pytest backend/tests/test_guard_pydantic.py -v        # 슬롯 가드
uv run python -m pytest backend/tests/test_runtime_evaluator.py -v     # eval/exec 보안
uv run python -m pytest backend/tests/test_conversation_store.py -v    # 히스토리 정합성
uv run python -m pytest backend/tests/test_openai_provider.py -v       # provider 스트리밍
uv run python -m pytest backend/tests/test_artifact_tool.py -v         # save_artifact (바이너리 kind 포함)
uv run python -m pytest backend/tests/test_artifact_parquet.py -v      # parquet 파이프라인
uv run python -m pytest backend/tests/test_artifact_io.py -v           # list_artifacts·load_artifact·경로 해석
uv run python -m pytest backend/tests/test_artifact_manifest.py -v     # 세션 manifest·Session Artifacts 섹션
uv run python -m pytest backend/tests/test_artifact_preview_api.py -v  # /api/artifact preview·csv·reveal (데이터 칩·폴더 열기)
uv run python -m pytest backend/tests/test_harness_timeout.py -v       # _execute_tool (async)
uv run python -m pytest backend/tests/test_harness_subagent.py -v      # 서브에이전트 격리
uv run python -m pytest backend/tests/test_harness_parallel.py -v      # 서브에이전트 병렬 디스패치
uv run python -m pytest backend/tests/test_harness_error_path.py -v    # run_turn 예외 경로 영속·DoneEvent
uv run python -m pytest backend/tests/test_harness_loop_guard.py -v    # 루프 가드 파일 fingerprint
uv run python -m pytest backend/tests/test_harness_todo_reset.py -v    # 턴 시작 terminal todo 리셋
uv run python -m pytest backend/tests/test_harness_wind_down.py -v     # 반복 예산 임박 wind-down 지시
uv run python -m pytest backend/tests/test_chat_concurrent_guard.py -v # 같은 client_id 동시 턴 거부
uv run python -m pytest backend/tests/test_chart_renderer.py -v        # 차트 렌더러 (legend 적용 포함)
uv run python -m pytest backend/tests/test_chart_filter_store.py -v    # 차트 뷰 상태 undo/redo 스택
uv run python -m pytest backend/tests/test_chart_api.py -v             # /api/chart/filter 통합 (HTTP 경계)
uv run python -m pytest backend/tests/test_display_chart_spec.py -v    # display_chart spec
```

---

## 프로덕션 빌드 / 릴리즈 (`-Channel` 필수)

```powershell
pwsh packaging/release.ps1 -Channel qa             # QA 빌드 (Mock 노출, 업데이트 차단, --prerelease)
pwsh packaging/release.ps1 -Channel prod -Upload -Notes "..."  # Prod 빌드 + GitHub Release 게시
pwsh packaging/release.ps1 -Channel prod -Force    # git dirty 상태 강제 통과
pwsh packaging/build-dev.ps1                       # dev: 메인+확장 프론트 전체 빌드 (backend 정적 서빙용, EXE 미빌드)
```

산출물: `release/{AppName}.exe`, `release/{AppName}-X.X.X.exe`, `release/latest.json`

> 빌드 순서·채널 분기·PowerShell 5.1 주의점 → [update_architecture.md](update_architecture.md).
