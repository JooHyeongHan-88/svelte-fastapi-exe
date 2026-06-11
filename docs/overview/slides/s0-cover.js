// 표지 · 목차 · 파트 구분 · 클로징
const { T, lightSlide, darkSlide, card, chip, starMark, lines } = require("./theme");

function cover(pres) {
  const s = darkSlide(pres);
  starMark(pres, s, 0.72, 0.78, 0.5, T.ACC);
  s.addText("PROJECT INTRODUCTION", {
    x: 0.72, y: 1.62, w: 8, h: 0.32, fontFace: T.SER, fontSize: 13, italic: true,
    color: T.ACC, charSpacing: 3, margin: 0,
  });
  s.addText([
    { text: "단일 EXE로 배포하는", options: { breakLine: true } },
    { text: "로컬 AI Agent 플랫폼", options: {} },
  ], {
    x: 0.7, y: 2.0, w: 11.6, h: 2.0, fontFace: T.KR, fontSize: 40, bold: true,
    color: T.DK_TX, margin: 0, lineSpacingMultiple: 1.12,
  });
  s.addText("Svelte SPA + FastAPI + LLM Agent 하니스를 PyInstaller 단일 실행 파일로 패키징하고,\nNexus로 배포·자동 업데이트하는 사내 AI Agent 채팅 앱", {
    x: 0.72, y: 4.18, w: 10.8, h: 0.75, fontFace: T.KR, fontSize: 13.5,
    color: T.DK_MUT, margin: 0, lineSpacingMultiple: 1.3,
  });
  const parts = ["①  프로젝트 전체 흐름", "②  구현된 UX / UI", "③  Backend 동작 흐름"];
  parts.forEach((p, i) => {
    chip(pres, s, 0.72 + i * 3.05, 5.55, 2.85, 0.46, p, {
      fill: "353331", color: T.DK_TX, size: 11.5,
    });
  });
  s.addText("docs/overview — 2026.06", {
    x: 0.72, y: 6.45, w: 6, h: 0.3, fontFace: T.MONO, fontSize: 10,
    color: T.DK_MUT, margin: 0,
  });
}

function agenda(pres) {
  const s = lightSlide(pres);
  s.addText("이 자료의 구성", {
    x: 0.7, y: 0.55, w: 11.9, h: 0.6, fontFace: T.KR, fontSize: 25, bold: true,
    color: T.INK, margin: 0,
  });
  s.addText("처음 보는 사람 기준으로, 큰 그림에서 내부 구현 순서로 내려간다", {
    x: 0.7, y: 1.18, w: 11.9, h: 0.3, fontFace: T.KR, fontSize: 12, color: T.MUT, margin: 0,
  });
  const cards = [
    {
      n: "1", t: "프로젝트 전체 흐름",
      q: "무엇을 만들고, 어떻게 빌드·배포되는가?",
      k: ["개발 → 빌드 → 배포 → 실행 → 업데이트", "아키텍처 · 디렉터리 구조", "환경 변수 · PROMPTS/SKILLS/AGENTS"],
    },
    {
      n: "2", t: "구현된 UX / UI",
      q: "최종 사용자는 어떤 화면에서 무엇을 쓰는가?",
      k: ["화면 레이아웃 · 세션 · 입력", "진행 가시화 · 에이전트 타임라인", "아티팩트 패널 · 차트 인터랙션 · 설정"],
    },
    {
      n: "3", t: "Backend 동작 흐름",
      q: "백엔드는 내부적으로 어떻게 움직이는가?",
      k: ["기동 · 생명주기 · API 지도", "채팅 한 턴(run_turn) · 서브 에이전트", "Registry · 내장 도구 · 산출물 파이프라인"],
    },
  ];
  cards.forEach((c, i) => {
    const x = 0.7 + i * 4.12, y = 1.85, w = 3.85, h = 4.55;
    card(pres, s, x, y, w, h);
    s.addText(c.n, {
      x: x + 0.28, y: y + 0.22, w: 1.2, h: 0.9, fontFace: T.SER, fontSize: 44, bold: true,
      color: T.ACC, margin: 0,
    });
    s.addText(c.t, {
      x: x + 0.28, y: y + 1.25, w: w - 0.56, h: 0.4, fontFace: T.KR, fontSize: 16.5, bold: true,
      color: T.INK, margin: 0,
    });
    s.addText(c.q, {
      x: x + 0.28, y: y + 1.72, w: w - 0.56, h: 0.65, fontFace: T.KR, fontSize: 11,
      color: T.ACC_DK, italic: true, margin: 0, lineSpacingMultiple: 1.2,
    });
    lines(s, x + 0.28, y + 2.5, w - 0.5, h - 2.7,
      c.k.map((t) => ({ t, bullet: { code: "2022", color: T.ACC }, s: 10.5, c: T.MUT, gap: 7 })));
  });
}

