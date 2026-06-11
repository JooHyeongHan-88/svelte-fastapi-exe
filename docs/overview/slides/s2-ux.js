// Part 2 — 구현된 UX/UI (9장)
const { T, lightSlide, header, card, chip, numDot, codeBlock, table, lines } = require("./theme");

function s_layout(pres) {
  const s = lightSlide(pres);
  header(s, "PART 2 · UX/UI", "화면 전체 레이아웃 — 3단 구성");
  // 목업: Sidebar / Chat / Artifact
  const X = 0.7, Y = 1.75, H = 4.0;
  // Sidebar
  card(pres, s, X, Y, 2.1, H, { fill: T.WHITE });
  s.addText("Sidebar", { x: X + 0.15, y: Y + 0.12, w: 1.8, h: 0.28, fontFace: T.KR, fontSize: 11, bold: true, color: T.ACC_DK, margin: 0 });
  chip(pres, s, X + 0.15, Y + 0.48, 1.8, 0.34, "+ 새 대화", { size: 9.5 });
  lines(s, X + 0.15, Y + 0.98, 1.8, 2.0, [
    { t: "오늘", s: 8.5, c: T.FAINT, gap: 3 },
    { t: "데이터 요약 분석", s: 9.5, gap: 3 },
    { t: "어제", s: 8.5, c: T.FAINT, gap: 3 },
    { t: "주간 보고서", s: 9.5, gap: 3 },
    { t: "시간 인사", s: 9.5 },
  ]);
  card(pres, s, X + 0.15, Y + H - 0.85, 1.8, 0.66, { fill: T.BG2, noLine: true });
  s.addText("ModelPicker\ndtgpt / gpt-4o", { x: X + 0.27, y: Y + H - 0.8, w: 1.6, h: 0.56, fontFace: T.KR, fontSize: 8.5, color: T.MUT, margin: 0 });
  // Chat
  card(pres, s, X + 2.3, Y, 5.7, H, { fill: T.WHITE });
  s.addText("TopBar — 현재 세션 제목", { x: X + 2.5, y: Y + 0.12, w: 5.2, h: 0.28, fontFace: T.KR, fontSize: 10, bold: true, color: T.ACC_DK, margin: 0 });
  s.addShape(pres.shapes.LINE, { x: X + 2.3, y: Y + 0.46, w: 5.7, h: 0, line: { color: T.LINE, width: 1 } });
  card(pres, s, X + 4.4, Y + 0.62, 3.4, 0.5, { fill: T.BG2, noLine: true, r: 0.12 });
  s.addText("user — 데이터 요약해줘", { x: X + 4.6, y: Y + 0.62, w: 3.1, h: 0.5, fontFace: T.KR, fontSize: 9.5, color: T.INK, valign: "middle", margin: 0 });
  card(pres, s, X + 2.5, Y + 1.28, 4.4, 1.85, { fill: T.BG, line: T.LINE, r: 0.12 });
  lines(s, X + 2.68, Y + 1.42, 4.1, 1.6, [
    { t: "assistant", s: 8.5, c: T.FAINT, gap: 3 },
    { t: "[스킬 뱃지]  [작업 타임라인]", s: 9, c: T.ACC_DK, b: true, gap: 3 },
    { t: "[TodoProgress 체크리스트]", s: 9, c: T.ACC_DK, b: true, gap: 3 },
    { t: "본문 (마크다운 렌더링)…", s: 9.5, gap: 3 },
    { t: "🔗 칩: 차트 6개 · 데이터", s: 9, c: T.MUT },
  ]);
  card(pres, s, X + 2.5, Y + H - 0.72, 5.3, 0.52, { fill: T.WHITE, line: T.ACC, lineW: 1.2, r: 0.12 });
  s.addText("Composer — Enter 전송 · Shift+Enter 줄바꿈 · / 스킬", { x: X + 2.7, y: Y + H - 0.72, w: 5.0, h: 0.52, fontFace: T.KR, fontSize: 9.5, color: T.MUT, valign: "middle", margin: 0 });
  // Artifact
  card(pres, s, X + 8.2, Y, 3.0, H, { fill: T.WHITE });
  s.addText("Artifact Panel", { x: X + 8.35, y: Y + 0.12, w: 2.7, h: 0.28, fontFace: T.KR, fontSize: 11, bold: true, color: T.ACC_DK, margin: 0 });
  ["이미지", "차트", "문서", "데이터"].forEach((c, i) => {
    chip(pres, s, X + 8.35 + (i % 2) * 1.4, Y + 0.5 + Math.floor(i / 2) * 0.44, 1.25, 0.34, c, { size: 9 });
  });
  card(pres, s, X + 8.35, Y + 1.5, 2.7, 2.25, { fill: T.BG2, noLine: true });
  s.addText("활성 칩 콘텐츠\n(갤러리 · ECharts 그리드\n· 마크다운 · 테이블)", {
    x: X + 8.45, y: Y + 1.6, w: 2.5, h: 2.0, fontFace: T.KR, fontSize: 9.5, color: T.MUT, align: "center", valign: "middle", margin: 0, lineSpacingMultiple: 1.3,
  });
  s.addText("⟷ 드래그 리사이즈", { x: X + 8.0, y: Y + H + 0.06, w: 3.2, h: 0.26, fontFace: T.KR, fontSize: 9, color: T.FAINT, align: "right", margin: 0 });
  // 하단 요약
  card(pres, s, 0.7, 6.1, 11.95, 0.78, { fill: T.BG2, noLine: true });
  s.addText([
    { text: "산출물은 채팅에 섞이지 않는다  ", options: { bold: true, color: T.ACC_DK, fontSize: 11.5 } },
    { text: "— 이미지·차트·보고서·데이터는 우측 패널에 표시되고, 말풍선에는 칩만 남아 언제든 다시 열 수 있다 (세션 복귀 후에도 보존)", options: { color: T.INK, fontSize: 11 } },
  ], { x: 1.0, y: 6.1, w: 11.4, h: 0.78, fontFace: T.KR, valign: "middle", margin: 0 });
}

