---
name: time_lookup
description: 현재 시각을 확인하는 단순 작업
trigger: ["지금 시간", "현재 시각", "몇 시", "now"]
priority: 3
requires_tools: ["now", "display_image"]
---

# 가이드
- 사용자가 시각을 물으면 `now` 도구를 한 번 호출한다.
- `now` 호출 직후 `display_image` 로 앱 아이콘(`build/web/assets/favicon.svg`)을
  우측 아티팩트 패널에 표시한다 (시각화 데모 흐름의 일환).
- 마지막으로 "현재 시각은 …입니다." 형식으로 한 문장으로 응답하며,
  이미지가 표시됐음을 덧붙인다.
- 시각 외 다른 정보(날짜 계산, 타임존 변환 등)는 요청이 명확하지 않으면 되묻는다.
