// Part 1 — 프로젝트 전체 흐름 (12장)
const { T, lightSlide, header, card, chip, numDot, codeBlock, table, arrow, lines } = require("./theme");

function s_define(pres) {
  const s = lightSlide(pres);
  header(s, "PART 1 · 전체 흐름", "한 문장 정의");
  card(pres, s, 0.7, 1.6, 11.95, 1.18, { fill: T.WHITE });
  s.addText([
    { text: "“웹 기술로 만든 AI Agent 채팅 앱을, ", options: {} },
    { text: "별도 서버·설치 과정 없이 단일 .exe 하나로", options: { bold: true, color: T.ACC_DK } },
    { text: " 사내 PC에 배포한다”", options: {} },
  ], {
    x: 1.0, y: 1.6, w: 11.3, h: 1.18, fontFace: T.KR, fontSize: 17.5, color: T.INK,
    valign: "middle", margin: 0,
  });
  const rows = [
    ["Svelte SPA", "사용자가 보는 채팅 UI — 정적 빌드 산출물"],
    ["FastAPI", "정적 파일 서빙 + REST/SSE API + LLM 에이전트 하니스"],
    ["PyInstaller", "위 둘 + 에이전트 정의 파일을 묶어 단일 EXE로 패키징"],
    ["Nexus", "사내 저장소 — EXE와 버전 메타데이터(latest.json) 배포"],
    ["Updater.exe", "실행 중인 앱을 새 버전으로 자가 교체 (자동 업데이트)"],
  ];
  rows.forEach((r, i) => {
    const y = 3.05 + i * 0.6;
    chip(pres, s, 0.7, y, 2.1, 0.42, r[0], { font: T.MONO, size: 11 });
    s.addText(r[1], {
      x: 3.05, y, w: 9.6, h: 0.42, fontFace: T.KR, fontSize: 12.5, color: T.INK,
      valign: "middle", margin: 0,
    });
  });
  card(pres, s, 0.7, 6.25, 11.95, 0.62, { fill: T.ACC_SOFT, noLine: true });
  s.addText([
    { text: "핵심 컨셉   ", options: { bold: true, color: T.ACC_DK, fontSize: 12.5 } },
    { text: "브라우저가 화면이고, EXE가 서버다 — 더블클릭하면 로컬 백엔드가 켜지고 브라우저에 채팅 화면이 열린다", options: { color: T.INK, fontSize: 12.5 } },
  ], { x: 1.0, y: 6.25, w: 11.4, h: 0.62, fontFace: T.KR, valign: "middle", margin: 0 });
}

function s_goals(pres) {
  const s = lightSlide(pres);
  header(s, "PART 1 · 전체 흐름", "왜 이런 구조인가 — 5가지 설계 목표");
  const goals = [
    ["설치 과정 없는 배포", "파일 복사만으로 실행", "PyInstaller onefile 단일 EXE — Python 런타임·웹 자산 전부 내장"],
    ["보안 경계", "외부 네트워크 노출 차단", "127.0.0.1 루프백 고정 바인딩 + Origin 가드 (env로도 변경 불가)"],
    ["포트 충돌 없음", "사용자 PC 환경 무가정", "기동 시 OS가 빈 포트 동적 할당, 프론트는 상대 경로만 사용"],
    ["수동 재배포 제거", "버전 업그레이드 자동화", "내장 업데이트 체크 + sha256 검증 + Updater.exe 자가 교체"],
    ["코드 수정 없는 확장", "도메인 로직과 앱 분리", "PROMPTS / SKILLS / AGENTS 마크다운 + .env 한 줄로 동작 정의"],
  ];
  goals.forEach((g, i) => {
    const col = i % 3, row = Math.floor(i / 3);
    const x = 0.7 + col * 4.12, y = 1.7 + row * 2.18, w = 3.85, h = 2.0;
    card(pres, s, x, y, w, h);
    numDot(pres, s, x + 0.25, y + 0.24, 0.4, i + 1);
    s.addText(g[0], {
      x: x + 0.8, y: y + 0.22, w: w - 1.0, h: 0.44, fontFace: T.KR, fontSize: 13.5,
      bold: true, color: T.INK, valign: "middle", margin: 0,
    });
    s.addText(g[1], {
      x: x + 0.25, y: y + 0.78, w: w - 0.5, h: 0.3, fontFace: T.KR, fontSize: 10,
      color: T.ACC_DK, bold: true, margin: 0,
    });
    s.addText(g[2], {
      x: x + 0.25, y: y + 1.1, w: w - 0.5, h: 0.8, fontFace: T.KR, fontSize: 10.5,
      color: T.MUT, margin: 0, lineSpacingMultiple: 1.2,
    });
  });
  card(pres, s, 4.82, 3.88, 7.83, 2.0, { fill: T.BG2, noLine: true });
  s.addText([
    { text: "이 에이전트의 정체성", options: { bold: true, color: T.ACC_DK, fontSize: 12, breakLine: true, paraSpaceAfter: 6 } },
    { text: "“미리 등록된 Python API 도구를 계획(plan)에 따라 실행하는 플랫폼”", options: { bold: true, fontSize: 13, color: T.INK, breakLine: true, paraSpaceAfter: 6 } },
    { text: "코드를 작성·편집하는 AI 코딩 어시스턴트가 아니라, 사내 도메인 작업(데이터 조회·분석·보고)을 대화로 수행하는 업무 에이전트를 지향한다.", options: { fontSize: 11, color: T.MUT } },
  ], { x: 5.12, y: 4.12, w: 7.25, h: 1.6, fontFace: T.KR, margin: 0, lineSpacingMultiple: 1.25 });
}