function s_session(pres) {
  const s = lightSlide(pres);
  header(s, "PART 2 · UX/UI", "세션 관리 & 입력");
  // 좌: 세션
  card(pres, s, 0.7, 1.7, 5.85, 4.65, { fill: T.WHITE });
  s.addText("세션(대화) 관리 — Sidebar", { x: 0.98, y: 1.88, w: 5.3, h: 0.34, fontFace: T.KR, fontSize: 14, bold: true, color: T.INK, margin: 0 });
  table(pres, s, 0.98, 2.35, 5.3, ["기능", "사용 방법"], [
    ["새 대화 / 전환", "버튼 · 행 클릭 (LLM 컨텍스트도 함께 복원)"],
    ["이름 변경", "행 더블클릭 → 인라인 편집"],
    ["삭제", "hover 시 버튼 — 백엔드 히스토리도 삭제"],
    ["자동 제목", "첫 메시지 기반 생성 (수동 변경 시 보존)"],
    ["시간 그룹핑", "오늘 / 어제 / 이번 주 버킷 정렬"],
  ], { size: 10, colW: [1.7, 3.6], rowH: 0.42 });
  card(pres, s, 0.98, 5.15, 5.3, 1.0, { fill: T.ACC_SOFT, noLine: true });
  s.addText([
    { text: "영속 + 안전장치  ", options: { bold: true, color: T.ACC_DK, breakLine: true, paraSpaceAfter: 3 } },
    { text: "모든 세션은 localStorage 저장 — 앱을 껐다 켜도 유지. 응답 생성 중엔 전환·삭제·새 대화 차단 (교차 저장 사고 방지)", options: { color: T.INK } },
  ], { x: 1.2, y: 5.27, w: 4.9, h: 0.8, fontFace: T.KR, fontSize: 10, margin: 0, lineSpacingMultiple: 1.2 });
  // 우: Composer
  card(pres, s, 6.8, 1.7, 5.85, 4.65, { fill: T.WHITE });
  s.addText("메시지 입력 — Composer", { x: 7.08, y: 1.88, w: 5.3, h: 0.34, fontFace: T.KR, fontSize: 14, bold: true, color: T.INK, margin: 0 });
  table(pres, s, 7.08, 2.35, 5.3, ["기능", "동작"], [
    ["전송 / 줄바꿈", "Enter / Shift + Enter (입력창 자동 확장)"],
    ["생성 중단", "정지 버튼 · ESC — 받은 데까지 “중단됨”으로 저장"],
    ["슬래시 커맨드", "/ 입력 → SKILL 자동완성 → 그 턴에 강제 활성화"],
    ["메시지 되감기", "과거 user 메시지 시점으로 잘라내고 재작성"],
  ], { size: 10, colW: [1.7, 3.6], rowH: 0.42 });
  codeBlock(pres, s, 7.08, 4.6, 5.3, 0.62, [
    { t: "/data_summary  ", c: T.CODE_ACC, b: true, s: 10.5 },
    { t: "→ “데이터 요약” 스킬이 무조건 적용된 상태로 전송", c: T.CODE_MUT, s: 9 },
  ], { size: 10, valign: "middle", padY: 0.1 });
  s.addText([
    { text: "응답 표시  ", options: { bold: true, color: T.ACC_DK, fontSize: 10.5 } },
    { text: "user는 plain text, assistant는 마크다운(marked + DOMPurify XSS 방어 + 코드 하이라이트). SSE로 토큰 단위 실시간 스트리밍, 완료 후 소요 시간 표시.", options: { color: T.MUT, fontSize: 10.5 } },
  ], { x: 7.08, y: 5.4, w: 5.3, h: 0.85, fontFace: T.KR, margin: 0, lineSpacingMultiple: 1.25 });
}

