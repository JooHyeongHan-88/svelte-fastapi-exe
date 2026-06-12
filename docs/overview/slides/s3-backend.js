// Part 3 — Backend 동작 흐름 (11장)
const { T, lightSlide, header, card, chip, numDot, codeBlock, table, lines } = require("./theme");

function s_duties(pres) {
  const s = lightSlide(pres);
  header(s, "PART 3 · BACKEND", "백엔드의 5가지 책임", { sub: "단순 API 서버가 아니라, 데스크탑 앱의 모든 서버 측 역할을 겸한다" });
  const duties = [
    ["정적 서빙", "Svelte SPA · 산출물 파일 제공", "main.py (StaticFiles)"],
    ["HTTP API", "채팅·설정·산출물·차트 REST/SSE", "api/"],
    ["에이전트 하니스", "LLM ↔ 도구 실행 루프", "agent/"],
    ["생명주기", "브라우저 연동 자동 기동·종료", "core/browser.py"],
    ["자동 업데이트", "버전 확인·다운로드·자가 교체", "core/updater.py"],
  ];
  duties.forEach((d, i) => {
    const col = i % 3, row = Math.floor(i / 3);
    const x = 0.7 + col * 4.12, y = 2.0 + row * 2.3, w = 3.85, h = 2.05;
    card(pres, s, x, y, w, h);
    numDot(pres, s, x + 0.25, y + 0.25, 0.42, i + 1);
    s.addText(d[0], { x: x + 0.82, y: y + 0.25, w: w - 1.05, h: 0.42, fontFace: T.KR, fontSize: 14.5, bold: true, color: T.INK, valign: "middle", margin: 0 });
    s.addText(d[1], { x: x + 0.25, y: y + 0.85, w: w - 0.5, h: 0.6, fontFace: T.KR, fontSize: 11, color: T.MUT, margin: 0, lineSpacingMultiple: 1.2 });
    chip(pres, s, x + 0.25, y + 1.5, w - 1.6, 0.36, d[2], { font: T.MONO, size: 9.5 });
  });
  card(pres, s, 4.82, 4.3, 7.83, 2.05, { fill: T.BG2, noLine: true });
  s.addText([
    { text: "이 파트에서 따라갈 경로  ", options: { bold: true, color: T.ACC_DK, fontSize: 12, breakLine: true, paraSpaceAfter: 6 } },
    { text: "기동 시퀀스 → 생명주기 → API 지도 → 모듈 지도", options: { fontSize: 12, color: T.INK, breakLine: true, paraSpaceAfter: 4 } },
    { text: "→ 채팅 한 턴(run_turn) → 라우팅·위임 → Registry·도구 → 산출물 파이프라인 → 안전장치", options: { fontSize: 12, color: T.INK } },
  ], { x: 5.12, y: 4.62, w: 7.25, h: 1.5, fontFace: T.KR, margin: 0, lineSpacingMultiple: 1.35 });
}

