# evaluator — parquet 큐레이션 확장

AI Agent 가 만든 parquet 산출물을 사람이 **시각적으로 검토·선별·재정렬**해 최종
리포트용 데이터로 만드는 확장 툴. 메인 채팅 앱과 독립적이며, **이 폴더(`extensions/evaluator/`)
를 통째로 지워도 메인 앱은 그대로 동작**한다(확장 시스템의 try/except no-op).

## 동작

소스 parquet 의 컬럼을 5개 역할로 매핑한다(기본값은 예시 데이터 컬럼명):

| 역할 | 기본 컬럼 | 설명 |
|---|---|---|
| 선택 기준 `select` | `item_id` | 좌측 리스트의 행 단위(체크 대상) |
| Sort 기준 `sort` | `rank` | 최초 정렬 순서 · 내보내기 시 정수 재계산 대상 |
| 차트 x `x` | `tkout_time` | scatter x축 |
| 차트 y `y` | `value` | scatter y축 |
| 레전드 `legend` | `category` | scatter 시리즈 그룹(예: POR/NEW) |
| 설명 `desc` | `item_desc` | 리스트 보조 설명 |

- 좌측: 선택 기준이 Sort 기준 순으로 나열. **↑/↓** 로 하이라이트 이동, **Space** 로 선택 토글,
  행의 **↑↓** 버튼으로 순서 변경.
- 본문: 하이라이트된 항목의 데이터를 scatter 로 즉시 표시(클라이언트 사이드 재구성, 라운드트립 없음).
- 하단: **저장하기**(선택·순서 상태를 사이드카 JSON 으로 저장) · **내보내기**(선택 항목만 필터 +
  리스트 순서대로 `sort` 컬럼을 1..N 정수로 재계산 → `<stem>.curated.parquet`).

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
  scripts/make_sample.py     # 예시 parquet 생성기
```

호스트 통합은 제네릭 확장 시스템(`backend/core/extensions_loader.py` + `main.py` 2줄 +
`App.spec` 글롭 1블록)이 담당하며 evaluator 비특정이다.
