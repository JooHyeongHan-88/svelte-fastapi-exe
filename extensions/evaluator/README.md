# evaluator — parquet 큐레이션 확장

AI Agent 가 만든 parquet 산출물을 사람이 **시각적으로 검토·선별·재정렬**해 최종
리포트용 데이터로 만드는 확장 툴. 메인 채팅 앱과 독립적이며, **이 폴더(`extensions/evaluator/`)
를 통째로 지워도 메인 앱은 그대로 동작**한다(확장 시스템의 try/except no-op).

## 동작

소스 parquet 의 컬럼을 **역할**로 매핑한다(기본값은 예시 데이터 컬럼명). 역할은 두 군으로
나뉜다 — **공통**(어느 차트든 필요)과 **차트별**(선택한 차트 종류에 따라 가변):

| 군 | 역할 | 기본 컬럼 | 다중 | 설명 |
|---|---|---|---|---|
| 공통 | 선택 기준 `select` | `item_id` | — | 좌측 리스트의 행 단위(체크 대상) |
| 공통 | Sort 기준 `sort` | `rank` | — | 최초 정렬 순서 · 내보내기 시 정수 재계산 대상 |
| 공통 | 레전드 `legend` | `category` | ✅ | 시리즈 그룹(범례). **여러 컬럼 선택 시 `POR \| A` 처럼 합성** |
| 공통 | 설명 `desc` | `item_desc` | — | 리스트 보조 설명 — **없어도 됨**(컬럼 부재 시 생략) |
| 차트별 | X축 `x` | `tkout_time` | — | 가로축 (scatter/line/bar/histogram/ecdf/heatmap) |
| 차트별 | Y축 `y` | `value` | — | 세로축 (scatter/line/bar/box/heatmap) |
| 차트별 | 집계 `aggregate` | `mean` | — | bar 전용 — 같은 X 값 묶음 집계(평균/합/개수/최소/최대) |

### 차트 종류 (메인 앱 `display_chart` 와 동일 7종)

본문 상단의 세그먼트 셀렉터로 차트 종류를 바꾼다. 종류를 바꾸면 **필요한 차트별 매핑 역할도
달라진다**(공통 4역할은 항상 동일). 차트 종류 변경은 데이터를 다시 읽지 않고 재렌더만 한다.

| mark | 필요 차트별 역할 | brush 점 필터 | 비고 |
|---|---|---|---|
| `scatter` 산점도 | x, y | ✅ | 상관관계 |
| `line` 선 | x, y | ✅ (투명 overlay) | x 정렬 추세 |
| `bar` 막대 | x, y (+집계) | — | x 범주별 y 집계, 레전드별 그룹 막대 |
| `box` 박스 | y | — | 레전드 그룹별 사분위 박스 |
| `histogram` 히스토그램 | x | — | 전체 범위 공유 10빈, 그룹별 겹침 |
| `ecdf` 누적분포 | x | ✅ (투명 overlay) | 그룹별 누적비율 계단선 |
| `heatmap` 히트맵 | x, y | — | x×y 셀 **빈도 밀도**(색=카운트, 레전드 미사용) |

- **매핑 설정**: 본문 상단 **⚙ 매핑 설정** 버튼으로 모달을 연다. 각 역할마다 **설명 + 컬럼
  드롭다운**(소스 스키마 기반)을 제공하고, legend 는 컬럼 토글 칩으로 **다중 선택**한다(선택
  순서가 합성 순서). 차트 종류·매핑은 **저장하기** 시 사이드카에 영속돼 재진입 시 복원된다.
  컬럼 역할이 바뀌면 데이터를 다시 읽되 **이미 한 선택·순서는 보존**한다(선택키 집합 불변 시).
- **좌측(너비 조절 가능)**: 선택 기준이 Sort 기준 순으로 나열. 진입 시 **전부 체크(선택)** 된 상태가
  기본. **↑/↓** 하이라이트 이동 · **Space** 선택 토글 · 행을 **드래그&드롭** 해 순서 변경(드롭 대상
  앞에 삽입). 패널 우측 경계를 드래그해 너비를 조절한다. **검색(키·설명)·legend 필터·일괄 선택
  (전체/해제/반전)** 으로 대량 후보를 빠르게 선별한다 — 필터는 **표시만 좁히고** 순서·내보내기 의미는
  바꾸지 않으며, 일괄 버튼은 **현재 표시된(필터된) 항목**에만 적용된다.
