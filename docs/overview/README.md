# 프로젝트 소개 자료 (Overview)

이 폴더는 **프로젝트를 처음 접하는 사람에게 프로젝트 자체를 설명하기 위한 자료**다.
`docs/` 의 다른 문서들이 "에이전트를 커스터마이징하는 개발자"를 위한 참고서라면,
이 폴더는 "이 프로젝트가 무엇이고 어떻게 동작하는가"를 큰 그림부터 차례로 설명한다.

각 문서는 추후 슬라이드 자료의 원고로 쓸 수 있도록 **섹션 단위(`##`)가 슬라이드 1~2장**에
대응하게 구성되어 있다.

## 읽는 순서

| 순서 | 문서 | 답하는 질문 |
|---|---|---|
| ① | [01-project-overview.md](01-project-overview.md) | 무엇을 만드는 프로젝트인가? 어떻게 빌드·배포되는가? 무엇으로 구성되어 있는가? |
| ② | [02-ux-ui.md](02-ux-ui.md) | 최종 사용자는 어떤 화면에서 어떤 기능을 쓰는가? |
| ③ | [03-backend-flow.md](03-backend-flow.md) | 백엔드는 내부적으로 어떻게 동작하는가? 어떤 모듈·도구가 있는가? |

## 슬라이드 (발표용)

위 3개 문서의 슬라이드 버전이 `slides/` 에 있다. **의존성·빌드 도구 없이** 브라우저로 바로 여는
self-contained HTML 덱이다.

```powershell
node docs/overview/slides/build-html.js   # slides/index.html 재생성
# slides/index.html 을 브라우저로 열기 — ← / → 방향키로 넘김, 인쇄(PDF 저장) 지원
```

- 내용은 `s0-cover.js` · `s1-overview.js` · `s2-ux.js` · `s3-backend.js` (섹션 = 슬라이드)에 정의되고,
  `theme.js` 가 Claude 톤 디자인 시스템, `html-render.js` 가 1280×720 캔버스로 렌더한다.
- `index.html` 은 생성 산출물 — 직접 편집하지 말고 `build-html.js` 로 재생성한다.

## 더 깊이 들어가려면

- 에이전트 확장(SKILLS/AGENTS/도구 추가) → [docs/README.md](../README.md)
- 아키텍처 세부 결정 사항 → `.claude/rules/*.md`