function s_bigpicture(pres) {
  const s = lightSlide(pres);
  header(s, "PART 1 · 전체 흐름", "큰 그림 — 개발부터 사용자까지 5단계");
  const steps = [
    ["개발", ["frontend/ (Svelte)", "backend/ (FastAPI)", "PROMPTS·SKILLS·AGENTS"]],
    ["빌드", ["release.ps1 한 줄", "npm build + PyInstaller", "→ release/MyAgent.exe"]],
    ["배포", ["Nexus 업로드", "EXE + latest.json", "(EXE 먼저, json 마지막)"]],
    ["실행", ["EXE 더블클릭", "FastAPI 동적 포트 기동", "브라우저 자동 오픈"]],
    ["업데이트", ["latest.json 확인", "다운로드 + sha256 검증", "Updater가 자가 교체"]],
  ];
  steps.forEach((st, i) => {
    const x = 0.7 + i * 2.62, y = 1.85, w = 2.28, h = 2.5;
    card(pres, s, x, y, w, h, { line: i === 4 ? T.ACC : T.LINE, lineW: i === 4 ? 1.5 : 1 });
    numDot(pres, s, x + 0.2, y + 0.2, 0.42, i + 1);
    s.addText(st[0], {
      x: x + 0.74, y: y + 0.2, w: w - 0.9, h: 0.42, fontFace: T.KR, fontSize: 14.5,
      bold: true, color: T.INK, valign: "middle", margin: 0,
    });
    lines(s, x + 0.22, y + 0.86, w - 0.42, h - 1.0,
      st[1].map((t) => ({ t, s: 9.5, c: T.MUT, gap: 5 })));
    if (i < 4) arrow(s, x + w + 0.0, y + 1.0, { w: 0.36, size: 16, color: T.ACC });
  });
  // build vs release 구분
  card(pres, s, 0.7, 4.75, 11.95, 1.55, { fill: T.BG2, noLine: true });
  s.addText("산출물 폴더의 역할 구분", {
    x: 1.0, y: 4.95, w: 6, h: 0.3, fontFace: T.KR, fontSize: 12, bold: true, color: T.ACC_DK, margin: 0,
  });
  s.addText([
    { text: "build/", options: { fontFace: T.MONO, bold: true, color: T.INK } },
    { text: "      중간 산출물 — EXE 안에 들어갈 재료 (web/, updater/), 업로드하지 않음", options: { color: T.MUT, breakLine: true, paraSpaceAfter: 5 } },
    { text: "release/", options: { fontFace: T.MONO, bold: true, color: T.INK } },
    { text: "  최종 산출물 — Nexus에 업로드되는 것 ({AppName}.exe, latest.json)", options: { color: T.MUT } },
  ], { x: 1.0, y: 5.32, w: 11.3, h: 0.85, fontFace: T.KR, fontSize: 11.5, margin: 0 });
}