function s_boot(pres) {
  const s = lightSlide(pres);
  header(s, "PART 3 · BACKEND", "기동 시퀀스 & 생명주기");
  // 좌: 기동 7단계
  s.addText("EXE 더블클릭 → 첫 화면까지  (main.py)", { x: 0.7, y: 1.7, w: 6, h: 0.32, fontFace: T.KR, fontSize: 13, bold: true, color: T.INK, margin: 0 });
  const steps = [
    ["소켓 바인딩", "frozen은 APP_NAME 해시 기반 고정 포트 (47100–48999) — 재기동 후 대화 기록 보존"],
    ["도구 자기등록", "import 시 @register_tool 데코레이터가 레지스트리 채움"],
    ["레지스트리 로드", "PROMPTS·SKILLS·AGENTS 메타 1회 + 교차 검증"],
    ["라우터 등록", "/api/* — SPA catch-all보다 먼저 (순서 중요)"],
    ["정적 mount", "/ · /assets · /result · /workspace"],
    ["데몬 스레드", "watchdog(생존 감시) + open_browser(자동 오픈)"],
    ["server.run()", "uvicorn 이벤트 루프 시작"],
  ];
  steps.forEach((st, i) => {
    const y = 2.15 + i * 0.63;
    numDot(pres, s, 0.7, y, 0.36, i + 1, { size: 10 });
    s.addText(st[0], { x: 1.2, y, w: 1.85, h: 0.36, fontFace: T.KR, fontSize: 11, bold: true, color: T.INK, valign: "middle", margin: 0 });
    s.addText(st[1], { x: 3.1, y, w: 3.6, h: 0.36, fontFace: T.KR, fontSize: 9.5, color: T.MUT, valign: "middle", margin: 0 });
  });
  // 우: presence
  s.addText("Presence & Watchdog — “탭이 곧 전원 스위치”", { x: 7.05, y: 1.7, w: 5.6, h: 0.32, fontFace: T.KR, fontSize: 13, bold: true, color: T.INK, margin: 0 });
  codeBlock(pres, s, 7.05, 2.15, 5.6, 2.6, [
    { t: "브라우저                    백엔드", c: T.CODE_MUT },
    { t: "GET /api/presence ───────→ 연결 = 생존 신호", c: T.CODE_TX },
    { t: "   ← : ping (30초마다 keepalive)", c: T.CODE_MUT },
    { t: "" },
    { t: "탭 닫힘 → SSE 종료 ──────→ 2초 유예(F5 흡수)", c: T.CODE_TX },
    { t: "                  watchdog: 클라이언트 0명", c: T.CODE_ACC },
    { t: "                  → 유예 후 서버 자가 종료", c: T.CODE_ACC, b: true },
  ], { size: 9.5, lh: 1.35 });
  lines(s, 7.05, 5.0, 5.6, 1.6, [
    { t: "세션 전부 삭제해도 서버 유지 — keepalive 채널로 세션과 생존을 분리", bullet: { code: "2022", color: T.ACC }, s: 10.5, c: T.MUT, gap: 6 },
    { t: "탭 복제는 연결 카운트로 관리 — 마지막 연결이 끊겨야 종료 유예 진입", bullet: { code: "2022", color: T.ACC }, s: 10.5, c: T.MUT, gap: 6 },
    { t: "첫 연결 전엔 STARTUP_GRACE(60초)까지 대기 — 브라우저가 늦게 떠도 안전", bullet: { code: "2022", color: T.ACC }, s: 10.5, c: T.MUT },
  ]);
}

function s_api(pres) {
  const s = lightSlide(pres);
  header(s, "PART 3 · BACKEND", "HTTP API 전체 지도", { sub: "라우터 7개 — 전 엔드포인트에 Origin 가드 적용 (frozen에서 외부 출처 요청 차단)" });
  table(pres, s, 0.7, 1.95, 11.95, ["그룹", "대표 엔드포인트", "역할"], [
    ["채팅", { t: "POST /api/chat", mono: true, s: 9.5 }, "턴 실행 — SSE 이벤트 스트림 · force_skills(슬래시) 지원"],
    ["대화 동기화", { t: "POST /api/conversation/restore · DELETE …", mono: true, s: 9.5 }, "localStorage → 백엔드 컨텍스트 복원(hydrate) · 삭제"],
    ["생존", { t: "GET /api/presence", mono: true, s: 9.5 }, "SSE 생존 채널 — 생명주기의 근거"],
    ["설정", { t: "GET·POST /api/settings · /models · /test", mono: true, s: 9.5 }, "LLM 설정 CRUD(키 마스킹) · 모델 목록 · 연결 테스트"],
    ["스킬", { t: "GET /api/skills", mono: true, s: 9.5 }, "SKILL 카탈로그 — 슬래시 커맨드 자동완성"],
    ["업데이트", { t: "GET /update/check · POST /update/apply · /status", mono: true, s: 9.5 }, "버전 확인 · 적용 · 진행 상태 폴링"],
    ["차트", { t: "POST /api/chart/filter · GET /filter-state", mono: true, s: 9.5 }, "brush 필터·레전드·undo/redo — 재렌더 결과 반환"],
    ["산출물", { t: "GET /api/artifact/preview · /csv · POST /reveal", mono: true, s: 9.5 }, "parquet 미리보기 · CSV 변환 · 산출물 폴더 탐색기 열기 (데이터 칩)"],
    ["정적", { t: "/ · /assets · /result · /workspace", mono: true, s: 9.5 }, "SPA · 빌드 자산 · 에이전트 산출물 · 도구 생성 파일"],
  ], { size: 10.5, colW: [1.55, 5.0, 5.4], rowH: 0.45 });
}

