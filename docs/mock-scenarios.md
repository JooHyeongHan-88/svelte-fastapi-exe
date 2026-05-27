# Mock Provider 시나리오 가이드

`backend/agent/providers/mock.py` 의 `MockProvider` 는 실제 LLM 없이 Harness 와
프론트엔드 UI/UX 전체 파이프라인을 결정론적으로 검증하기 위한 가짜 응답기다.
사용자가 특정 트리거 문구를 입력하면 미리 정의된 5개 시나리오가 발동되어 도구
호출·산출물 저장·SSE 이벤트 스트림을 자동으로 재현한다.

**중요**: Mock 은 `ToolCallEvent` / `DeltaEvent` / `ReasoningEvent` / `DoneEvent` 만
yield 한다. 도구 실행, 결과 합성, UI 이벤트(`TodoUpdateEvent` /
`AgentSwitchEvent` / `AgentReturnEvent` / `SkillActiveEvent` /
`SkillCompleteEvent` / `ToolResultEvent`) 는 모두 Harness 가 자동으로 처리한다.
Mock 안에서 도구를 직접 실행하거나 결과를 합성하지 않는다.

---

## 활성화 방법

dev 모드:
```powershell
# 옵션 A — .env 에서 시드 (settings.json 없을 때만 적용)
APP_LLM_PROVIDER=mock

# 옵션 B — 런타임 핫스왑 (설정 모달 또는 POST /api/settings)
curl -X POST http://127.0.0.1:8765/api/settings -d '{"provider":"mock"}'
```

EXE 모드: 설정 UI 에서 Provider 드롭다운을 `mock` 으로 변경.

---

## 시나리오 트리거 표

| ID | 트리거 예시 | 위임 방식 | 핵심 검증 위젯 |
|---|---|---|---|
| **A** | (그 외 모든 입력) | — | DeltaEvent, MessageBubble markdown |
| **B** | `추천해줘`, `골라줘`, `help me decide` | — (오케스트레이터 직접) | `ReasoningBlock`, `AskUserCard(input_type=both)` |
| **C** | `지금 시간`, `현재 시각`, `몇 시야`, `what time` | 직접 실행 (소속 에이전트 없는 standalone SKILL) | `SkillBadge`, `ArtifactImage`, `ArtifactMarkdown` |
| **D** | `데이터 요약`, `요약 통계`, `summary stats` | Case 3 (data_summary → analyst_agent) | `AgentTrail`, `AgentProgress`, sub 내 `TodoProgress(3)`, sub 내 `ReasoningBlock`, `ArtifactChart(bar)`, `SkillCompleteBadge` |
| **E** | `전체 분석 보고서`, `종합 보고서` | Case 3 × 2단 체이닝 | 오케스트레이터 `TodoProgress(2)`, `AgentTrail` 칩 2개, sub 내 위젯들, `ArtifactChart` + `ArtifactMarkdown` |

---

## 시나리오 흐름 상세

### A. echo (fallback)

매칭되지 않은 모든 입력에 대해 `DeltaEvent` 만 yield. 마크다운 렌더링과 스트리밍
파이프라인의 기본 동작을 검증한다.

### B. reasoning + ask_user (3-mode 데모 중 both 모드)

```
턴 1  → ReasoningEvent 청크 → ToolCallEvent(ask_user, input_type=both,
                                            options=["옵션 A", "옵션 B", "옵션 C"])
턴 2  → (사용자 답변 후) DeltaEvent — 선택 확인 echo
```

### C. time_check SKILL (standalone)

```
턴 1  → ToolCallEvent(now)
턴 2  → ToolCallEvent(display_image, source=result/<session>/<ts>/favicon.svg)
턴 3  → ToolCallEvent(save_artifact, time_log.md)
        ToolCallEvent(display_markdown, source=result/<session>/<ts>/time_log.md)
턴 4  → DeltaEvent — "현재 시각은 ... 입니다" 자연어 응답
```