function s_runtime(pres) {
  const s = lightSlide(pres);
  header(s, "PART 1 · 전체 흐름", "실행 시 모습 — 사용자 PC 한 대 안에서");
  // 좌측 다이어그램
  card(pres, s, 0.7, 1.7, 6.1, 4.4, { fill: T.WHITE });
  s.addText("사용자 PC  (외부 네트워크 노출 없음)", {
    x: 0.95, y: 1.86, w: 5.6, h: 0.3, fontFace: T.KR, fontSize: 10.5, bold: true, color: T.MUT, margin: 0,
  });
  card(pres, s, 0.98, 2.25, 5.54, 2.5, { fill: T.BG2, line: T.LINE });
  s.addText("MyAgent.exe  (PyInstaller onefile)", {
    x: 1.2, y: 2.38, w: 5.1, h: 0.28, fontFace: T.MONO, fontSize: 10.5, bold: true, color: T.INK, margin: 0,
  });
  codeBlock(pres, s, 1.2, 2.74, 5.1, 1.82, [
    { t: "FastAPI + uvicorn  127.0.0.1:<동적 포트>", c: T.CODE_ACC, b: true },
    { t: " ├ /            → 내장 web/ (Svelte SPA)" },
    { t: " ├ /api/*       → REST + SSE 스트리밍" },
    { t: " ├ /result/*    → 에이전트 산출물" },
    { t: " └ /workspace/* → 도구 생성 파일" },
  ], { size: 9 });
  s.addText("↑  HTTP (루프백 전용)", {
    x: 1.2, y: 4.86, w: 4, h: 0.3, fontFace: T.KR, fontSize: 10, color: T.ACC_DK, bold: true, margin: 0,
  });
  card(pres, s, 0.98, 5.2, 5.54, 0.6, { fill: T.WHITE, line: T.ACC, lineW: 1.25 });
  s.addText("기본 브라우저  —  EXE가 자동으로 오픈", {
    x: 0.98, y: 5.2, w: 5.54, h: 0.6, fontFace: T.KR, fontSize: 11.5, bold: true,
    color: T.INK, align: "center", valign: "middle", margin: 0,
  });
  // 우측: 생명주기 + 저장 위치
  s.addText("생명주기는 브라우저 탭과 연동", {
    x: 7.15, y: 1.7, w: 5.4, h: 0.32, fontFace: T.KR, fontSize: 13, bold: true, color: T.INK, margin: 0,
  });
  const life = [
    "EXE 기동 → 빈 포트 할당 → 브라우저 자동 오픈",
    "브라우저의 SSE 연결(presence) 유지 = 생존 신호",
    "탭 닫음 → 유예 후 watchdog이 서버 자가 종료",
  ];
  life.forEach((t, i) => {
    numDot(pres, s, 7.15, 2.12 + i * 0.52, 0.36, i + 1, { size: 10.5 });
    s.addText(t, {
      x: 7.65, y: 2.12 + i * 0.52, w: 5.1, h: 0.36, fontFace: T.KR, fontSize: 11,
      color: T.INK, valign: "middle", margin: 0,
    });
  });
  s.addText("→ “더블클릭으로 켜고, 탭 닫으면 꺼지는” 일반 데스크탑 앱처럼 동작", {
    x: 7.15, y: 3.75, w: 5.45, h: 0.32, fontFace: T.KR, fontSize: 10.5, italic: true, color: T.ACC_DK, margin: 0,
  });
  table(pres, s, 7.15, 4.25, 5.45, ["데이터", "저장 위치 (frozen EXE)"], [
    ["대화 세션·메시지", { t: "브라우저 localStorage", mono: true, s: 9 }],
    ["LLM 설정", { t: "%APPDATA%\\{APP_NAME}\\settings.json", mono: true, s: 9 }],
    ["에이전트 산출물", { t: "%APPDATA%\\{APP_NAME}\\result\\", mono: true, s: 9 }],
  ], { size: 10, colW: [1.85, 3.6], rowH: 0.34 });
}

function s_stack(pres) {
  const s = lightSlide(pres);
  header(s, "PART 1 · 전체 흐름", "기술 스택");
  table(pres, s, 0.7, 1.75, 11.95, ["영역", "기술", "비고"], [
    ["Frontend", { t: "Svelte 5 (runes) + Vite", b: true }, "SPA — 빌드 결과는 순수 정적 파일"],
    ["차트", { t: "ECharts", b: true }, "인터랙티브 차트 (brush 필터 · 레전드 편집)"],
    ["Backend", { t: "FastAPI + uvicorn", b: true }, "REST + SSE(Server-Sent Events) 스트리밍"],
    ["LLM 연동", { t: "OpenAI 호환 API (DTGPT) + Mock", b: true }, "provider 추상화 — 재시작 없는 핫스왑"],
    ["데이터", { t: "polars + parquet", b: true }, "에이전트 산출물의 표준 데이터 포맷"],
    ["패키징", { t: "PyInstaller (onefile)", b: true }, "Windows 단일 EXE"],
    ["배포", { t: "Nexus raw repository", b: true }, "저장소 중립적 설계 (APP_REPO_* 변수)"],
    ["패키지 관리", { t: "uv (Python) / npm (JS)", b: true }, ""],
    ["품질", { t: "ruff + pytest", b: true }, "포맷·린트 / asyncio 자동 모드 테스트"],
  ], { size: 11.5, colW: [2.2, 4.55, 5.2], rowH: 0.5, headSize: 11.5 });
}