function s_modules(pres) {
  const s = lightSlide(pres);
  header(s, "PART 3 · BACKEND", "모듈 지도 — backend/ 폴더별 책임");
  const cols = [
    { name: "core/  — 기반 시설", items: [
      ["config.py", "경로·포트의 단일 진실 공급원, frozen/dev 분기"],
      ["browser.py", "presence 카운트·watchdog·자동 오픈·종료 제어"],
      ["result_store.py", "산출물 슬롯 발급·경로 해석·세션 manifest"],
      ["updater.py", "업데이트 확인→다운로드→검증→Updater 기동"],
    ]},
    { name: "api/  — HTTP 경계", items: [
      ["chat.py", "채팅 SSE·대화 복원/삭제·동시 턴 가드"],
      ["presence.py / skills.py", "생존 채널 · SKILL 카탈로그"],
      ["settings.py / update.py", "설정 CRUD·연결 테스트 · 업데이트 4단계 노출"],
      ["chart.py / artifact.py", "차트 필터 액션 · parquet 미리보기/CSV"],
    ]},
    { name: "agent/  — 하니스 (핵심)", items: [
      ["harness.py", "run_turn — 턴 전 과정 오케스트레이션"],
      ["guard.py / models.py", "슬롯 가드 분기 · 전체 데이터 모델"],
      ["providers/ registries/", "LLM 어댑터(mock·openai) · 레지스트리 4종"],
      ["tools/ runtime/ stores/ charts/", "내장 도구 · 안전 실행 인프라 · 히스토리/상태 · 차트 렌더"],
    ]},
  ];
  cols.forEach((c, i) => {
    const x = 0.7 + i * 4.12, w = 3.85;
    card(pres, s, x, 1.75, w, 4.55);
    s.addText(c.name, { x: x + 0.24, y: 1.93, w: w - 0.48, h: 0.34, fontFace: T.MONO, fontSize: 12, bold: true, color: T.ACC_DK, margin: 0 });
    c.items.forEach((it, j) => {
      const y = 2.42 + j * 0.95;
      s.addText(it[0], { x: x + 0.24, y, w: w - 0.48, h: 0.26, fontFace: T.MONO, fontSize: 9.5, bold: true, color: T.INK, margin: 0 });
      s.addText(it[1], { x: x + 0.24, y: y + 0.27, w: w - 0.48, h: 0.6, fontFace: T.KR, fontSize: 9.5, color: T.MUT, margin: 0, lineSpacingMultiple: 1.15 });
    });
  });
  card(pres, s, 0.7, 6.5, 11.95, 0.62, { fill: T.BG2, noLine: true });
  s.addText([
    { text: "settings/", options: { fontFace: T.MONO, bold: true, color: T.INK, fontSize: 10.5 } },
    { text: " LLM 설정 저장소 (멀티 프로바이더 슬롯·키 마스킹)    ", options: { color: T.MUT, fontSize: 10.5 } },
    { text: "scripts/", options: { fontFace: T.MONO, bold: true, color: T.INK, fontSize: 10.5 } },
    { text: " 에이전트에 노출할 도메인 유틸 패키지    ", options: { color: T.MUT, fontSize: 10.5 } },
    { text: "tests/", options: { fontFace: T.MONO, bold: true, color: T.INK, fontSize: 10.5 } },
    { text: " 하니스·가드·산출물 파이프라인 pytest", options: { color: T.MUT, fontSize: 10.5 } },
  ], { x: 1.0, y: 6.5, w: 11.4, h: 0.62, fontFace: T.KR, valign: "middle", margin: 0 });
}

