"""대화 히스토리·턴 진행 상태(todo/pending slot) 영속 저장소.

경계: 이 패키지는 **대화·턴 상태 전용**이다. "저장하는 것"이 전부 여기로
오지 않는다 —

    - 코드 실행 변수($df 등)는 `agent/runtime/namespace.py` (의도적 휘발,
      세션 간 영속의 정식 경로는 save_artifact → load_artifact).
    - 차트 ViewState(undo/redo)는 `agent/charts/chart_filter_store.py`
      (산출물 폴더의 charts.filter.json 사이드카).

구성:
    - conversation: client_id 별 대화 히스토리 인메모리 저장소 (tool 쌍 보존
      트리밍 + 히스토리 truncation).
    - agent_state: AgentState(todo/pending) 디스크 영속 — EXE 재기동을 건너서
      슬롯 답변 흐름이 이어져야 하므로 ConversationStore 와 분리.
"""
