---
name: report_writer
description: 분석 결과를 한국어 마크다운 보고서로 정리하고 사이드 패널에 렌더링한다
trigger:
  - 보고서 작성
  - 리포트 작성
  - report writing
priority: 5
requires_tools:
  - save_artifact
  - display_markdown
---

# 리포트 작성 작업 가이드

사용자가 "보고서/리포트로 정리해줘" 라고 요청하거나, 선행 분석 결과를 문서화해야
할 때 따르는 표준 절차다.

## 단계

1. **본문 구조화** — 받은 분석 내용(앞 단계의 요약 또는 sub-agent 반환 요약)을
   다음 마크다운 골격으로 정리한다:
   ```markdown
   # {제목}

   ## 요약
   {1-2 문단}

   ## 핵심 지표
   | 항목 | 값 | 비고 |
   |---|---|---|

   ## 인사이트
   - {불릿 1}
   - {불릿 2}

   ## 후속 액션
   ```

2. **산출물 저장** — `save_artifact(filename="report.md", kind="markdown",
   content=<위 본문>)` 로 저장한다. 반환된 경로를 다음 단계에서 사용한다.

3. **패널 렌더링** — `display_markdown(source=<save_artifact 반환 경로>,
   title="<리포트 제목>")` 로 사이드 패널에 렌더링한다.

## 주의

- 표·불릿·인용·코드 블록을 적극 활용해 ArtifactMarkdown 의 렌더링 영역을 충분히
  채운다 — 단순 문단만 있으면 시각적으로 빈약하다.
- 본문에 `Task Summary:` 라는 문자열은 절대 포함하지 않는다 (sub-agent 종료 마커와
  충돌한다).
- `save_artifact` 와 `display_markdown` 은 한 iteration 에서 함께 호출해도 무방하다.