function s_runturn(pres) {
  const s = lightSlide(pres);
  header(s, "PART 3 · BACKEND", "채팅 한 턴의 처리 흐름 — run_turn()", { sub: "사용자 입력 1건 = run_turn 1회 = 완결된 응답 턴 — 백엔드의 심장부" });
  codeBlock(pres, s, 0.7, 1.95, 7.6, 4.95, [
    { t: "POST /api/chat", c: T.CODE_ACC, b: true },
    { t: " ├ [동시 턴 가드] 같은 세션 생성 중이면 즉시 거부", c: T.CODE_MUT },
    { t: " ▼" },
    { t: "run_turn()", c: T.CODE_ACC, b: true },
    { t: " ① 상태 로드     todo·pending 복원 (종결 todo는 리셋)" },
    { t: " ② SKILL 선택    trigger 매칭 또는 슬래시 강제 지정" },
    { t: " ③ 프롬프트 합성  PROMPTS+SKILL+카탈로그+state+산출물 목록" },
    { t: " ④ 스킬 뱃지     SkillActiveEvent → 프론트 즉시 표시" },
    { t: " ⑤ 에이전트 루프  (최대 8회 반복)", b: true },
    { t: "     provider.astream() — LLM 스트리밍 호출", c: T.CODE_TX },
    { t: "      ├ delta     → 실시간 타이핑 중계" },
    { t: "      ├ tool_call → sentinel? 하니스 직접 처리", c: T.CODE_ACC },
    { t: "      │            슬롯 가드: 누락→사용자 질문 /", c: T.CODE_ACC },
    { t: "      │                     형식 오류→LLM 자가수정", c: T.CODE_ACC },
    { t: "      │            일반 도구 → 실행(timeout) → 결과", c: T.CODE_ACC },
    { t: "      └ done      → 결과 있으면 루프 계속, 없으면 종료" },
    { t: " ⑥ 영속화        히스토리 append + 상태 저장" },
    { t: " ⑦ DoneEvent     정확히 1회 보장 — 스트리밍 종료", b: true },
  ], { size: 9.5, lh: 1.28 });
  // 우측 설명
  const notes = [
    ["왜 루프인가", "LLM이 “도구 호출 → 결과 확인 → 다음 행동 결정”을 여러 번 거치며 작업을 완성하기 때문"],
    ["상한 도달 시", "그때까지의 결과로 응급 응답(salvage) — todo 전부 완료면 “완료(예산 소진)”, 아니면 “미완료 주의”로 구분 표시"],
    ["히스토리 절약", "도구 결과는 현재 턴엔 전문 유지, 히스토리엔 800자 절단 저장 — 다음 턴 컨텍스트 비대화 방지"],
  ];
  notes.forEach((n, i) => {
    const y = 2.0 + i * 1.62;
    card(pres, s, 8.6, y, 4.05, 1.45);
    s.addText(n[0], { x: 8.86, y: y + 0.12, w: 3.55, h: 0.3, fontFace: T.KR, fontSize: 11.5, bold: true, color: T.ACC_DK, margin: 0 });
    s.addText(n[1], { x: 8.86, y: y + 0.45, w: 3.55, h: 0.95, fontFace: T.KR, fontSize: 9.8, color: T.MUT, margin: 0, lineSpacingMultiple: 1.2 });
  });
}

function s_sse(pres) {
  const s = lightSlide(pres);
  header(s, "PART 3 · BACKEND", "SSE 이벤트 — 백엔드→프론트 스트리밍 프로토콜", { sub: "프론트는 이 이벤트만으로 모든 UI를 그린다 — 한 턴 동안 흘러가는 13종" });
  const L = [
    ["skill_active", "턴 시작, 스킬 매칭 직후", "스킬 뱃지"],
    ["reasoning", "LLM 중간 판단 설명", "ReasoningBlock"],
    ["delta", "텍스트 토큰 생성", "말풍선 실시간 타이핑"],
    ["tool_call", "도구 호출 시작", "도구 카드 (running)"],
    ["tool_result", "도구 완료/실패", "카드 종결 + 산출물 칩"],
    ["todo_update", "add/complete_todo", "TodoProgress 갱신"],
    ["ask_user", "사용자 입력 필요", "AskUserCard + 턴 중단"],
  ];
  const R = [
    ["agent:switch", "서브 에이전트 위임 시작", "트레일 카드 생성"],
    ["agent:progress", "서브 내부 진행", "트레일 세그먼트 채움"],
    ["agent:return", "서브 완료", "트레일 종결 + 요약"],
    ["skill_complete", "todo 전원 종결", "완료 뱃지"],
    ["error", "오류·예산 소진", "점선 박스 (초록/빨강)"],
    ["done", "턴 종료 (정확히 1회)", "스트리밍 종료·완료 마커"],
  ];
  const mk = (rows) => rows.map((r) => [{ t: r[0], mono: true, s: 9.5, b: true }, r[1], r[2]]);
  table(pres, s, 0.7, 2.0, 5.95, ["이벤트", "발생 시점", "프론트 반영"], mk(L), { size: 9.5, colW: [1.55, 2.2, 2.2], rowH: 0.42 });
  table(pres, s, 6.95, 2.0, 5.7, ["이벤트", "발생 시점", "프론트 반영"], mk(R), { size: 9.5, colW: [1.65, 2.0, 2.05], rowH: 0.42 });
  card(pres, s, 6.95, 5.5, 5.7, 1.15, { fill: T.BG2, noLine: true });
  s.addText([
    { text: "병렬 위임의 상관키  ", options: { bold: true, color: T.ACC_DK, fontSize: 10.5 } },
    { text: "agent:* 이벤트는 dispatch_id를 실어 — 같은 이름 에이전트가 동시에 떠도 프론트가 정확한 트레일로 라우팅한다", options: { color: T.INK, fontSize: 10.5 } },
  ], { x: 7.22, y: 5.62, w: 5.15, h: 0.92, fontFace: T.KR, margin: 0, lineSpacingMultiple: 1.25 });
}