function s_progress(pres) {
  const s = lightSlide(pres);
  header(s, "PART 2 · UX/UI", "작업 진행의 실시간 가시화", { sub: "단순 채팅과의 차별점 — 에이전트가 지금 무엇을 하는지 항상 보인다" });
  // 좌 목업
  card(pres, s, 0.7, 1.95, 5.5, 4.6, { fill: T.WHITE });
  // TurnStatus
  card(pres, s, 1.0, 2.2, 4.9, 0.55, { fill: T.BG2, noLine: true, r: 0.27 });
  s.addShape(pres.shapes.OVAL, { x: 1.25, y: 2.4, w: 0.16, h: 0.16, fill: { color: T.ACC }, line: { type: "none" } });
  s.addText("도구 실행 중…   12초", { x: 1.55, y: 2.2, w: 4.2, h: 0.55, fontFace: T.KR, fontSize: 11, color: T.INK, valign: "middle", margin: 0 });
  s.addText("TurnStatus — 펄스 점 + 상황별 문구 + 경과 시간", { x: 1.0, y: 2.85, w: 4.9, h: 0.26, fontFace: T.KR, fontSize: 9, color: T.FAINT, margin: 0 });
  // TodoProgress
  card(pres, s, 1.0, 3.3, 4.9, 1.7, { fill: T.BG, line: T.LINE });
  s.addText("작업 진행", { x: 1.22, y: 3.42, w: 3, h: 0.28, fontFace: T.KR, fontSize: 10.5, bold: true, color: T.INK, margin: 0 });
  lines(s, 1.22, 3.76, 4.5, 1.2, [
    { t: "✓  데이터 조회 — 1,234행 조회 완료", s: 10, c: T.OK, gap: 5 },
    { t: "✓  통계 산출 — 평균·분산 계산", s: 10, c: T.OK, gap: 5 },
    { t: "○  차트 생성", s: 10, c: T.MUT },
  ]);
  s.addText("TodoProgress — 단계별 상태 + 한 줄 결과 요약", { x: 1.0, y: 5.08, w: 4.9, h: 0.26, fontFace: T.KR, fontSize: 9, color: T.FAINT, margin: 0 });
  chip(pres, s, 1.0, 5.5, 2.0, 0.4, "⚡ data_summary", { size: 9.5 });
  chip(pres, s, 3.15, 5.5, 1.7, 0.4, "✓ 작업 완료", { fill: "E7EDE4", color: T.OK, size: 9.5 });
  s.addText("SkillBadge / SkillCompleteBadge", { x: 1.0, y: 6.0, w: 4.9, h: 0.26, fontFace: T.KR, fontSize: 9, color: T.FAINT, margin: 0 });
  // 우 설명
  const rows = [
    ["TurnStatus", "생성 중 말풍선 하단 — 도구 실행/에이전트 작업/추론/응답 생성 4가지 문구를 진행 상태에서 자동 선택"],
    ["TodoProgress", "add_todo로 계획 등록 → 체크리스트 실시간 갱신 (완료·실패·건너뜀 + 요약)"],
    ["스킬 뱃지", "턴 시작 즉시 어떤 작업 지침(SKILL)이 적용됐는지 표시"],
    ["완료 표식", "완료 마커 + hover 시 소요 시간 — ESC 중단 메시지에는 미표시"],
  ];
  rows.forEach((r, i) => {
    const y = 2.0 + i * 1.15;
    card(pres, s, 6.5, y, 6.15, 1.0);
    s.addText(r[0], { x: 6.76, y: y + 0.1, w: 5.6, h: 0.28, fontFace: T.KR, fontSize: 11.5, bold: true, color: T.ACC_DK, margin: 0 });
    s.addText(r[1], { x: 6.76, y: y + 0.4, w: 5.65, h: 0.55, fontFace: T.KR, fontSize: 10, color: T.MUT, margin: 0, lineSpacingMultiple: 1.15 });
  });
}