// 파트 구분 슬라이드
function divider(pres, n, title, sub, chips) {
  const s = darkSlide(pres);
  starMark(pres, s, 11.95, 0.7, 0.42, T.ACC);
  s.addText(`PART ${n}`, {
    x: 0.75, y: 1.7, w: 5, h: 0.4, fontFace: T.SER, fontSize: 15, italic: true,
    color: T.ACC, charSpacing: 3, margin: 0,
  });
  s.addText(String(n), {
    x: 9.0, y: 1.9, w: 3.5, h: 3.6, fontFace: T.SER, fontSize: 230, bold: true,
    color: "31302D", align: "right", margin: 0,
  });
  s.addText(title, {
    x: 0.72, y: 2.15, w: 9.5, h: 1.0, fontFace: T.KR, fontSize: 38, bold: true,
    color: T.DK_TX, margin: 0,
  });
  s.addText(sub, {
    x: 0.74, y: 3.3, w: 9.0, h: 0.4, fontFace: T.KR, fontSize: 14, color: T.DK_MUT, margin: 0,
  });
  let cx = 0.74;
  chips.forEach((c) => {
    const w = 0.42 + c.length * 0.155;
    chip(pres, s, cx, 4.4, w, 0.42, c, { fill: "353331", color: T.DK_MUT, size: 10.5, bold: false });
    cx += w + 0.18;
  });
}

function closing(pres) {
  const s = darkSlide(pres);
  starMark(pres, s, 0.72, 0.72, 0.42, T.ACC);
  s.addText("정리 — 한 장으로 보는 전체", {
    x: 0.72, y: 1.35, w: 11, h: 0.65, fontFace: T.KR, fontSize: 28, bold: true,
    color: T.DK_TX, margin: 0,
  });
  const rows = [
    ["만드는 것", "로컬 단일 EXE로 배포되는 사내 AI Agent 채팅 앱"],
    ["화면", "Svelte 5 SPA — localStorage 세션, SSE 실시간 스트리밍"],
    ["서버", "FastAPI — 정적 서빙 + API + presence 생명주기 + 자동 업데이트"],
    ["에이전트", "하니스 루프 — LLM provider와 등록된 도구의 plan 기반 반복 실행"],
    ["확장", "PROMPTS / SKILLS / AGENTS 마크다운 + @register_tool + .env 한 줄"],
    ["빌드·배포", "release.ps1 → PyInstaller EXE + latest.json → Nexus → 자가 교체 업데이트"],
  ];
  rows.forEach((r, i) => {
    const y = 2.35 + i * 0.62;
    s.addText(r[0], {
      x: 0.74, y, w: 1.95, h: 0.45, fontFace: T.KR, fontSize: 13, bold: true,
      color: T.ACC, margin: 0, valign: "middle",
    });
    s.addText(r[1], {
      x: 2.85, y, w: 9.7, h: 0.45, fontFace: T.KR, fontSize: 12.5,
      color: T.DK_TX, margin: 0, valign: "middle",
    });
  });
  s.addText([
    { text: "더 깊이 보려면  ", options: { color: T.DK_MUT, fontSize: 11 } },
    { text: "docs/overview/*.md", options: { color: T.CODE_ACC, fontFace: T.MONO, fontSize: 11, bold: true } },
    { text: "  — 이 슬라이드의 원고 (섹션 단위 1:1 대응)", options: { color: T.DK_MUT, fontSize: 11 } },
  ], { x: 0.74, y: 6.35, w: 11.5, h: 0.35, fontFace: T.KR, margin: 0 });
}

module.exports = { cover, agenda, divider, closing };