function s_routing(pres) {
  const s = lightSlide(pres);
  header(s, "PART 3 · BACKEND", "오케스트레이터 라우팅 & 서브 에이전트 위임");
  // 좌: Case
  s.addText("결정론적 라우팅 — Case 0~5  (PROMPTS/orchestrator.md)", { x: 0.7, y: 1.68, w: 6.5, h: 0.3, fontFace: T.KR, fontSize: 12.5, bold: true, color: T.INK, margin: 0 });
  table(pres, s, 0.7, 2.08, 6.35, ["Case", "조건 → 행동"], [
    [{ t: "0", align: "center", b: true }, "요청이 모호함 → 도구 호출 전에 ask_user로 먼저 질문"],
    [{ t: "1", align: "center", b: true }, "일상 대화 → 도구 없이 즉시 텍스트 응답"],
    [{ t: "2", align: "center", b: true }, "에이전트 지명 → 지명된 에이전트에 즉시 위임"],
    [{ t: "3", align: "center", b: true, fill: T.ACC_SOFT }, { t: "스킬 트리거 + 전담 에이전트 존재 → 자동 위임 (직접 실행 금지)", b: true, fill: T.ACC_SOFT }],
    [{ t: "4", align: "center", b: true }, "전담 에이전트 없음 → 오케스트레이터가 직접 도구 실행"],
    [{ t: "5", align: "center", b: true }, "마지막 응답 → “무엇을/결과/다음 행동” 완료 보고"],
  ], { size: 10, colW: [0.7, 5.65], rowH: 0.43 });
  s.addText("Case 3가 핵심 — SKILL(무엇을) × AGENT(누가)의 매핑을 설정 파일이 결정한다", {
    x: 0.7, y: 4.95, w: 6.35, h: 0.55, fontFace: T.KR, fontSize: 10.5, italic: true, color: T.ACC_DK, margin: 0, lineSpacingMultiple: 1.2,
  });
  // 우: 위임
  s.addText("위임 방식 — 의존성으로 갈린다", { x: 7.4, y: 1.68, w: 5.3, h: 0.3, fontFace: T.KR, fontSize: 12.5, bold: true, color: T.INK, margin: 0 });
  const d = [
    ["call_sub_agent  (순차)", "작업이 하나거나 앞 결과를 뒤가 사용 — 격리 컨텍스트에서 실행, 완료 요약만 복귀"],
    ["call_sub_agents_parallel  (병렬)", "독립 작업 여러 개 동시 실행 (semaphore 상한 3) — 전원 완료 후 요약을 하나로 합쳐 복귀"],
  ];
  d.forEach((x, i) => {
    const y = 2.08 + i * 1.28;
    card(pres, s, 7.4, y, 5.25, 1.12);
    s.addText(x[0], { x: 7.66, y: y + 0.12, w: 4.8, h: 0.28, fontFace: T.MONO, fontSize: 10.5, bold: true, color: T.ACC_DK, margin: 0 });
    s.addText(x[1], { x: 7.66, y: y + 0.44, w: 4.8, h: 0.6, fontFace: T.KR, fontSize: 9.8, color: T.MUT, margin: 0, lineSpacingMultiple: 1.2 });
  });
  table(pres, s, 7.4, 4.85, 5.25, ["안전 제약", "구현"], [
    ["서브의 재위임 불가", "4중 방어선 (무한 재귀 차단)"],
    ["LLM 호출 총량", "TurnBudget — 합산 상한 20회"],
    ["같은 에이전트 반복", "3회 연속 위임 시 loop-guard"],
  ], { size: 9.5, colW: [2.1, 3.15], rowH: 0.37 });
  card(pres, s, 0.7, 5.7, 6.35, 1.0, { fill: T.BG2, noLine: true });
  s.addText([
    { text: "격리 실행  ", options: { bold: true, color: T.ACC_DK, fontSize: 10.5 } },
    { text: "서브 에이전트는 별도 메시지·별도 상태에서 실행되고 완료 시 요약만 반환 — 메인 컨텍스트 오염을 막는다. 병렬 중 입력이 필요한 작업은 그것만 ‘입력 필요’로 종료 보고.", options: { color: T.INK, fontSize: 10.5 } },
  ], { x: 0.98, y: 5.82, w: 5.8, h: 0.8, fontFace: T.KR, margin: 0, lineSpacingMultiple: 1.2 });
}