function s_arch(pres) {
  const s = lightSlide(pres);
  header(s, "PART 1 · 전체 흐름", "아키텍처 — 3개 층의 분리");
  const layers = [
    ["① 화면 층", "frontend/ (Svelte 5)", "대화 UI · 세션 관리 · 아티팩트 패널 — 진실의 원천은 브라우저 localStorage"],
    ["② 서버 층", "backend/ (FastAPI)", "정적 서빙 · presence 생명주기 · 설정 · 업데이트 · 산출물 API"],
    ["③ 에이전트 층", "backend/agent/ (하니스)", "LLM provider ↔ 도구 실행 루프 — 동작 정의는 코드 밖 (PROMPTS·SKILLS·AGENTS)"],
  ];
  const conn = ["REST + SSE  (/api/*)", "run_turn() 호출"];
  layers.forEach((l, i) => {
    const y = 1.75 + i * 1.52;
    card(pres, s, 0.7, y, 7.6, 1.05, { line: i === 2 ? T.ACC : T.LINE, lineW: i === 2 ? 1.5 : 1 });
    s.addText(l[0], {
      x: 1.0, y: y + 0.14, w: 2.4, h: 0.36, fontFace: T.KR, fontSize: 14, bold: true, color: T.INK, margin: 0,
    });
    s.addText(l[1], {
      x: 3.2, y: y + 0.17, w: 4.9, h: 0.3, fontFace: T.MONO, fontSize: 11, color: T.ACC_DK, bold: true, margin: 0,
    });
    s.addText(l[2], {
      x: 1.0, y: y + 0.55, w: 7.0, h: 0.4, fontFace: T.KR, fontSize: 10.5, color: T.MUT, margin: 0,
    });
    if (i < 2) {
      s.addText("│  " + conn[i], {
        x: 1.35, y: y + 1.07, w: 4.5, h: 0.42, fontFace: T.MONO, fontSize: 9.5,
        color: T.ACC_DK, bold: true, valign: "middle", margin: 0,
      });
    }
  });
  // 우측 콜아웃 — 역방향 hydrate
  card(pres, s, 8.6, 1.75, 4.05, 4.6, { fill: T.BG2, noLine: true });
  s.addText("특징적인 데이터 흐름", {
    x: 8.88, y: 1.98, w: 3.5, h: 0.32, fontFace: T.KR, fontSize: 12.5, bold: true, color: T.ACC_DK, margin: 0,
  });
  lines(s, 8.88, 2.42, 3.5, 3.8, [
    { t: "대화 히스토리의 진실의 원천은 프론트(localStorage)다.", b: true, s: 11.5, gap: 8 },
    { t: "앱 시작·세션 전환 시 프론트가 보관한 메시지를 POST /api/conversation/restore 로 백엔드에 주입(hydrate)해 LLM 컨텍스트를 복원한다.", s: 10.5, c: T.MUT, gap: 8 },
    { t: "백엔드는 대화를 영구 저장하지 않는다 — 산출물 파일과 에이전트 상태만 디스크 영속.", s: 10.5, c: T.MUT },
  ], { gap: 8 });
}

