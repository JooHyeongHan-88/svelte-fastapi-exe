// Claude(Anthropic) 스타일 디자인 시스템 + 공용 헬퍼
// 팔레트: 아이보리 배경 + 차콜 잉크 + 테라코타 액센트 (Claude 브랜드 톤)

const T = {
  BG: "FAF9F5", // 아이보리 (라이트 슬라이드 배경)
  BG2: "F0EEE6", // 짙은 아이보리 (패널)
  DARK: "1F1E1D", // 차콜 (다크 슬라이드 배경 / 잉크)
  INK: "262522",
  MUT: "6E6B64", // 본문 보조 (웜 그레이)
  FAINT: "A39F95",
  ACC: "D97757", // 테라코타 (Claude 액센트)
  ACC_DK: "B0552F", // 작은 글자용 진한 테라코타
  ACC_SOFT: "F3E3D9", // 연한 테라코타 (칩 배경)
  WHITE: "FFFFFF",
  LINE: "E5E2D9", // 카드 테두리
  CODE_BG: "27261F",
  CODE_TX: "EDEAE0",
  CODE_MUT: "9A958A",
  CODE_ACC: "E89B7D",
  OK: "6E8B68", // 차분한 세이지 그린 (✓)
  DK_TX: "F5F3EC", // 다크 슬라이드 본문
  DK_MUT: "B5B1A6",
  KR: "Malgun Gothic",
  SER: "Georgia",
  MONO: "Consolas",
  W: 13.33,
  H: 7.5,
};

let pageNo = 0;

function stamp(slide, dark) {
  pageNo += 1;
  const c = dark ? T.DK_MUT : T.FAINT;
  slide.addText("Local AI Agent Platform — 프로젝트 소개", {
    x: 0.55, y: T.H - 0.42, w: 5, h: 0.3, fontFace: T.KR, fontSize: 8,
    color: c, align: "left", margin: 0,
  });
  slide.addText(String(pageNo).padStart(2, "0"), {
    x: T.W - 1.15, y: T.H - 0.42, w: 0.6, h: 0.3, fontFace: T.SER, fontSize: 9,
    color: c, align: "right", margin: 0,
  });
  return pageNo;
}

function lightSlide(pres) {
  const s = pres.addSlide();
  s.background = { color: T.BG };
  stamp(s, false);
  return s;
}

function darkSlide(pres) {
  const s = pres.addSlide();
  s.background = { color: T.DARK };
  stamp(s, true);
  return s;
}

// 상단 헤더: 키커(테라코타 소문구) + 제목
function header(slide, kicker, title, opts = {}) {
  slide.addText(kicker, {
    x: 0.7, y: 0.42, w: 11.9, h: 0.3, fontFace: T.KR, fontSize: 11, bold: true,
    color: T.ACC_DK, charSpacing: 2, margin: 0,
  });
  slide.addText(title, {
    x: 0.7, y: 0.72, w: 11.9, h: 0.62, fontFace: T.KR, fontSize: 25, bold: true,
    color: T.INK, margin: 0,
  });
  if (opts.sub) {
    slide.addText(opts.sub, {
      x: 0.7, y: 1.34, w: 11.9, h: 0.3, fontFace: T.KR, fontSize: 11.5,
      color: T.MUT, margin: 0,
    });
  }
}

function card(pres, slide, x, y, w, h, opts = {}) {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x, y, w, h, rectRadius: opts.r ?? 0.07,
    fill: { color: opts.fill || T.WHITE },
    line: opts.noLine ? { type: "none" } : { color: opts.line || T.LINE, width: opts.lineW ?? 1 },
  });
}

// 알약형 칩
function chip(pres, slide, x, y, w, h, text, opts = {}) {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x, y, w, h, rectRadius: h / 2,
    fill: { color: opts.fill || T.ACC_SOFT },
    line: opts.line ? { color: opts.line, width: 0.75 } : { type: "none" },
  });
  slide.addText(text, {
    x, y: y - 0.012, w, h, align: "center", valign: "middle", margin: 0,
    fontFace: opts.font || T.KR, fontSize: opts.size || 10, bold: opts.bold !== false,
    color: opts.color || T.ACC_DK,
  });
}