function s_registry(pres) {
  const s = lightSlide(pres);
  header(s, "PART 3 · BACKEND", "Registry 4종 & 도구 시스템", { sub: "“정의 파일 → 런타임 객체” — 메타데이터는 부팅 시 가볍게, 본문은 필요할 때 lazy" });
  table(pres, s, 0.7, 1.95, 11.95, ["Registry", "원천", "관리 대상", "로딩 정책"], [
    [{ t: "PromptRegistry", mono: true, s: 10 }, "PROMPTS/*.md", "기반 system prompt 합성", "매 턴 읽기 — dev는 핫리로드"],
    [{ t: "SkillRegistry", mono: true, s: 10 }, "SKILLS/*.md", "트리거 매칭·슬래시 강제 지정", "메타 부팅 1회, 본문 첫 매칭 시"],
    [{ t: "AgentRegistry", mono: true, s: 10 }, "AGENTS/*.md", "서브 에이전트 카탈로그·Case 3 매핑", "메타 부팅 1회, 본문 위임 시"],
    [{ t: "ToolRegistry", mono: true, s: 10 }, "@register_tool", "도구 스키마·검증기·실행 함수", "import 시 자기등록"],
  ], { size: 10.5, colW: [2.3, 2.1, 4.0, 3.55], rowH: 0.42 });
  // 도구 등록
  codeBlock(pres, s, 0.7, 4.15, 6.6, 2.6, [
    { t: "@register_tool(", c: T.CODE_ACC, b: true },
    { t: '  description="매출 데이터를 기간으로 조회한다.",' },
    { t: '  slot_prompts={"date_from": "시작일을 알려주세요"},' },
    { t: "  timeout_seconds=15)", c: T.CODE_ACC },
    { t: "async def fetch_sales(" },
    { t: '  date_from: Annotated[date, "조회 시작일"], ...' },
    { t: ") -> ToolResult:  # content=LLM 요약, data=프론트 전달", c: T.CODE_MUT },
  ], { size: 9.5, lh: 1.3 });
  // 우: 검증/안전
  const g = [
    ["슬롯 가드 — 오류 책임자 분기", "필수 값 없음 → 사용자에게 질문 / 형식 틀림 → LLM이 같은 턴에 자가수정"],
    ["자동 스키마", "함수 시그니처(Annotated)에서 JSON Schema + 입력 검증을 한 번에 생성"],
    ["Sentinel 도구", "add_todo 등은 하니스가 가로채 처리 — 함수 본문은 절대 실행 안 됨"],
  ];
  g.forEach((x, i) => {
    const y = 4.15 + i * 0.92;
    card(pres, s, 7.55, y, 5.1, 0.8);
    s.addText(x[0], { x: 7.8, y: y + 0.08, w: 4.6, h: 0.26, fontFace: T.KR, fontSize: 10.5, bold: true, color: T.ACC_DK, margin: 0 });
    s.addText(x[1], { x: 7.8, y: y + 0.36, w: 4.65, h: 0.42, fontFace: T.KR, fontSize: 9.3, color: T.MUT, margin: 0, lineSpacingMultiple: 1.12 });
  });
}

