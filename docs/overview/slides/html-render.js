// HTML 슬라이드 렌더 백엔드 — pptxgenjs 의 pres/slide API 를 그대로 흉내 내,
// theme.js + s0~s3 의 슬라이드 정의를 한 글자도 고치지 않고 self-contained HTML 덱으로 출력한다.
//
// 좌표계: pptx 의 inch 를 96px/inch 로 환산한 1280×720(16:9) 고정 캔버스에 절대 배치한다.
// 폰트 크기(pt)는 96/72 = 4/3 배로 px 변환. 슬라이드별 overflow:hidden 으로 "규격 이탈"을 차단한다.

const IN = 96; // px per inch
const PT = 96 / 72; // pt -> px

const FONT = {
  "Malgun Gothic": "'Malgun Gothic','Apple SD Gothic Neo','Noto Sans KR',sans-serif",
  Georgia: "Georgia,'Times New Roman',serif",
  Consolas: "Consolas,'D2Coding','Courier New',monospace",
};

const SHAPES = {
  ROUNDED_RECTANGLE: "roundRect",
  RECTANGLE: "rect",
  OVAL: "oval",
  LINE: "line",
  STAR_12_POINT: "star",
  STAR_16_POINT: "star",
  STAR_8_POINT: "star",
};

// 12각 스타버스트 클립패스 (24 꼭짓점, 바깥 50% / 안쪽 21%)
const STAR_POLY = (() => {
  const pts = [];
  const cx = 50, cy = 50, ro = 50, ri = 21, n = 12;
  for (let i = 0; i < n * 2; i++) {
    const r = i % 2 === 0 ? ro : ri;
    const a = (Math.PI / n) * i - Math.PI / 2;
    pts.push(`${(cx + r * Math.cos(a)).toFixed(2)}% ${(cy + r * Math.sin(a)).toFixed(2)}%`);
  }
  return pts.join(",");
})();

function px(inch) {
  return +(inch * IN).toFixed(2);
}
function ptpx(pt) {
  return +(pt * PT).toFixed(2);
}
function col(c) {
  if (!c) return c;
  return c[0] === "#" ? c : "#" + c;
}
function font(face) {
  return FONT[face] || FONT["Malgun Gothic"];
}
function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// runs([{text, options}]) -> 줄 단위 <div> 묶음. breakLine 으로 줄을 끊고 paraSpaceAfter(pt) 만큼 간격.
function buildRuns(runs) {
  let out = "";
  let line = "";
  const flush = (gapPt) => {
    out += `<div style="min-height:1em;margin-bottom:${ptpx(gapPt || 0)}px">${line || "&nbsp;"}</div>`;
    line = "";
  };
  runs.forEach((r) => {
    const o = r.options || {};
    const st = [];
    if (o.bold) st.push("font-weight:700");
    if (o.italic) st.push("font-style:italic");
    if (o.color) st.push("color:" + col(o.color));
    if (o.fontFace) st.push("font-family:" + font(o.fontFace));
    if (o.fontSize) st.push("font-size:" + ptpx(o.fontSize) + "px");
    let prefix = "";
    if (o.bullet && typeof o.bullet === "object") {
      const glyph = String.fromCodePoint(parseInt(o.bullet.code || "2022", 16));
      prefix = `<span style="color:${col(o.bullet.color) || "#888"}">${glyph}  </span>`;
    }
    line += `${prefix}<span style="${st.join(";")}">${esc(r.text)}</span>`;
    if (o.breakLine) flush(o.paraSpaceAfter);
  });
  flush(0);
  return out;
}

