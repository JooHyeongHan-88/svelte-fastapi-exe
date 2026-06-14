# evaluator — parquet 큐레이션 확장

AI Agent 가 만든 parquet 산출물을 사람이 **시각적으로 검토·선별·재정렬**해 최종
리포트용 데이터로 만드는 확장 툴. 메인 채팅 앱과 독립적이며, **이 폴더(`extensions/evaluator/`)
를 통째로 지워도 메인 앱은 그대로 동작**한다(확장 시스템의 try/except no-op).

## 동작

소스 parquet 의 컬럼을 역할로 매핑한다(기본값은 예시 데이터 컬럼명):

| 역할 | 기본 컬럼 | 필수 | 설명 |
|---|---|---|---|
| 선택 기준 `select` | `item_id` | ✅ | 좌측 리스트의 행 단위(체크 대상) |
| Sort 기준 `sort` | `rank` | ✅ | 최초 정렬 순서 · 내보내기 시 정수 재계산 대상 |
| 차트 x `x` | `tkout_time` | ✅ | scatter x축 |
| 차트 y `y` | `value` | ✅ | scatter y축 |
| 레전드 `legend` | `category` | ✅ | scatter 시리즈 그룹(예: POR/NEW) |
| 설명 `desc` | `item_desc` | — | 리스트 보조 설명 — **없어도 됨**(컬럼 부재 시 desc 생략) |

- **좌측(너비 조절 가능)**: 선택 기준이 Sort 기준 순으로 나열. 진입 시 **전부 체크(선택)** 된 상태가
  기본. **↑/↓** 하이라이트 이동 · **Space** 선택 토글 · 행의 **↑↓** 로 순서 변경. 패널 우측
  경계를 드래그해 너비를 조절한다.
- **본문(차트 그리드)**: 항목을 **클릭하면 그 항목의 scatter 를 표시**하고, **Ctrl/⌘+클릭으로
  여러 항목을 동시에** 그리드(페이지당 6개·페이지네이션)로 본다. 각 차트는 제목 패널로 감싸인다.
  메인 앱 `display_chart` 와 같은 UX:
  - 차트를 **클릭하면 확대 라이트박스**(리사이즈·좌우 네비)로 연다.
  - 라이트박스 툴바: **Filter / Filter All / Reset / Undo / Redo** + **Legend** 편집 패널
    (드래그 순서 · 색상 · 눈 표시/숨김 · 체크 후 Filter 로 제외). 차트 상호작용은 **클라이언트
    사이드**라 라운드트립이 없다. **Filter(점·레전드 그룹 제외)는 '이 행을 최종 데이터에서
    뺀다'는 데이터 결정이라 내보내기 결과 parquet 에 실제로 반영**되고, 레전드 순서·색상·눈
    표시/숨김은 **시각 전용**이라 데이터에 반영하지 않는다.
- **하단**: **저장하기**(선택·순서 상태를 사이드카 JSON 으로 저장) · **내보내기**(선택 항목만 필터 +
  **Filter 로 제외한 행 실제 삭제** + 리스트 순서대로 `sort` 컬럼을 1..N 정수로 재계산 →
  `<stem>.curated.parquet`).
  내보내기 성공 시 같은 출처(same-origin)인 **메인 앱 탭에 `BroadcastChannel("evaluator:exports")`
  로 알림**을 보내, 메인 앱이 그 parquet 을 **데이터 칩**으로 사용자에게 인폼한다(세션 상관키는
  소스 경로의 `<session>`).

## 진입

```
http://127.0.0.1:<port>/ext/evaluator/?path=result/<session>/<ts>/<file>.parquet
```

매핑 오버라이드도 쿼리로 전달 가능: `&select=item_id&sort=rank&x=tkout_time&y=value&legend=category&desc=item_desc`

## 개발 / 빌드

```powershell
# 의존성
cd extensions/evaluator/frontend; npm install

# 빌드(→ dist/) — 백엔드가 /ext/evaluator/ 로 서빙
npm run build

# 또는 dev 서버(HMR, 5174) — /api·/result 는 백엔드(8765)로 프록시
npm run dev   # http://127.0.0.1:5174/ext/evaluator/?path=...

# 예시 parquet 생성(dev)
uv run python extensions/evaluator/scripts/make_sample.py

# 백엔드 테스트(격리)
uv run python -m pytest extensions/evaluator/backend/tests -v
```

> 빌드된 `dist/` 와 파이썬 코드는 `App.spec` 의 글롭이 자동으로 EXE 에 번들한다(spec 수정 불필요).

## 구조

```
extensions/evaluator/
  backend/router.py          # /api/ext/evaluator — dataset/state/export (단일 모듈)
  backend/tests/             # 격리 pytest
  frontend/                  # 독립 Svelte5+Vite SPA (echarts)
    src/App.svelte           # 좌측 리스트(너비 조절·다중선택) + 차트 그리드 + 액션
    src/lib/chartOption.js   # points+스냅샷 → scatter ECharts option (제외·레전드·row_ids)
    src/lib/chartState.svelte.js  # 선택키별 제외/레전드 undo/redo 스냅샷 스택(클라이언트)
    src/lib/ChartCell.svelte      # 단일 ECharts(그리드 셀/라이트박스, brush)
    src/lib/ChartGrid.svelte      # 제목 패널 + 6/페이지 페이지네이션 그리드
    src/lib/ChartLightbox.svelte  # 확대 모달 + Filter/Reset/Legend 툴바(인라인 SVG)
  scripts/make_sample.py     # 예시 parquet 생성기
```

> 차트는 메인 앱 `display_chart`(백엔드 spec→render→`/api/chart/filter` 파이프라인)와 달리
> **클라이언트에서 직접** 구성한다 — points 가 이미 적재돼 있고 필터/레전드는 검토용 휘발 상태라
> 격리 원칙상 메인 앱 차트 내부에 결합하지 않는다. 메인 앱 수신부는 `frontend/src/lib/evaluatorBridge.svelte.js`.

호스트 통합은 제네릭 확장 시스템(`backend/core/extensions_loader.py` + `main.py` 2줄 +
`App.spec` 글롭 1블록)이 담당하며 evaluator 비특정이다.