function s_tools(pres) {
  const s = lightSlide(pres);
  header(s, "PART 3 · BACKEND", "Built-in 도구 카탈로그 — 5그룹 23종", { sub: "새 도구를 추가하기 전부터 내장된 도구 전체 (인자 상세: docs/builtin-tools.md)" });
  const groups = [
    ["계획·상호작용 (Sentinel)", "7", "add_todo · complete_todo · ask_user · activate_skill · call_sub_agent · call_sub_agents_parallel · complete_subagent", "하니스가 직접 처리 — 계획 수립·되묻기·위임·종료 보고"],
    ["산출물 저장·재발견", "3", "save_artifact · list_artifacts · load_artifact", "파일 영속(markdown·json·parquet·바이너리) → 목록 재발견 → 변수로 복원 — 세션을 넘는 재사용"],
    ["시각화", "3", "display_image · display_chart · display_markdown", "아티팩트 패널로 전달 — 갤러리 · ECharts · 보고서 렌더링"],
    ["라이브러리 런타임 메타", "8", "inspect_callable · list_module_members · call_function · eval_expression · exec_code · list_namespace · describe_variable · delete_variable", "api_refs 활성 시 자동 노출 — 외부 Python 라이브러리를 wrapper 없이 동적 사용"],
    ["데모", "1", "now", "현재 시각 반환 — 등록 패턴 예시 겸용"],
  ];
  groups.forEach((g, i) => {
    const y = 2.0 + i * 0.92;
    card(pres, s, 0.7, y, 11.95, 0.8);
    s.addText(g[0], { x: 0.98, y: y + 0.08, w: 2.9, h: 0.3, fontFace: T.KR, fontSize: 11, bold: true, color: T.INK, margin: 0 });
    numDot(pres, s, 3.62, y + 0.24, 0.34, g[1], { size: 9.5, font: T.KR });
    s.addText(g[2], { x: 4.2, y: y + 0.07, w: 8.2, h: 0.42, fontFace: T.MONO, fontSize: 8.8, color: T.ACC_DK, bold: true, margin: 0, lineSpacingMultiple: 1.1 });
    s.addText(g[3], { x: 0.98, y: y + 0.42, w: 2.9, h: 0.36, fontFace: T.KR, fontSize: 8.2, color: T.FAINT, margin: 0, lineSpacingMultiple: 1.05 });
    s.addShape(pres.shapes.LINE, { x: 4.2, y: y + 0.52, w: 8.15, h: 0, line: { color: T.LINE, width: 0.75 } });
    s.addText(g[3], { x: 4.2, y: y + 0.55, w: 8.2, h: 0.24, fontFace: T.KR, fontSize: 8.8, color: T.MUT, margin: 0 });
  });
  codeBlock(pres, s, 0.7, 6.7, 11.95, 0.52, [
    { t: "노출 규칙   오케스트레이터=전체−complete_subagent  ·  서브=화이트리스트−위임 도구  ·  list/load_artifacts=항상  ·  메타 8종=api_refs 있을 때", s: 9 },
  ], { size: 9, valign: "middle", padY: 0.06 });
}

