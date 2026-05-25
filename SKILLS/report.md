---
name: report_writer
description: Markdown 보고서를 생성하고 사이드 패널에 렌더링하는 작업
trigger: ["리포트 작성", "보고서 작성", "리포트 에이전트", "report writer"]
priority: 6
requires_tools: ["display_markdown"]
---

# Markdown 리포트 작성 가이드

## 절차
1. `add_todo` 로 아래 3단계를 한 번에 등록한다.
2. **본문 작성** — 주제·핵심 사실·근거를 markdown 형식으로 정리한다 (헤더·표·불릿·code block).
3. **산출물 저장** — `report/<session>/report.md` 경로에 본문을 기록한 뒤 `complete_todo`.
4. **사이드 렌더링** — `display_markdown(source="report/<session>/report.md", title="...")`
   도구로 우측 패널에 표시한 뒤 `complete_todo`.

## 행동 원칙
- 데이터에 근거가 없는 단정은 금지한다. 추정·가정은 "[가정]" 으로 표기.
- 본문은 200~600 단어 사이가 적절하다 — 너무 길면 요약, 너무 짧으면 표/리스트로 보강.
- 동일 세션에서 이미 같은 산출물 파일이 있으면 덮어쓰지 말고 그대로 재사용한다.

## 금지
- 산출물 파일 없이 자연어로만 보고하지 않는다 — 사이드 패널에 표시될 파일이 반드시 있어야 한다.
- 사용자가 위임한 범위 밖의 주제로 확장하지 않는다.