favicon.svg 는 `backend/agent/providers/mock.py::_ensure_favicon_artifact()` 가
`WEB_DIR/assets/favicon.svg` 를 현재 턴 슬롯에 복사한다 (`display_image` 가 실제
파일 경로를 요구하므로 예외적으로 Mock 이 디스크 작업 직접 수행).

### D. data_summary via analyst_agent (Case 3 단일 위임)

```
오케스트레이터
  턴 1  → ToolCallEvent(call_sub_agent, agent_name="analyst_agent", task="...")

analyst_agent (sub-agent context)
  턴 1  → ReasoningEvent 청크 → ToolCallEvent(add_todo, items=[3개])
  턴 2  → ToolCallEvent(exec_code, samples = [...]) → complete_todo(1)
  턴 3  → ToolCallEvent(call_function, scripts.stats.compute_summary_stats,
                        kwargs={data: $samples}, store_as=stats) → complete_todo(2)
  턴 4  → ToolCallEvent(eval_expression, "stats['mean']", store_as=avg)
          ToolCallEvent(display_chart, bar, series=[stats 6개 항목])
          complete_todo(3)
  턴 5  → ToolCallEvent(complete_subagent, summary="...")

오케스트레이터
  턴 2  → DeltaEvent — analyst 요약 인용 + 차트 안내 자연어 응답
```

분석가의 namespace 변수 `samples`, `stats`, `avg` 는 실제 Harness 가 실행해 세션
namespace 에 저장된다. Mock 은 그 값을 모르므로 차트 series 에는 데모용 더미 값을
넣는다 (실제 LLM 은 tool_result 에서 값을 보고 series 를 구성).

### E. composite — analyst → writer 체이닝

```
오케스트레이터
  턴 1  → ToolCallEvent(add_todo, items=[데이터 분석, 보고서 작성])
  턴 2  → ToolCallEvent(call_sub_agent, "analyst_agent",
                        task="[E-composite] 통계 계산 및 차트 시각화 ...")

analyst_agent sub (축약 흐름 — D 보다 짧음)
  턴 1  → add_todo(2)
  턴 2  → exec_code + call_function + complete_todo(1)
  턴 3  → display_chart + complete_todo(2)
  턴 4  → complete_subagent(summary)

오케스트레이터
  턴 3  → complete_todo(분석)
  턴 4  → ToolCallEvent(call_sub_agent, "writer_agent",
                        task="[E-composite] 분석가 요약: {analyst_summary}")

writer_agent sub
  턴 1  → save_artifact(report.md) + display_markdown
  턴 2  → complete_subagent(summary)

오케스트레이터
  턴 5  → complete_todo(보고서)
  턴 6  → ReasoningEvent + DeltaEvent — 종합 markdown 보고
```

writer 는 analyst 의 namespace 변수에 직접 접근하지 않는다 (sub-agent 격리).
오케스트레이터가 `AgentReturnEvent.summary` 를 받아 writer 의 task 텍스트에 embed
해 전달한다 — 실제 LLM 의 자연스러운 데이터 흐름과 동일.

---

## 분기 우선순위

`MockProvider.astream` 의 분기 순서:

```
1  sub-agent context 감지 (system marker)
     ├─ analyst_agent + [E-composite]  → E analyst sub
     ├─ writer_agent  + [E-composite]  → E writer sub
     └─ analyst_agent (marker 없음)     → D analyst sub
2  E composite     (트리거 또는 진행 중 상태)
3  D single        (트리거 또는 진행 중 상태)
4  C time_check    (트리거 또는 진행 중 상태)
5  B ask_user      (트리거)
5b B answered echo (B ask_user tool_result 존재)
6  A echo          (기본 폴백)
```

진행 중 상태 판별은 `_has_recent_tool_result(messages, prefix)` 헬퍼가 마지막
user 메시지 이후 슬라이스에서 특정 `tool_call_id` prefix 를 검색해 결정한다.

---

## 산출물 경로 규약

Mock 시나리오가 생성하는 파일은 모두 `result/` 하위에 저장된다.

```
result/
  {세션제목}-{client_id[:8]}/      ← session_dir_name()
    {YYYYMMDD-HHmmss}/             ← turn_slot() — 같은 턴 안 호출은 동일 폴더 재사용
      favicon.svg                  ← C 시나리오 이미지
      time_log.md                  ← C 시나리오 시각 로그
      report.md                    ← E 시나리오 writer 산출물
```

