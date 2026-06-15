// SSE 스트림 이벤트 → assistant 메시지 segments 트리 리듀서.
//
// chatActions 의 sendMessage 루프가 받은 각 StreamEvent 를 이 헬퍼들에 넘겨
// segments 배열(reactive proxy)을 in-place 로 누적한다. 오케스트레이터와
// 서브에이전트가 _applyEvent 를 재귀적으로 공유하는 것이 멀티 에이전트 트레일
// 렌더의 핵심이다. 순수 함수(전역 crypto 외 의존 없음)라 전송 루프와 분리했다.

// 시각화 도구 결과인지 판별. tool_result / agent:progress 양쪽에서 공유한다.
const _ARTIFACT_TOOL_NAMES = new Set([
  "display_image",
  "display_chart",
  "display_markdown",
  // 확장 시스템 진입 규약 — open_curation 은 확장 SPA 를 패널 iframe(extension 칩)으로 연다.
  // evaluator 비특정(제네릭)이라 확장 폴더를 지워도 무해(에이전트가 호출 안 함).
  "open_curation",
]);
const _ARTIFACT_KINDS = new Set(["image", "chart", "markdown", "extension"]);

// harness 가 모든 tool_call 을 프론트로 yield 하지만, sentinel 도구는 전용 세그먼트
// (subagent / todo / askUser / skill 칩) 로 따로 렌더되므로 도구 카드로 중복 표시하면 안 된다.
const _SENTINEL_TOOL_NAMES = new Set([
  "add_todo",
  "complete_todo",
  "call_sub_agent",
  "call_sub_agents_parallel",
  "activate_skill",
  "complete_subagent",
  "ask_user",
]);

function _isArtifactToolResult(ev) {
  return (
    !ev.is_error &&
    ev.data?.kind &&
    _ARTIFACT_KINDS.has(ev.data.kind) &&
    _ARTIFACT_TOOL_NAMES.has(ev.name)
  );
}

/**
 * parquet 중간 산출물 → 데이터 칩 payload 목록.
 * save_artifact 직접 저장과 exec_code 의 artifact_dir() 직접 쓰기(new_artifacts)
 * 양쪽을 커버한다. parquet 만 칩이 된다 (중간 데이터 영속 포맷 통일 방향).
 *
 * @param {{name?: string, is_error?: boolean, data?: object}} ev tool_result 이벤트
 * @returns {Array<{path: string, filename?: string, size?: number, rows?: number, columns?: number}>}
 */
function _dataArtifactPayloads(ev) {
  if (ev.is_error || !ev.data) return [];
  if (
    ev.name === "save_artifact" &&
    ev.data.kind === "parquet" &&
    typeof ev.data.path === "string"
  ) {
    const { path, filename, size, rows, columns } = ev.data;
    return [{ path, filename, size, rows, columns }];
  }
  if (ev.name === "exec_code" && Array.isArray(ev.data.new_artifacts)) {
    return ev.data.new_artifacts
      .filter((a) => a && a.kind === "parquet" && typeof a.path === "string")
      .map(({ path, filename, size }) => ({ path, filename, size }));
  }
  return [];
}

// ---------- segments 헬퍼 ----------

/** 짧은 고유 ID 생성 (세그먼트 key 용). */
export function _segId() {
  return crypto.randomUUID().slice(0, 8);
}

/**
 * segments 배열에서 agentId 와 일치하는 마지막 running 서브에이전트 세그먼트를 반환한다.
 * agent:progress / agent:return 이벤트 라우팅에 사용한다.
 *
 * Args:
 *   segments: 검색할 세그먼트 배열
 *   agentId: 찾을 서브에이전트 ID
 *
 * Returns:
 *   일치하는 세그먼트 객체 또는 null
 */
function _findLastRunningSubagent(segments, agentId) {
  for (let i = segments.length - 1; i >= 0; i--) {
    const seg = segments[i];
    if (seg.kind === "subagent" && seg.agentId === agentId && seg.status === "running") {
      return seg;
    }
  }
  return null;
}

/**
 * agent:progress / agent:return 이벤트를 올바른 서브에이전트 세그먼트로 라우팅한다.
 *
 * dispatch_id 가 있으면(병렬 실행) 그 상관키로 정확히 매칭한다 — 같은 이름 에이전트가
 * 둘 이상 동시에 떠도 충돌하지 않는다. dispatch_id 가 없으면(구 세션·순차 폴백)
 * agentId 기반 '마지막 running' 휴리스틱으로 되돌아간다.
 *
 * Args:
 *   segments: 검색할 세그먼트 배열
 *   ev: agent:progress(agent_id) 또는 agent:return(from_agent) 이벤트
 *
 * Returns:
 *   일치하는 subagent 세그먼트 객체 또는 null
 */