function s_timeline(pres) {
  const s = lightSlide(pres);
  header(s, "PART 2 · UX/UI", "에이전트 활동 타임라인 — 세그먼트");
  // 좌 목업: 트레일
  card(pres, s, 0.7, 1.75, 6.0, 4.85, { fill: T.WHITE });
  card(pres, s, 1.0, 2.0, 5.4, 0.6, { fill: T.BG2, noLine: true });
  s.addText("▸ 추론 — “데이터 범위를 먼저 확인해야…”", { x: 1.2, y: 2.0, w: 5.0, h: 0.6, fontFace: T.KR, fontSize: 10, color: T.MUT, valign: "middle", margin: 0, italic: true });
  card(pres, s, 1.0, 2.75, 5.4, 0.55, { fill: T.BG, line: T.LINE });
  s.addText("🔧 exec_code — 완료", { x: 1.2, y: 2.75, w: 5.0, h: 0.55, fontFace: T.KR, fontSize: 10, color: T.INK, valign: "middle", margin: 0 });
  // subagent trail
  card(pres, s, 1.0, 3.48, 5.4, 1.95, { fill: T.BG, line: T.ACC, lineW: 1.2 });
  s.addText("🔄 orchestrator → analyst_agent", { x: 1.2, y: 3.6, w: 5.0, h: 0.3, fontFace: T.MONO, fontSize: 10, bold: true, color: T.ACC_DK, margin: 0 });
  lines(s, 1.45, 3.98, 4.8, 0.95, [
    { t: "🔧 exec_code 실행 중…", s: 9.5, c: T.MUT, gap: 4 },
    { t: "✓ 통계 산출 완료", s: 9.5, c: T.OK, gap: 4 },
    { t: "✓ 반환 — “분석 완료. 이상치 3건 발견.”", s: 9.5, c: T.INK },
  ]);
  s.addText("서브 에이전트 트레일 — 내부 도구·todo가 실시간으로 채워짐", { x: 1.2, y: 5.13, w: 5.0, h: 0.26, fontFace: T.KR, fontSize: 8.5, color: T.FAINT, margin: 0 });
  card(pres, s, 1.0, 5.6, 5.4, 0.78, { fill: T.BG, line: T.LINE });
  s.addText("🔄 analyst_agent (진행 중)   🔄 writer_agent (진행 중)", {
    x: 1.2, y: 5.6, w: 5.0, h: 0.5, fontFace: T.MONO, fontSize: 9, color: T.ACC_DK, valign: "middle", margin: 0,
  });
  s.addText("병렬 위임 — 트레일 여러 개가 동시에 진행", { x: 1.2, y: 6.08, w: 5.0, h: 0.26, fontFace: T.KR, fontSize: 8.5, color: T.FAINT, margin: 0 });
  // 우 설명
  table(pres, s, 7.0, 1.85, 5.65, ["세그먼트", "표시 내용"], [
    [{ t: "추론", b: true }, "LLM의 중간 판단 설명 — 접이식 블록"],
    [{ t: "도구 실행", b: true }, "도구명 + running → 완료/에러 상태 카드"],
    [{ t: "서브 에이전트", b: true }, "위임 트레일 — 내부 활동 실시간 + 완료 요약"],
  ], { size: 10.5, colW: [1.6, 4.05], rowH: 0.46 });
  card(pres, s, 7.0, 3.75, 5.65, 1.6, { fill: T.BG2, noLine: true });
  s.addText([
    { text: "병렬 위임의 정확한 라우팅  ", options: { bold: true, color: T.ACC_DK, fontSize: 11.5, breakLine: true, paraSpaceAfter: 5 } },
    { text: "call_sub_agents_parallel 시 트레일 여러 개가 인터리브되어 진행 — 같은 이름의 에이전트 2개가 동시에 떠도 dispatch_id 상관키로 각자의 트레일에 정확히 매칭된다.", options: { color: T.INK, fontSize: 10.5 } },
  ], { x: 7.28, y: 3.93, w: 5.1, h: 1.3, fontFace: T.KR, margin: 0, lineSpacingMultiple: 1.25 });
  s.addText("말풍선 안에 본문 텍스트 외에 활동 세그먼트가 시간 순으로 쌓인다 — 응답이 “어떻게 만들어졌는지”가 그대로 기록으로 남는다.", {
    x: 7.0, y: 5.6, w: 5.65, h: 0.8, fontFace: T.KR, fontSize: 10.5, color: T.MUT, margin: 0, lineSpacingMultiple: 1.3,
  });
}