function s_dirs(pres) {
  const s = lightSlide(pres);
  header(s, "PART 1 · 전체 흐름", "디렉터리 구조");
  codeBlock(pres, s, 0.7, 1.7, 6.7, 5.25, [
    { t: "svelte-fastapi-exe/", c: T.CODE_MUT },
    { t: "├ frontend/        ", c: T.CODE_ACC, b: true },
    { t: "│   └ src/components·lib   UI 26개 + 상태·액션" },
    { t: "├ backend/         ", c: T.CODE_ACC, b: true },
    { t: "│   ├ main.py               엔트리포인트" },
    { t: "│   ├ core/  api/  agent/   기반·HTTP·하니스" },
    { t: "│   ├ settings/  scripts/   설정·도메인 유틸" },
    { t: "│   └ tests/                pytest" },
    { t: "├ PROMPTS/ SKILLS/ AGENTS/  에이전트 정의(.md)", c: T.CODE_ACC, b: true },
    { t: "├ packaging/       App.spec · release.ps1" },
    { t: "├ updater/         자가 교체 로직 소스" },
    { t: "├ docs/            개발자 가이드" },
    { t: "├ .env             설정의 단일 진실 공급원", c: T.CODE_ACC, b: true },
    { t: "├ build/           (생성) 중간 산출물", c: T.CODE_MUT },
    { t: "├ release/         (생성) 배포 산출물", c: T.CODE_MUT },
    { t: "└ result/ workspace/ (생성) 런타임 산출물", c: T.CODE_MUT },
  ], { size: 10, lh: 1.32 });
  s.addText("확장 포인트는 전부 코드 밖에 있다", {
    x: 7.75, y: 1.85, w: 4.9, h: 0.4, fontFace: T.KR, fontSize: 14.5, bold: true, color: T.INK, margin: 0,
  });
  const pts = [
    ["에이전트 행동 변경", "PROMPTS/ · SKILLS/ · AGENTS/ 마크다운 수정 — dev는 핫리로드"],
    ["새 도구 추가", "backend/agent/tools/ 에 .py 파일 추가 → 부팅 시 자동 등록"],
    ["라이브러리 노출", ".env 의 APP_ALLOWED_LIBRARIES 한 줄 → 런타임·EXE 번들 동시 반영"],
    ["앱 이름 변경", ".env 의 APP_NAME 하나 — spec과 release.ps1이 이 값을 읽음"],
  ];
  pts.forEach((p, i) => {
    const y = 2.5 + i * 1.12;
    card(pres, s, 7.75, y, 4.9, 0.96);
    s.addText(p[0], {
      x: 8.0, y: y + 0.1, w: 4.4, h: 0.3, fontFace: T.KR, fontSize: 11.5, bold: true, color: T.ACC_DK, margin: 0,
    });
    s.addText(p[1], {
      x: 8.0, y: y + 0.42, w: 4.45, h: 0.48, fontFace: T.KR, fontSize: 10, color: T.MUT, margin: 0, lineSpacingMultiple: 1.15,
    });
  });
}

function s_devfrozen(pres) {
  const s = lightSlide(pres);
  header(s, "PART 1 · 전체 흐름", "개발 모드 vs 패키징 모드", { sub: "같은 코드가 두 모드로 동작 — 분기 기준은 sys.frozen (PyInstaller 여부) 하나" });
  table(pres, s, 0.7, 1.85, 11.95, ["", "dev (개발)", "frozen (배포 EXE)"], [
    [{ t: "화면", b: true }, "Vite dev server (localhost:5173, HMR)", "EXE에 내장된 web/ 정적 파일"],
    [{ t: "백엔드 포트", b: true }, ".env의 APP_DEV_PORT 고정 (기본 8765)", "OS가 빈 포트를 동적 할당"],
    [{ t: "API 연결", b: true }, "Vite가 /api 를 백엔드로 프록시", "같은 origin — 프록시 불필요"],
    [{ t: "PROMPTS/SKILLS 수정", b: true }, { t: "핫리로드 (다음 턴부터 반영)", b: true, c: T.ACC_DK }, "빌드 시점 박제 — 재빌드 필요"],
    [{ t: "종료 방식", b: true }, "Ctrl + C", "탭 닫기 → watchdog 자동 종료"],
  ], { size: 11.5, colW: [2.5, 4.7, 4.75], rowH: 0.52, headSize: 11.5 });
  codeBlock(pres, s, 0.7, 5.15, 11.95, 1.45, [
    { t: "# 개발 서버 실행", c: T.CODE_MUT },
    { t: "uv run python backend/main.py", c: T.CODE_TX, b: true },
    { t: "cd frontend; npm run dev          # → http://localhost:5173", c: T.CODE_TX, b: true },
  ], { size: 11, lh: 1.4 });
}