- **본문(차트 그리드)**: 항목을 **클릭하면 그 항목의 차트를 표시**한다. **Ctrl/⌘+클릭으로 토글**,
  **Shift+클릭으로 범위**를 한 번에 선택하고, 상단 **전체 보기 / 보기 해제** 버튼으로 일괄 제어한다.
  선택된 차트는 그리드(페이지당 6개·페이지네이션)로 보이며 각 차트는 제목 패널로 감싸인다.
- **병합 보기**: 상단 **차트 보기 제어**의 토글. 표시 선택된 차트들의 **소스 데이터만 하나로 합쳐**
  단일 차트로 비교하되, **항목별 차트의 매핑 요소(legend 포함)를 그대로 유지**한다(legend 를 항목
  키로 덮어쓰지 않음 — 읽기전용 비교 뷰).
- 메인 앱 `display_chart` 와 같은 UX:
  - 차트를 **클릭하면 확대 라이트박스**(리사이즈·좌우 네비)로 연다.
  - 라이트박스 툴바: **Filter / Filter All / Reset / Undo / Redo** + **Legend** 편집 패널
    (드래그 순서 · 색상 · 눈 표시/숨김 · 체크 후 Filter 로 제외). 차트 상호작용은 **클라이언트
    사이드**라 라운드트립이 없다. **Filter(점·레전드 그룹 제외)는 '이 행을 최종 데이터에서
    뺀다'는 데이터 결정이라 내보내기 결과 parquet 에 실제로 반영**되고, 레전드 순서·색상·눈
    표시/숨김은 **시각 전용**이라 데이터에 반영하지 않는다.
- **하단**: **큐레이션 메모(선택)** 입력 · **저장하기**(선택·순서·차트설정을 사이드카 JSON 으로 저장)
  · **내보내기**(선택 항목만 필터 + **Filter 로 제외한 행 실제 삭제** + 리스트 순서대로 `sort` 컬럼을
  1..N 정수로 재계산 → `<stem>.curated.parquet`).
  내보내기 성공 시 같은 출처(same-origin)인 **메인 앱 탭에 `BroadcastChannel("evaluator:exports")`
  로 알림**을 보낸다. 메인 앱은 그 parquet 을 **데이터 칩**으로 인폼하되, **사람의 결정 요약**
  (`/export` 응답 `summary` — 후보 N개 중 M개 선택·X행 제외·메모)을 칩 배너로 띄우고 **"이어서 작업"**
  버튼으로 그 맥락을 담은 후속 프롬프트를 채팅 입력창에 시드한다(루프 환류). 세션 상관키는 소스
  경로의 `<session>`.

## 진입

```
http://127.0.0.1:<port>/ext/evaluator/?path=result/<session>/<ts>/<file>.parquet
```

매핑 오버라이드도 쿼리로 전달 가능: `&select=item_id&sort=rank&x=tkout_time&y=value&legend=category&desc=item_desc`
(legend 는 다중 컬럼이면 `&legend=category&legend=item_id` 처럼 반복한다.) `open_curation`
번들의 `mapping.legend` 도 문자열 또는 문자열 리스트 둘 다 받는다. 번들의 선택적 `mark`
(scatter/line/bar/box/histogram/ecdf/heatmap)로 **기본 차트 종류**를 지정할 수 있다(생략 시 scatter).

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
    src/App.svelte           # 좌측 리스트 + 차트 종류 셀렉터 + 매핑 설정 모달 + 그리드
    src/lib/chartOption.js   # mark 별 빌더 디스패처(7종) — points+스냅샷 → ECharts option
    src/lib/chartState.svelte.js  # 선택키별 제외/레전드 undo/redo 스냅샷 스택(클라이언트)
    src/lib/ChartCell.svelte      # 단일 ECharts(그리드 셀/라이트박스, mark·roles, brush)
    src/lib/ChartGrid.svelte      # 제목 패널 + 6/페이지 페이지네이션 그리드
    src/lib/ChartLightbox.svelte  # 확대 모달 + Filter/Reset/Legend 툴바(인라인 SVG)
  scripts/make_sample.py     # 예시 parquet 생성기
```

> 차트는 메인 앱 `display_chart`(백엔드 spec→render→`/api/chart/filter` 파이프라인)와 달리
> **클라이언트에서 직접** 구성한다 — points 가 이미 적재돼 있고 필터/레전드는 검토용 휘발 상태라
> 격리 원칙상 메인 앱 차트 내부에 결합하지 않는다. 메인 앱 수신부는 `frontend/src/lib/evaluatorBridge.svelte.js`.

호스트 통합은 제네릭 확장 시스템(`backend/core/extensions_loader.py` + `main.py` 2줄 +
`App.spec` 글롭 1블록)이 담당하며 evaluator 비특정이다.