function s_askuser(pres) {
  const s = lightSlide(pres);
  header(s, "PART 2 · UX/UI", "사용자 되묻기 — AskUserCard");
  // 목업
  card(pres, s, 0.7, 1.9, 6.0, 2.1, { fill: T.WHITE, line: T.ACC, lineW: 1.3 });
  s.addText("어느 기간의 보고서를 생성할까요?", {
    x: 1.0, y: 2.15, w: 5.4, h: 0.4, fontFace: T.KR, fontSize: 13.5, bold: true, color: T.INK, margin: 0,
  });
  ["오늘", "이번 주", "이번 달", "직접 입력"].forEach((o, i) => {
    chip(pres, s, 1.0 + i * 1.32, 2.75, 1.18, 0.46, o, { fill: T.BG2, color: T.INK, size: 10.5 });
  });
  s.addText("버튼 클릭 또는 입력창에 직접 입력 — 답변하면 작업이 이어진다", {
    x: 1.0, y: 3.42, w: 5.4, h: 0.3, fontFace: T.KR, fontSize: 9.5, color: T.FAINT, margin: 0,
  });
  // input_type
  s.addText("input_type 3가지", { x: 0.7, y: 4.35, w: 4, h: 0.3, fontFace: T.KR, fontSize: 12.5, bold: true, color: T.INK, margin: 0 });
  table(pres, s, 0.7, 4.75, 6.0, ["값", "화면", "답변 방법"], [
    [{ t: "choice", mono: true }, "선택지 버튼만", "버튼 클릭"],
    [{ t: "text", mono: true }, "질문 텍스트만", "직접 입력"],
    [{ t: "both", mono: true }, "버튼 + 입력 힌트", "둘 다 가능"],
  ], { size: 10.5, colW: [1.3, 2.5, 2.2], rowH: 0.38 });
  // 우: 발동 경로
  s.addText("발동 경로는 2가지 — 사용자에겐 같은 카드로 보인다", {
    x: 7.1, y: 1.9, w: 5.55, h: 0.35, fontFace: T.KR, fontSize: 13, bold: true, color: T.INK, margin: 0,
  });
  const paths = [
    ["LLM의 능동 질문", "ask_user 도구", "요청이 모호할 때 — “데이터 보여줘”처럼 대상·기간을 단정할 수 없으면 도구 호출 전에 먼저 묻는다"],
    ["슬롯 가드 자동 발동", "인자 검증 레이어", "도구 실행에 필수 인자가 빠졌을 때 자동으로 질문 — 답변하면 같은 도구를 자동 재시도"],
  ];
  paths.forEach((p, i) => {
    const y = 2.45 + i * 1.55;
    card(pres, s, 7.1, y, 5.55, 1.35);
    numDot(pres, s, 7.35, y + 0.18, 0.38, i + 1, { size: 11 });
    s.addText(p[0], { x: 7.88, y: y + 0.18, w: 3.4, h: 0.36, fontFace: T.KR, fontSize: 12, bold: true, color: T.INK, valign: "middle", margin: 0 });
    chip(pres, s, 11.0, y + 0.18, 1.45, 0.36, p[1], { size: 8.5, font: T.MONO });
    s.addText(p[2], { x: 7.35, y: y + 0.62, w: 5.05, h: 0.65, fontFace: T.KR, fontSize: 10, color: T.MUT, margin: 0, lineSpacingMultiple: 1.2 });
  });
  card(pres, s, 7.1, 5.65, 5.55, 0.85, { fill: T.BG2, noLine: true });
  s.addText([
    { text: "묻는 동안 턴은 안전하게 중단  ", options: { bold: true, color: T.ACC_DK, fontSize: 10.5 } },
    { text: "— 질문이 상태로 저장되고, 다음 턴에 답변과 함께 작업이 재개된다", options: { color: T.INK, fontSize: 10.5 } },
  ], { x: 7.35, y: 5.65, w: 5.05, h: 0.85, fontFace: T.KR, valign: "middle", margin: 0, lineSpacingMultiple: 1.2 });
}