export function _findSubagentForEvent(segments, ev) {
  const agentId = ev.agent_id ?? ev.from_agent;
  if (ev.dispatch_id) {
    for (let i = segments.length - 1; i >= 0; i--) {
      const seg = segments[i];
      if (seg.kind === "subagent" && seg.dispatchId === ev.dispatch_id) {
        return seg;
      }
    }
    // dispatch_id 가 왔는데 매칭 세그먼트가 없으면(이론상 드묾) 이름 기반 폴백.
  }
  return _findLastRunningSubagent(segments, agentId);
}

/**
 * SSE 이벤트를 segments 배열에 시간순으로 누적한다.
 * 오케스트레이터와 서브에이전트가 동일 헬퍼를 재귀적으로 공유한다 — 재귀의 핵심.
 *
 * agent:switch / agent:progress / agent:return 은 최상위에서만 발생하므로
 * 이 함수에서는 처리하지 않는다.
 *
 * Args:
 *   segments: 누적 대상 배열 (in-place 변경)
 *   ev: 이벤트 객체 — { type, ...payload }
 *   addArtifactChip: 아티팩트 칩 추가 콜백 (kind, payload, {open}) => void | null
 *   setActiveSkills: 해당 scope 의 activeSkills 갱신 (skills[]) => void | null
 */
export function _applyEvent(segments, ev, addArtifactChip, setActiveSkills) {
  switch (ev.type) {
    case "delta": {
      // 마지막 text 세그먼트에 이어붙이거나 새로 push (도구 호출로 끊기면 복수 text 가능)
      const last = segments.at(-1);
      if (last?.kind === "text") {
        last.content += ev.content ?? "";
      } else {
        segments.push({ kind: "text", id: _segId(), content: ev.content ?? "" });
      }
      break;
    }
    case "reasoning": {
      const last = segments.at(-1);
      if (last?.kind === "reasoning") {
        last.content += ev.content ?? "";
      } else {
        segments.push({ kind: "reasoning", id: _segId(), content: ev.content ?? "" });
      }
      break;
    }
    case "tool_call": {
      // sentinel 도구는 전용 세그먼트로 렌더되므로 도구 카드를 push 하지 않는다.
      // (대응 tool_result 도 매칭 세그먼트가 없어 자연히 no-op 처리된다.)
      if (_SENTINEL_TOOL_NAMES.has(ev.call?.name)) break;
      segments.push({
        kind: "tool",
        id: _segId(),
        callId: ev.call?.id ?? _segId(),
        name: ev.call?.name ?? "?",
        status: "running",
        detail: null,
        data: null,
      });
      break;
    }
    case "tool_result": {
      // tool_call_id 로 대응하는 tool 세그먼트를 찾아 확정한다.
      for (let i = segments.length - 1; i >= 0; i--) {
        if (segments[i].kind === "tool" && segments[i].callId === ev.tool_call_id) {
          segments[i].status = ev.is_error ? "error" : "ok";
          segments[i].detail = ev.result ?? null;
          segments[i].data = ev.data ?? null;
          if (addArtifactChip) {
            if (_isArtifactToolResult(ev)) {
              addArtifactChip(ev.data.kind, ev.data, { open: true });
            }
            for (const payload of _dataArtifactPayloads(ev)) {
              addArtifactChip("data", payload, { open: false });
            }
          }
          break;
        }
      }
      break;
    }
    case "todo_update": {
      // add_todo 가 누적돼도 todo_update 는 항상 전체 리스트를 보내므로 단일 블록 in-place 갱신.
      let todoIdx = -1;
      for (let i = segments.length - 1; i >= 0; i--) {
        if (segments[i].kind === "todo") { todoIdx = i; break; }
      }
      if (todoIdx >= 0) {
        segments[todoIdx].todos = ev.todos ?? [];
      } else {
        segments.push({ kind: "todo", id: _segId(), todos: ev.todos ?? [], complete: null });
      }
      break;
    }
    case "skill_active": {
      if (setActiveSkills) setActiveSkills(ev.skills ?? []);
      break;
    }
    case "skill_complete": {
      // 해당 scope 의 마지막 todo 세그먼트에 complete 통계를 설정한다.
      const complete = {
        completed: ev.completed ?? 0,
        failed: ev.failed ?? 0,
        skipped: ev.skipped ?? 0,
      };
      for (let i = segments.length - 1; i >= 0; i--) {
        if (segments[i].kind === "todo") {
          segments[i].complete = complete;
          break;
        }
      }
      break;
    }
  }
}