// 번호 원
function numDot(pres, slide, x, y, d, label, opts = {}) {
  slide.addShape(pres.shapes.OVAL, {
    x, y, w: d, h: d, fill: { color: opts.fill || T.ACC }, line: { type: "none" },
  });
  slide.addText(String(label), {
    x, y: y - 0.015, w: d, h: d, align: "center", valign: "middle", margin: 0,
    fontFace: opts.font || T.SER, fontSize: opts.size || 12, bold: true,
    color: opts.color || "FFFFFF",
  });
}

// 다크 코드 블록 — lines: [{t, c?, b?}] 또는 문자열
function codeBlock(pres, slide, x, y, w, h, lines, opts = {}) {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x, y, w, h, rectRadius: 0.08, fill: { color: T.CODE_BG }, line: { type: "none" },
  });
  const runs = lines.map((ln, i) => {
    const o = typeof ln === "string" ? { t: ln } : ln;
    return {
      text: o.t,
      options: {
        color: o.c || T.CODE_TX, bold: !!o.b, breakLine: i < lines.length - 1,
        fontSize: o.s || opts.size || 9.5,
      },
    };
  });
  slide.addText(runs, {
    x: x + 0.22, y: y + (opts.padY ?? 0.14), w: w - 0.44, h: h - (opts.padY ?? 0.14) * 2,
    fontFace: T.MONO, fontSize: opts.size || 9.5, color: T.CODE_TX,
    valign: opts.valign || "top", margin: 0, lineSpacingMultiple: opts.lh || 1.25,
  });
}

// 표 — rows: [[셀,...],...] 셀: 문자열 또는 {t, ...옵션}
function table(pres, slide, x, y, w, head, rows, opts = {}) {
  const headRow = head.map((h) => ({
    text: h,
    options: {
      fill: { color: opts.headFill || T.DARK }, color: opts.headColor || T.DK_TX,
      bold: true, fontSize: opts.headSize || (opts.size || 10),
      valign: "middle", align: "left",
    },
  }));
  const bodyRows = rows.map((r, ri) =>
    r.map((c) => {
      const o = typeof c === "string" ? { t: c } : c;
      return {
        text: o.t,
        options: {
          fill: { color: o.fill || (ri % 2 ? T.BG2 : T.WHITE) },
          color: o.c || T.INK, bold: !!o.b, italic: !!o.i,
          fontFace: o.mono ? T.MONO : T.KR,
          fontSize: o.s || opts.size || 10, valign: "middle", align: o.align || "left",
        },
      };
    })
  );
  slide.addTable([headRow, ...bodyRows], {
    x, y, w, colW: opts.colW, rowH: opts.rowH || 0.3,
    border: { pt: 0.75, color: T.LINE }, fontFace: T.KR,
    margin: opts.margin || [0.04, 0.08, 0.04, 0.08], autoPage: false,
  });
}

// 클로드풍 스타버스트 마크 (프리셋 star 도형, 없으면 원으로 폴백)
function starMark(pres, slide, x, y, d, color) {
  const shape =
    pres.shapes.STAR_12_POINT || pres.shapes.STAR_16_POINT ||
    pres.shapes.STAR_8_POINT || pres.shapes.OVAL;
  slide.addShape(shape, {
    x, y, w: d, h: d, fill: { color: color || T.ACC }, line: { type: "none" },
  });
}

// 우향 화살표 (텍스트 글리프 — Malgun 지원)
function arrow(slide, x, y, opts = {}) {
  slide.addText("→", {
    x, y, w: opts.w || 0.3, h: opts.h || 0.3, align: "center", valign: "middle",
    fontFace: T.KR, fontSize: opts.size || 14, bold: true, color: opts.color || T.FAINT,
    margin: 0,
  });
}

// 본문 여러 줄 텍스트 — items: [{t, b?, c?, s?, gap?}]
function lines(slide, x, y, w, h, items, opts = {}) {
  const runs = items.map((it, i) => ({
    text: it.t,
    options: {
      bold: !!it.b, color: it.c || T.INK, fontSize: it.s || opts.size || 11,
      breakLine: i < items.length - 1, bullet: it.bullet || false,
      paraSpaceAfter: it.gap ?? opts.gap ?? 4,
      fontFace: it.mono ? T.MONO : opts.font || T.KR,
    },
  }));
  slide.addText(runs, {
    x, y, w, h, fontFace: opts.font || T.KR, valign: opts.valign || "top",
    margin: 0, align: opts.align || "left",
  });
}

module.exports = { T, lightSlide, darkSlide, header, card, chip, numDot, codeBlock, table, starMark, arrow, lines, stamp };