function s_artifact(pres) {
  const s = lightSlide(pres);
  header(s, "PART 2 · UX/UI", "아티팩트 패널 — 산출물 칩 4종");
  const chips = [
    ["🖼️ 이미지 N장", "ArtifactImage", "세로 갤러리 — 6장씩 lazy load 무한 스크롤, 클릭 시 라이트박스"],
    ["📊 차트 N개", "ArtifactChart", "ECharts 반응형 그리드 — 페이지당 최대 6개 + 페이지네이션"],
    ["📝 문서 제목", "ArtifactMarkdown", "마크다운 보고서 렌더링 — 채팅과 동일한 sanitize 파이프라인"],
    ["데이터 (parquet)", "ArtifactData", "상위 10행 미리보기 테이블 + 행×열·크기 메타 + 전체 CSV 다운로드"],
  ];
  chips.forEach((c, i) => {
    const col = i % 2, row = Math.floor(i / 2);
    const x = 0.7 + col * 6.1, y = 1.75 + row * 1.62, w = 5.85, h = 1.45;
    card(pres, s, x, y, w, h);
    chip(pres, s, x + 0.25, y + 0.2, 1.95, 0.44, c[0], { size: 10.5 });
    s.addText(c[1], { x: x + 2.35, y: y + 0.24, w: 2.6, h: 0.36, fontFace: T.MONO, fontSize: 10, color: T.FAINT, valign: "middle", margin: 0 });
    s.addText(c[2], { x: x + 0.25, y: y + 0.78, w: w - 0.5, h: 0.58, fontFace: T.KR, fontSize: 10.5, color: T.MUT, margin: 0, lineSpacingMultiple: 1.2 });
  });
  // 공통 UX
  s.addText("패널 공통 UX", { x: 0.7, y: 5.15, w: 4, h: 0.32, fontFace: T.KR, fontSize: 13, bold: true, color: T.INK, margin: 0 });
  lines(s, 0.7, 5.55, 7.4, 1.3, [
    { t: "드래그 리사이즈 — 최대 1000px (와이드 테이블 대응), 설정은 localStorage에 기억", bullet: { code: "2022", color: T.ACC }, s: 10.5, c: T.MUT, gap: 6 },
    { t: "display 계열 칩은 생성 즉시 패널 자동 오픈 — 칩 클릭으로 언제든 재오픈", bullet: { code: "2022", color: T.ACC }, s: 10.5, c: T.MUT, gap: 6 },
    { t: "데이터 칩은 자동 오픈하지 않음 — 빈번한 중간 저장마다 패널이 튀는 것 방지", bullet: { code: "2022", color: T.ACC }, s: 10.5, c: T.MUT },
  ]);
  card(pres, s, 8.5, 5.15, 4.15, 1.7, { fill: T.ACC_SOFT, noLine: true });
  s.addText([
    { text: "@ 참조 삽입  ", options: { bold: true, color: T.ACC_DK, fontSize: 11.5, breakLine: true, paraSpaceAfter: 4 } },
    { text: "칩·패널의 @ 버튼 → 산출물 경로가 입력창에 삽입. “이 데이터로 이어서 분석해줘”를 클릭 한 번으로 — 과거 세션 산출물도 이어서 작업 가능", options: { color: T.INK, fontSize: 10 } },
  ], { x: 8.78, y: 5.3, w: 3.6, h: 1.45, fontFace: T.KR, margin: 0, lineSpacingMultiple: 1.22 });
}