function s_build(pres) {
  const s = lightSlide(pres);
  header(s, "PART 1 · 전체 흐름", "빌드 & 릴리즈 파이프라인", { sub: "pwsh packaging/release.ps1 한 줄이 전체를 수행 — 사전 검사: git clean 확인 + .env 로드" });
  const steps = [
    ["버전 동기화", "pyproject.toml → backend/_version.py"],
    ["Frontend 빌드", "npm run build → build/web/"],
    ["Updater 빌드", "PyInstaller → build/updater/Updater.exe"],
    ["App EXE 빌드", "PyInstaller → release/{AppName}.exe"],
    ["메타데이터 생성", "sha256·크기 계산 → release/latest.json"],
    ["업로드 (선택)", "-Upload 시 Nexus로 — EXE 먼저, json 마지막"],
  ];
  steps.forEach((st, i) => {
    const y = 1.95 + i * 0.74;
    numDot(pres, s, 0.7, y, 0.4, i + 1);
    s.addText(st[0], {
      x: 1.25, y, w: 2.05, h: 0.4, fontFace: T.KR, fontSize: 12, bold: true, color: T.INK, valign: "middle", margin: 0,
    });
    s.addText(st[1], {
      x: 3.35, y, w: 3.9, h: 0.4, fontFace: T.MONO, fontSize: 9.5, color: T.MUT, valign: "middle", margin: 0,
    });
  });
  // 우측: EXE 내장물
  card(pres, s, 7.5, 1.95, 5.15, 3.4, { fill: T.WHITE });
  s.addText("App.spec이 EXE에 내장하는 것", {
    x: 7.78, y: 2.12, w: 4.6, h: 0.3, fontFace: T.KR, fontSize: 12.5, bold: true, color: T.ACC_DK, margin: 0,
  });
  lines(s, 7.78, 2.55, 4.6, 2.7, [
    { t: "build/web/ — 프론트 정적 자산", mono: true, s: 10 },
    { t: "Updater.exe — 자가 교체 헬퍼", mono: true, s: 10 },
    { t: "PROMPTS/ SKILLS/ AGENTS/ — 파일 추가만으로 다음 빌드 반영", mono: true, s: 10 },
    { t: ".env — 빌드 시점 설정 박제", mono: true, s: 10 },
    { t: "backend/scripts/ — 서브모듈 자동 수집", mono: true, s: 10 },
    { t: "APP_ALLOWED_LIBRARIES의 각 패키지 — env 한 줄 = 번들 자동 포함", mono: true, s: 10 },
  ], { gap: 7 });
  card(pres, s, 7.5, 5.5, 5.15, 1.1, { fill: T.ACC_SOFT, noLine: true });
  s.addText([
    { text: "업로드 순서가 중요한 이유  ", options: { bold: true, color: T.ACC_DK, breakLine: true, paraSpaceAfter: 3 } },
    { text: "latest.json이 먼저 올라가면 클라이언트가 아직 없는 EXE(404)를 받으려 시도할 수 있다", options: { color: T.INK } },
  ], { x: 7.78, y: 5.62, w: 4.6, h: 0.9, fontFace: T.KR, fontSize: 10.5, margin: 0, lineSpacingMultiple: 1.2 });
}

function s_update(pres) {
  const s = lightSlide(pres);
  header(s, "PART 1 · 전체 흐름", "자동 업데이트 — 4단계 자가 교체", { sub: "재설치 없이 새 버전 도달 — 다운로드 무결성(sha256)과 실행 파일 잠금 문제를 모두 처리" });
  const steps = [
    ["확인", "Nexus의 latest.json GET (5분 캐시) — URL·sha256 형식 검증 실패 시 조용히 무시"],
    ["적용", "새 EXE 스트리밍 다운로드 → sha256 검증 → .new.exe 스테이징 → Updater 분리 실행 후 서버 자진 종료"],
    ["대기", "Updater.exe가 부모 프로세스 종료를 폴링 (최대 60초 + 3초 추가 유예)"],
    ["교체", "rename-to-backup: 현재→.old → new→현재 → 재기동 / 실패 시 .old 복원 (롤백)"],
  ];
  steps.forEach((st, i) => {
    const y = 2.0 + i * 0.92;
    numDot(pres, s, 0.7, y + 0.12, 0.44, i + 1);
    card(pres, s, 1.35, y, 11.3, 0.76);
    s.addText(st[0], {
      x: 1.62, y, w: 1.1, h: 0.76, fontFace: T.KR, fontSize: 13.5, bold: true, color: T.INK, valign: "middle", margin: 0,
    });
    s.addText(st[1], {
      x: 2.8, y, w: 9.7, h: 0.76, fontFace: T.KR, fontSize: 11, color: T.MUT, valign: "middle", margin: 0, lineSpacingMultiple: 1.15,
    });
  });
  card(pres, s, 0.7, 5.85, 11.95, 1.0, { fill: T.BG2, noLine: true });
  s.addText([
    { text: "왜 직접 덮어쓰지 않고 rename-to-backup인가   ", options: { bold: true, color: T.ACC_DK, fontSize: 11.5 } },
    { text: "방금 종료된 EXE의 잔존 파일 잠금 + 백신 스캔 때문에 직접 교체는 ACCESS_DENIED가 발생한다. rename은 잠긴 파일에도 허용되므로 30회 × 0.5초 재시도로 안전하게 교체한다.", options: { color: T.INK, fontSize: 11 } },
  ], { x: 1.0, y: 5.97, w: 11.35, h: 0.78, fontFace: T.KR, margin: 0, valign: "top", lineSpacingMultiple: 1.25 });
}

