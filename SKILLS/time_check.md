---
name: time_check
description: 현재 시각을 확인하고 시각 로그를 이미지·마크다운으로 사용자에게 시연한다
trigger:
  - 지금 시간
  - 현재 시각
  - 몇 시야
  - 몇 시인가요
  - what time
priority: 5
requires_tools:
  - now
  - save_artifact
  - display_image
  - display_markdown
---

# 시간 확인 작업 가이드

사용자가 현재 시각을 묻거나 시간 기록이 필요한 작업을 요청할 때 따르는 표준 절차다.
`now` 도구로 시각을 가져온 뒤 이미지·마크다운 산출물로 사용자에게 시연한다.

## 단계

1. **시각 조회** — `now()` 도구로 현재 시각을 ISO 8601 문자열로 가져온다.
2. **시각화 이미지 표시** — 시각을 상징하는 이미지를 `display_image` 로 우측 패널에
   띄운다. (시계 아이콘이나 시각 테마 산출물 등)
3. **시각 로그 저장 및 렌더링** — `save_artifact(filename="time_log.md", kind="markdown")`
   로 "현재 시각 기록" 문서를 저장하고, 반환된 경로를 `display_markdown` 으로 패널에
   렌더링한다.
4. **자연어 응답** — 사용자에게 "현재 시각은 {time} 입니다" 형태로 한국어 응답한다.
   필요하면 우측 패널에 추가 시각 자료가 있다는 안내 한 줄을 덧붙인다.

## 주의

- 각 도구 호출은 한 번씩만 — 동일 인자로 연속 호출하면 loop-guard 가 차단한다.
- `display_image` / `display_markdown` 의 `source` 는 항상 `result/<session>/<ts>/<filename>`
  형식이어야 한다 (절대경로·외부 URL 금지).