function s_chart(pres) {
  const s = lightSlide(pres);
  header(s, "PART 2 · UX/UI", "차트 인터랙션 — 보기를 넘어 데이터 탐색 도구로");
  table(pres, s, 0.7, 1.8, 6.3, ["조작", "방법"], [
    ["확대 보기", "차트 셀 클릭 → 라이트박스 (핸들 드래그로 크기 조절)"],
    ["차트 간 이동", "← / → 방향키"],
    ["영역 선택", "brush 드래그 (scatter·line·ecdf 등 행 단위 차트)"],
    ["행 제외 필터", "Filter (이 차트만) / Filter All (같은 데이터 전체)"],
    ["그룹 제외", "레전드 패널 체크 → 같은 Filter 버튼"],
    ["실행 취소", "Undo / Redo / Reset — 필터·레전드를 하나의 히스토리로"],
  ], { size: 10.5, colW: [1.8, 4.5], rowH: 0.46 });
  // 레전드 패널 목업
  card(pres, s, 7.35, 1.8, 5.3, 2.5, { fill: T.WHITE });
  s.addText("Legend 편집 패널", { x: 7.6, y: 1.95, w: 4.8, h: 0.3, fontFace: T.KR, fontSize: 11.5, bold: true, color: T.ACC_DK, margin: 0 });
  const lg = [["그룹 A", T.ACC], ["그룹 B", "6E8B68"], ["그룹 C", "8B7355"]];
  lg.forEach((g, i) => {
    const y = 2.35 + i * 0.5;
    s.addText("⠿", { x: 7.62, y, w: 0.3, h: 0.36, fontFace: T.KR, fontSize: 11, color: T.FAINT, valign: "middle", margin: 0 });
    s.addShape(pres.shapes.OVAL, { x: 7.98, y: y + 0.09, w: 0.18, h: 0.18, fill: { color: g[1] }, line: { type: "none" } });
    s.addText(g[0], { x: 8.28, y, w: 2.2, h: 0.36, fontFace: T.KR, fontSize: 10.5, color: T.INK, valign: "middle", margin: 0 });
    s.addText(i === 2 ? "숨김" : "표시", { x: 10.9, y, w: 0.75, h: 0.36, fontFace: T.KR, fontSize: 9, color: i === 2 ? T.FAINT : T.OK, valign: "middle", margin: 0 });
    s.addText(i === 1 ? "☑" : "☐", { x: 11.85, y, w: 0.4, h: 0.36, fontFace: T.KR, fontSize: 11, color: i === 1 ? T.ACC_DK : T.FAINT, valign: "middle", margin: 0 });
  });
  s.addText("드래그 순서 변경 · 색상 클릭 변경 · 표시/숨김 · Filter 선택", {
    x: 7.6, y: 3.9, w: 4.8, h: 0.28, fontFace: T.KR, fontSize: 9, color: T.FAINT, margin: 0,
  });
  // 동기화 노트
  card(pres, s, 7.35, 4.55, 5.3, 2.1, { fill: T.BG2, noLine: true });
  s.addText([
    { text: "핵심 설계  ", options: { bold: true, color: T.ACC_DK, fontSize: 11.5, breakLine: true, paraSpaceAfter: 5 } },
    { text: "그리드와 라이트박스가 같은 캐시를 공유 — 어느 쪽에서 편집해도 양쪽 동시 갱신.", options: { color: T.INK, fontSize: 10.5, breakLine: true, paraSpaceAfter: 5 } },
    { text: "필터 상태는 서버 파일로 영속 — 세션을 나갔다 와도 유지되고 Undo로 언제든 복원. 데이터 원본(parquet)은 불변.", options: { color: T.INK, fontSize: 10.5 } },
  ], { x: 7.62, y: 4.73, w: 4.75, h: 1.75, fontFace: T.KR, margin: 0, lineSpacingMultiple: 1.25 });
  s.addText("brush 선택 → Filter → 즉시 재집계·재렌더 — “이상치를 빼고 다시 보자”가 대화 없이 클릭으로 끝난다", {
    x: 0.7, y: 5.05, w: 6.3, h: 0.7, fontFace: T.KR, fontSize: 11, italic: true, color: T.ACC_DK, margin: 0, lineSpacingMultiple: 1.25,
  });
}

