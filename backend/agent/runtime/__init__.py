"""라이브러리 런타임 인프라.

외부 Python 패키지를 Agent 가 동적으로 사용하기 위한 baseline.

구성:
    - resolver: dotted-path 해석 + ALLOWED_LIBRARIES 화이트리스트.
    - serialization: SessionNamespace 변수의 디스크 직렬화.
    - evaluator: eval_expression 의 안전 builtins.
    - namespace: 세션별 변수 저장소 (memory hot tier + disk cold tier).
    - introspect: SKILL/AGENT 의 api_refs 로부터 ApiDoc 추출.

이 패키지의 공개 API 는 backend/agent/tools/runtime.py 에서 사용된다.
"""