- 폴더명은 `result_store.sanitize_title()` 로 Windows/POSIX 안전 처리된다.
- `result/` 는 `.gitignore` 에 등재되어 있으므로 생성된 파일은 추적되지 않는다.
- 동일 턴 내 `save_artifact` 여러 호출은 `turn_slot()` 캐시로 같은 폴더에 모인다.

---

## 새 시나리오 추가 절차

1. **트리거 상수 선언** — `backend/agent/providers/mock.py` 상단에
   `_X_TRIGGERS = ("...", "...")` 추가. 기존 시나리오 트리거와 충돌하지 않도록
   고유 키워드 선택 (특히 일반적인 단어 "도와줘" / "요약" 등은 다른 시나리오와
   충돌하기 쉬움).

2. **시나리오 함수 작성** —
   ```python
   async def _scenario_X(messages: list[Message]) -> AsyncIterator[StreamEvent]:
       has_step1 = _has_recent_tool_result(messages, "mock-X-step1-")
       if not has_step1:
           yield ToolCallEvent(
               call=ToolCall(
                   id=f"mock-X-step1-{uuid.uuid4().hex[:8]}",
                   name="some_tool",
                   arguments={...},
               )
           )
           yield DoneEvent()
           return
       # 다음 단계...
   ```

3. **`astream` 분기 추가** — 적절한 우선순위 위치에 트리거 매칭 또는 진행 상태
   판별 분기를 삽입한다.

4. **(선택) 새 SKILL/AGENT 추가** — Case 3 자동 라우팅을 시험하려면
   `SKILLS/<name>.md` 에 Front Matter (trigger, api_refs) 를 작성하고
   `AGENTS/<name>.md` 의 `skills:` 에 등록한다.

5. **(선택) 새 backend/scripts 함수** — `backend/scripts/<module>.py` 에 함수를
   추가하면 `App.spec` 의 `collect_submodules('scripts')` 가 다음 빌드에 자동
   포함한다. `.env` 의 `APP_ALLOWED_LIBRARIES=scripts` 가 import 화이트리스트에
   등록되어 있어야 한다.

---

## 트리거 충돌 주의사항

- 새 트리거를 추가할 때는 기존 5개 트리거와의 부분 문자열 충돌을 반드시 확인한다.
- `_matches` 헬퍼는 소문자 substring 매칭이므로 짧은 키워드는 광범위하게 매칭된다.
- 같은 입력이 여러 시나리오에 매칭되면 위쪽 분기가 우선한다 (코드 순서).

현재 트리거 충돌 회피 결정:
- B 의 트리거에서 "도와줘" 는 제외 (D/E 와 충돌 위험)
- E 의 트리거에서 "요약" 단어 제외 (D 와 충돌)
- C 의 "몇 시" 는 "몇 시야" / "몇 시인가요" 로 제한 (오탐 방지)

---

## 미커버 분기

다음은 의도적으로 5개 시나리오에서 제외했다. 필요 시 별도 시나리오로 확장 가능:

- `activate_skill` sentinel 도구 분기
- 도구 실행 실패 (`is_error=True`) — RCA 유도 메시지 흐름
- `AskUserCard` 의 `input_type=text` / `input_type=choice` 단독 모드 (B 는 both 만)
- loop-guard / depth-guard 차단 흐름
- TurnBudget 한도 초과 시 ErrorEvent

---

## 검증 방법

자동 (단위 테스트 + 린트):
```powershell
uv run ruff format . && uv run ruff check --fix .
cd backend; uv run python -m pytest tests/ -v
```

수동 (Mock 모드 dev 서버):
```powershell
uv run python backend/main.py    # 터미널 1
cd frontend; npm run dev         # 터미널 2
```

브라우저에서 각 시나리오 트리거를 순서대로 입력하며 위의 "핵심 검증 위젯" 컬럼의
모든 컴포넌트가 정상 렌더링되는지 육안 확인한다.