function s_env(pres) {
  const s = lightSlide(pres);
  header(s, "PART 1 · 전체 흐름", "환경 변수 — .env 단일 진실 공급원");
  codeBlock(pres, s, 0.7, 1.7, 5.6, 1.7, [
    { t: ".env ─┬─ backend (load_dotenv)", c: T.CODE_TX, b: true },
    { t: "      ├─ vite.config.js  dev 프록시", c: T.CODE_TX },
    { t: "      ├─ App.spec  EXE 이름·번들 결정", c: T.CODE_TX },
    { t: "      └─ release.ps1  자격증명", c: T.CODE_TX },
  ], { size: 10, lh: 1.35 });
  card(pres, s, 6.55, 1.7, 6.1, 1.7, { fill: T.BG2, noLine: true });
  s.addText([
    { text: "frozen EXE의 .env 우선순위", options: { bold: true, color: T.ACC_DK, fontSize: 11.5, breakLine: true, paraSpaceAfter: 4 } },
    { text: "빌드 시 박제된 .env를 override=False로 읽으므로 OS 환경 변수가 있으면 그쪽이 우선 — 임시 오버라이드는 가능, 근본 변경은 재빌드.", options: { color: T.INK, fontSize: 10.5 } },
  ], { x: 6.85, y: 1.88, w: 5.5, h: 1.35, fontFace: T.KR, margin: 0, lineSpacingMultiple: 1.25 });
  table(pres, s, 0.7, 3.62, 11.95, ["변수", "기본값", "의미"], [
    [{ t: "APP_NAME", mono: true, s: 9.5 }, "MyAgent", "EXE 파일명·%APPDATA% 폴더 — 앱 이름 변경은 이 값 하나"],
    [{ t: "APP_DEV_PORT", mono: true, s: 9.5 }, "8765", "dev 전용 백엔드 포트 (frozen은 동적 할당이라 무관)"],
    [{ t: "APP_LLM_PROVIDER", mono: true, s: 9.5 }, "mock", "최초 기동 시 settings.json 시드 (mock·dtgpt·openai_compatible)"],
    [{ t: "APP_MAX_AGENT_ITERATIONS", mono: true, s: 9.5 }, "8", "한 턴당 provider→도구 반복 상한"],
    [{ t: "APP_MAX_AGENT_CALLS_PER_TURN", mono: true, s: 9.5 }, "20", "오케스트레이터+서브 합산 LLM 호출 예산"],
    [{ t: "APP_TOOL_DEFAULT_TIMEOUT", mono: true, s: 9.5 }, "30", "도구 1회 실행 타임아웃 (초)"],
    [{ t: "APP_ALLOWED_LIBRARIES", mono: true, s: 9.5 }, "scripts,polars", "에이전트에 노출할 패키지 CSV — EXE 빌드 시 자동 번들링"],
    [{ t: "APP_REPO_BASE_URL / _USER / _PASSWORD", mono: true, s: 9.5 }, "(내부)", "업데이트 저장소 URL·업로드 자격증명"],
  ], { size: 10, colW: [3.6, 1.45, 6.9], rowH: 0.345 });
  s.addText("이외 생명주기(GRACE)·생성 파라미터·캐시 TTL 등 — 전체 목록: backend/core/config.py · backend/agent/config.py", {
    x: 0.7, y: 6.78, w: 11.9, h: 0.28, fontFace: T.KR, fontSize: 9.5, color: T.FAINT, margin: 0,
  });
}