function s_settings(pres) {
  const s = lightSlide(pres);
  header(s, "PART 2 · UX/UI", "설정 · 업데이트 · 테마");
  const cards = [
    ["LLM 설정", [
      "SettingsModal — 프로바이더(mock·dtgpt·openai_compatible)·모델·API Key·Base URL + 연결 테스트",
      "ModelPicker — 사이드바 하단 드롭업으로 빠른 모델 전환 (목록 5분 캐시, 5개 초과 시 검색창)",
      "저장 즉시 적용 — 서버 재시작 없이 다음 메시지부터 (provider hot-swap)",
    ]],
    ["보안 처리", [
      "API 키는 백엔드 settings.json에만 저장 — 브라우저에 절대 저장하지 않음",
      "조회 시 항상 마스킹 (sk-p••••4f2a) — 입력 필드는 placeholder로만 흔적 표시",
      "프로바이더 전환 시에도 이전 프로바이더 설정은 슬롯에 보존",
    ]],
    ["업데이트 UX & 테마", [
      "새 버전 감지 → 상단 배너 → 클릭 한 번 → 진행률 모달(다운로드·검증) → 자동 교체·재기동",
      "실패 시 자동 롤백 — 기존 버전이 다시 뜬다",
      "라이트/다크 테마 토글 (CSS 변수 토큰 — 전 컴포넌트 즉시 반영) · 모바일 사이드바 접힘",
    ]],
  ];
  cards.forEach((c, i) => {
    const y = 1.75 + i * 1.68;
    card(pres, s, 0.7, y, 11.95, 1.5);
    s.addText(c[0], { x: 1.0, y: y + 0.14, w: 2.6, h: 0.34, fontFace: T.KR, fontSize: 13, bold: true, color: T.ACC_DK, margin: 0 });
    lines(s, 3.6, y + 0.16, 8.8, 1.25,
      c[1].map((t) => ({ t, bullet: { code: "2022", color: T.ACC }, s: 10, c: T.MUT, gap: 4.5 })));
  });
}

function s_mock(pres) {
  const s = lightSlide(pres);
  header(s, "PART 2 · UX/UI", "직접 체험 — Mock 시나리오 (데모 대본)", { sub: "실제 LLM 없이(provider: mock) 아래 입력만으로 위 UI 기능 전부를 시연할 수 있다" });
  table(pres, s, 0.7, 1.95, 11.95, ["입력 예시", "시나리오", "체험하는 UI"], [
    [{ t: "(아무 문장)", mono: true }, "A. echo", "기본 스트리밍, TurnStatus"],
    [{ t: "추천해줘 · 골라줘", mono: true }, "B. ask_user", "ReasoningBlock, AskUserCard"],
    [{ t: "지금 시간", mono: true }, "C. time_check", "스킬 뱃지, 마크다운 산출물"],
    [{ t: "데이터 요약", mono: true }, "D. data_summary", "서브 에이전트 트레일, TodoProgress, 차트 6개 + 레전드 편집"],
    [{ t: "전체 분석 보고서", mono: true }, "E. composite", "2단 위임, 차트 7개 + 이미지 갤러리"],
    [{ t: "병렬 분석", mono: true }, "F. parallel", "트레일 2개 동시 진행 (병렬 위임)"],
    [{ t: "이전 결과  (D 이후)", mono: true }, "G. artifact 재사용", "과거 산출물 재발견 → 이어서 분석"],
  ], { size: 11, colW: [3.1, 2.5, 6.35], rowH: 0.52 });
  s.addText("시나리오 상세 흐름: docs/mock-scenarios.md — 데모·스크린샷 촬영 시 이 표를 그대로 따라 하면 된다", {
    x: 0.7, y: 6.15, w: 11.9, h: 0.3, fontFace: T.KR, fontSize: 10, color: T.FAINT, margin: 0,
  });
}

module.exports = { s_layout, s_session, s_progress, s_timeline, s_askuser, s_artifact, s_chart, s_settings, s_mock };