function renderText(t, o) {
  o = o || {};
  const valign =
    o.valign === "middle" ? "center" : o.valign === "bottom" ? "flex-end" : "flex-start";
  const st = [
    "position:absolute",
    `left:${px(o.x || 0)}px`,
    `top:${px(o.y || 0)}px`,
    `width:${px(o.w || 1)}px`,
    `height:${px(o.h || 0.5)}px`,
    "display:flex",
    "flex-direction:column",
    `justify-content:${valign}`,
    `text-align:${o.align || "left"}`,
    "white-space:pre-wrap",
    "word-break:break-word",
    `font-family:${font(o.fontFace)}`,
    `font-size:${ptpx(o.fontSize || 12)}px`,
    `color:${col(o.color) || "#262522"}`,
    `line-height:${o.lineSpacingMultiple || 1.25}`,
  ];
  if (o.bold) st.push("font-weight:700");
  if (o.italic) st.push("font-style:italic");
  if (o.charSpacing) st.push(`letter-spacing:${(o.charSpacing * 0.8).toFixed(2)}px`);

  const inner = Array.isArray(t) ? buildRuns(t) : esc(t);
  return `<div style="${st.join(";")}">${inner}</div>`;
}

function renderShape(type, o) {
  const st = [
    "position:absolute",
    `left:${px(o.x)}px`,
    `top:${px(o.y)}px`,
    `width:${px(o.w)}px`,
  ];
  if (type === SHAPES.LINE) {
    const lw = (o.line && o.line.width) || 1;
    st.push(`height:${lw}px`, `background:${col((o.line && o.line.color) || "#000")}`);
    return `<div style="${st.join(";")}"></div>`;
  }
  st.push(`height:${px(o.h)}px`);
  if (o.fill && o.fill.color) st.push(`background:${col(o.fill.color)}`);
  if (o.line && o.line.type !== "none") {
    st.push(`border:${o.line.width || 1}px solid ${col(o.line.color) || "#000"}`, "box-sizing:border-box");
  }
  if (type === SHAPES.OVAL) st.push("border-radius:50%");
  else if (type === SHAPES.ROUNDED_RECTANGLE) {
    const r = o.rectRadius != null ? o.rectRadius : 0.07;
    st.push(`border-radius:${px(r)}px`);
  } else if (type === SHAPES.STAR_12_POINT) {
    st.push(`clip-path:polygon(${STAR_POLY})`);
  }
  return `<div style="${st.join(";")}"></div>`;
}

function renderTable(rows, o) {
  const colW = o.colW;
  const rowH = px(o.rowH || 0.3);
  const border = o.border
    ? `${o.border.pt || 0.75}px solid ${col(o.border.color) || "#ccc"}`
    : "none";
  const m = o.margin || [0.04, 0.08, 0.04, 0.08];
  const pad = `${px(m[0])}px ${px(m[1])}px ${px(m[2] != null ? m[2] : m[0])}px ${px(
    m[3] != null ? m[3] : m[1]
  )}px`;
  const colgroup = colW
    ? "<colgroup>" + colW.map((c) => `<col style="width:${px(c)}px">`).join("") + "</colgroup>"
    : "";
  let body = "";
  rows.forEach((row) => {
    body += "<tr>";
    row.forEach((cell) => {
      const c = cell.options || {};
      const st = [
        `border:${border}`,
        `padding:${pad}`,
        `height:${rowH}px`,
        "box-sizing:border-box",
        "overflow:hidden",
        `vertical-align:${c.valign === "top" ? "top" : "middle"}`,
        `text-align:${c.align || "left"}`,
        `font-family:${font(c.fontFace || "Malgun Gothic")}`,
        `font-size:${ptpx(c.fontSize || o.size || 10)}px`,
        "white-space:pre-wrap",
        "word-break:break-word",
      ];
      if (c.fill && c.fill.color) st.push(`background:${col(c.fill.color)}`);
      if (c.color) st.push(`color:${col(c.color)}`);
      if (c.bold) st.push("font-weight:700");
      if (c.italic) st.push("font-style:italic");
      body += `<td style="${st.join(";")}">${esc(cell.text)}</td>`;
    });
    body += "</tr>";
  });
  return `<table style="position:absolute;left:${px(o.x)}px;top:${px(
    o.y
  )}px;width:${px(o.w)}px;border-collapse:collapse;table-layout:fixed">${colgroup}${body}</table>`;
}