function s_psa(pres) {
  const s = lightSlide(pres);
  header(s, "PART 1 · 전체 흐름", "PROMPTS · SKILLS · AGENTS — 코드 수정 없는 확장", { sub: "에이전트의 “행동”은 Python 코드가 아니라 마크다운 파일로 정의된다 — 빌드 시 EXE에 자동 번들링" });
  const cards = [
    ["PROMPTS/", "헌법", "모든 턴에 항상 적용", "정체성·응답 스타일·안전 규칙·라우팅 원칙", "base → safety → orchestrator(AGENTS 있을 때) → domain 순으로 합성"],
    ["SKILLS/", "업무 매뉴얼", "트리거 키워드 매칭 시", "특정 작업의 절차·필수 입력·금지 사항", "trigger 배열 부분 매칭, 최대 3개 동시 · /이름 으로 강제 활성화"],
    ["AGENTS/", "팀원 프로필", "오케스트레이터가 위임할 때", "서브 에이전트 페르소나·전담 스킬·도구 권한", "skills 매핑 = 자동 위임(Case 3) · tools 화이트리스트 · 격리 실행"],
  ];
  cards.forEach((c, i) => {
    const x = 0.7 + i * 4.12, y = 1.95, w = 3.85, h = 3.3;
    card(pres, s, x, y, w, h);
    s.addText(c[0], {
      x: x + 0.25, y: y + 0.2, w: 2.3, h: 0.35, fontFace: T.MONO, fontSize: 14, bold: true, color: T.INK, margin: 0,
    });
    chip(pres, s, x + w - 1.5, y + 0.2, 1.25, 0.36, c[1], { size: 10 });
    s.addText(c[2], {
      x: x + 0.25, y: y + 0.72, w: w - 0.5, h: 0.3, fontFace: T.KR, fontSize: 10.5, bold: true, color: T.ACC_DK, margin: 0,
    });
    s.addText(c[3], {
      x: x + 0.25, y: y + 1.1, w: w - 0.5, h: 0.7, fontFace: T.KR, fontSize: 11, color: T.INK, margin: 0, lineSpacingMultiple: 1.2,
    });
    s.addShape(pres.shapes.LINE, { x: x + 0.25, y: y + 1.95, w: w - 0.5, h: 0, line: { color: T.LINE, width: 1 } });
    s.addText(c[4], {
      x: x + 0.25, y: y + 2.08, w: w - 0.5, h: 1.1, fontFace: T.KR, fontSize: 9.8, color: T.MUT, margin: 0, lineSpacingMultiple: 1.25,
    });
  });
  // 하단: 핫리로드 + Mock 경고
  card(pres, s, 0.7, 5.5, 7.4, 1.35, { fill: T.BG2, noLine: true });
  s.addText([
    { text: "로딩 정책   ", options: { bold: true, color: T.ACC_DK, fontSize: 11.5, breakLine: true, paraSpaceAfter: 4 } },
    { text: "메타데이터(Front Matter)는 부팅 시 1회, 본문은 필요할 때 lazy 로드.", options: { color: T.INK, fontSize: 10.5, breakLine: true, paraSpaceAfter: 3 } },
    { text: "dev는 mtime 기반 핫리로드 — 서버 재시작 없이 다음 턴부터 반영. frozen은 빌드 시 박제.", options: { color: T.MUT, fontSize: 10.5 } },
  ], { x: 1.0, y: 5.64, w: 6.85, h: 1.1, fontFace: T.KR, margin: 0, lineSpacingMultiple: 1.2 });
  card(pres, s, 8.35, 5.5, 4.3, 1.35, { fill: T.ACC_SOFT, noLine: true });
  s.addText([
    { text: "현재 내용물은 Mock이다  ", options: { bold: true, color: T.ACC_DK, fontSize: 11.5, breakLine: true, paraSpaceAfter: 4 } },
    { text: "지금의 SKILLS·AGENTS·scripts는 LLM 없이 하니스/UI를 검증하기 위한 것 — 운영 시 도메인 파일로 교체", options: { color: T.INK, fontSize: 10.5 } },
  ], { x: 8.63, y: 5.64, w: 3.75, h: 1.1, fontFace: T.KR, margin: 0, lineSpacingMultiple: 1.2 });
}

module.exports = { s_define, s_goals, s_bigpicture, s_runtime, s_stack, s_arch, s_dirs, s_devfrozen, s_build, s_update, s_env, s_psa };