function s_pipeline(pres) {
  const s = lightSlide(pres);
  header(s, "PART 3 · BACKEND", "산출물 & 차트 파이프라인 — 세션을 넘는 영속");
  // 좌: 산출물
  codeBlock(pres, s, 0.7, 1.78, 5.9, 2.15, [
    { t: "result/", c: T.CODE_ACC, b: true },
    { t: "└ <세션제목>-<id8>/         세션 단위" },
    { t: "   ├ _artifacts.jsonl      manifest(장부)", c: T.CODE_ACC },
    { t: "   └ <YYYYMMDD-HHmmss>/    턴 단위 슬롯" },
    { t: "      ├ data.parquet  charts.spec.json" },
    { t: "      └ charts.json   report.md" },
  ], { size: 9.5, lh: 1.3 });
  s.addText("재발견 루프 — “지난번 그 데이터로 이어서”", { x: 0.7, y: 4.1, w: 5.9, h: 0.3, fontFace: T.KR, fontSize: 12, bold: true, color: T.INK, margin: 0 });
  const loop = [
    ["저장", "save_artifact / exec_code → manifest에 자동 기록"],
    ["노출", "매 턴 프롬프트에 “Session Artifacts” 목록 주입 — 히스토리가 잘려도 존재를 안다"],
    ["재사용", "list_artifacts → load_artifact(변수 복원) → 후속 분석"],
  ];
  loop.forEach((l, i) => {
    const y = 4.5 + i * 0.72;
    numDot(pres, s, 0.7, y, 0.36, i + 1, { size: 10 });
    s.addText(l[0], { x: 1.2, y, w: 0.95, h: 0.36, fontFace: T.KR, fontSize: 11, bold: true, color: T.INK, valign: "middle", margin: 0 });
    s.addText(l[1], { x: 2.2, y: y - 0.05, w: 4.45, h: 0.5, fontFace: T.KR, fontSize: 9.5, color: T.MUT, valign: "middle", margin: 0, lineSpacingMultiple: 1.1 });
  });
  // 우: 차트
  s.addText("차트 파이프라인 — 데이터와 선언의 분리", { x: 7.0, y: 1.78, w: 5.65, h: 0.3, fontFace: T.KR, fontSize: 12, bold: true, color: T.INK, margin: 0 });
  codeBlock(pres, s, 7.0, 2.18, 5.65, 2.3, [
    { t: "생성 (에이전트)", c: T.CODE_MUT },
    { t: "① parquet 저장 → ② spec 저장(mark×encoding)" },
    { t: "③ display_chart → ④ ECharts option 렌더" },
    { t: "" },
    { t: "상호작용 (사용자)", c: T.CODE_MUT },
    { t: "⑤ brush·레전드 편집 → ⑥ /api/chart/filter" },
    { t: "⑦ undo/redo 스택 push → ⑧ 재렌더·동시 반영", c: T.CODE_ACC },
  ], { size: 9.5, lh: 1.3 });
  lines(s, 7.0, 4.68, 5.65, 1.9, [
    { t: "“이미지 생성”이 아니라 데이터(parquet)+선언(spec) 분리 — 그래서 사후 필터·레전드 편집이 가능", bullet: { code: "2022", color: T.ACC }, s: 10, c: T.MUT, gap: 6 },
    { t: "필터는 사이드카 파일에 단일 undo/redo 스택으로 영속 — 재진입 후에도 복원·되감기", bullet: { code: "2022", color: T.ACC }, s: 10, c: T.MUT, gap: 6 },
    { t: "원본 parquet은 불변 — 필터는 행 제외 목록일 뿐, Reset으로 언제든 원복", bullet: { code: "2022", color: T.ACC }, s: 10, c: T.MUT },
  ]);
}

function s_safety(pres) {
  const s = lightSlide(pres);
  header(s, "PART 3 · BACKEND", "안전장치 모음", { sub: "실 LLM의 비결정성·실패에 대비한 방어선 (상세: .claude/rules/harness_resilience.md)" });
  table(pres, s, 0.7, 1.95, 11.95, ["분류", "장치", "효과"], [
    [{ t: "입력 경계", b: true }, "Origin 가드 + 루프백 고정 · 동시 턴 가드", "외부 접근 불가 · 같은 세션 중복 요청의 히스토리 오염 방지"],
    [{ t: "LLM 오류", b: true }, "슬롯 가드 책임자 분기 · 깨진 tool_call JSON 마커", "사용자 질문 최소화, LLM 실수는 자가수정 · 스트림 잘림 복구"],
    [{ t: "폭주 방지", b: true }, "반복 상한 8 · 턴 예산 20 · loop-guard · 도구 timeout 30s", "무한 루프·비용 폭주·턴 정지 차단"],
    [{ t: "네트워크", b: true }, "provider 재시도 (지수 백오프)", "일시 오류(429·연결 끊김) 자동 복구"],
    [{ t: "정합성", b: true }, "tool 쌍 보존 트리밍 · 실패 턴 영속 + DoneEvent 보장", "와이어 규약 위반(400) 방지 · 예외에도 턴이 증발하지 않음"],
    [{ t: "코드 실행", b: true }, "evaluator 가드 — exec/eval/os/subprocess 차단", "LLM 폭주 방지 (허용: 안전 stdlib + ALLOWED_LIBRARIES)"],
    [{ t: "비밀 보호", b: true }, "에러 메시지 안전화 · API 키 마스킹", "키·URL이 화면·로그에 노출되지 않음"],
  ], { size: 10.5, colW: [1.5, 5.05, 5.4], rowH: 0.52 });
  s.addText("Mock 시나리오는 happy path만 검증 — 이 방어선들이 실 LLM 투입 시의 신뢰성을 담보한다", {
    x: 0.7, y: 6.15, w: 11.9, h: 0.3, fontFace: T.KR, fontSize: 10.5, italic: true, color: T.ACC_DK, margin: 0,
  });
}

module.exports = { s_duties, s_boot, s_api, s_modules, s_runturn, s_sse, s_routing, s_registry, s_tools, s_pipeline, s_safety };