// pptxgenjs slide 흉내 — addText/addShape/addTable + background 세터
class HtmlSlide {
  constructor() {
    this.html = "";
    this._bg = "#FAF9F5";
  }
  set background(v) {
    if (v && v.color) this._bg = col(v.color);
  }
  get background() {
    return { color: this._bg };
  }
  addText(t, o) {
    this.html += renderText(t, o);
  }
  addShape(type, o) {
    this.html += renderShape(type, o);
  }
  addTable(rows, o) {
    this.html += renderTable(rows, o || {});
  }
}

// pptxgenjs pres 흉내 — addSlide/shapes (+ layout/author/title 세터는 무시)
class HtmlPres {
  constructor() {
    this.slides = [];
    this.shapes = SHAPES;
  }
  addSlide() {
    const s = new HtmlSlide();
    this.slides.push(s);
    return s;
  }
}

function renderDeck(slides, opts = {}) {
  const title = esc(opts.title || "프로젝트 소개");
  const sections = slides
    .map((s) => `<section class="slide" style="background:${s._bg}">${s.html}</section>`)
    .join("\n");
  return `<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>${title}</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
html,body{height:100%;background:#1b1a18;overflow:hidden;font-family:'Malgun Gothic','Noto Sans KR',sans-serif}
.stage{position:fixed;inset:0}
.slide{position:absolute;left:50%;top:50%;width:1280px;height:720px;overflow:hidden;
  transform:translate(-50%,-50%) scale(var(--scale,1));transform-origin:center center;
  display:none;box-shadow:0 12px 48px rgba(0,0,0,.5)}
.slide.active{display:block}
.hud{position:fixed;left:0;right:0;bottom:14px;z-index:50;display:flex;gap:14px;
  justify-content:center;align-items:center;font-family:Georgia,serif;color:#b9b5ab}
.hud button{background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.18);
  color:#e6e3da;border-radius:8px;padding:6px 14px;cursor:pointer;font-size:15px;line-height:1}
.hud button:hover{background:rgba(255,255,255,.16)}
.counter{min-width:74px;text-align:center;font-size:13px;letter-spacing:1.5px}
@media print{
  html,body{overflow:visible;background:#fff}
  .hud{display:none}
  .stage{position:static}
  .slide{display:block!important;position:relative;left:0;top:0;transform:none;
    page-break-after:always;box-shadow:none;margin:0 auto}
  @page{size:1280px 720px;margin:0}
}
</style>
</head>
<body>
<div class="stage">
${sections}
</div>
<div class="hud">
  <button id="prev" aria-label="이전">←</button>
  <span class="counter" id="counter"></span>
  <button id="next" aria-label="다음">→</button>
</div>
<script>
(function(){
  var slides=[].slice.call(document.querySelectorAll('.slide'));
  var counter=document.getElementById('counter');
  var idx=0;
  function fit(){var s=Math.min(window.innerWidth/1280, window.innerHeight/720);
    document.documentElement.style.setProperty('--scale', s);}
  function show(i){idx=(i+slides.length)%slides.length;
    slides.forEach(function(el,j){el.classList.toggle('active', j===idx);});
    counter.textContent=(idx+1)+' / '+slides.length;
    history.replaceState(null,'','#s'+(idx+1));}
  window.addEventListener('keydown',function(e){
    if(['ArrowRight','PageDown',' '].indexOf(e.key)>-1){show(idx+1);e.preventDefault();}
    else if(['ArrowLeft','PageUp'].indexOf(e.key)>-1){show(idx-1);e.preventDefault();}
    else if(e.key==='Home'){show(0);} else if(e.key==='End'){show(slides.length-1);}
  });
  window.addEventListener('resize',fit);
  document.getElementById('prev').onclick=function(){show(idx-1);};
  document.getElementById('next').onclick=function(){show(idx+1);};
  var h=parseInt((location.hash||'').replace('#s',''),10);
  if(h>0) idx=h-1;
  fit(); show(idx);
})();
</script>
</body>
</html>
`;
}

module.exports = { HtmlPres, renderDeck };
