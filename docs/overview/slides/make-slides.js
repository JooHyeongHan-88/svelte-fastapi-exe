// 프로젝트 소개 슬라이드 생성기 — docs/overview/*.md 3부작의 슬라이드 버전
// 실행: NODE_PATH=<글로벌 node_modules> node make-slides.js
const pptxgen = require("pptxgenjs");
const { cover, agenda, divider, closing } = require("./s0-cover");
const p1 = require("./s1-overview");
const p2 = require("./s2-ux");
const p3 = require("./s3-backend");

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.33 × 7.5 in
pres.author = "hanjoo";
pres.title = "단일 EXE로 배포하는 로컬 AI Agent 플랫폼 — 프로젝트 소개";

cover(pres);
agenda(pres);

divider(pres, 1, "프로젝트 전체 흐름", "무엇을 만들고, 어떻게 빌드·배포되는가", [
  "한 문장 정의", "설계 목표", "5단계 큰 그림", "아키텍처", "빌드·배포", "자동 업데이트", "환경 변수", "PROMPTS·SKILLS·AGENTS",
]);
p1.s_define(pres);
p1.s_goals(pres);
p1.s_bigpicture(pres);
p1.s_runtime(pres);
p1.s_stack(pres);
p1.s_arch(pres);
p1.s_dirs(pres);
p1.s_devfrozen(pres);
p1.s_build(pres);
p1.s_update(pres);
p1.s_env(pres);
p1.s_psa(pres);

divider(pres, 2, "구현된 UX / UI", "최종 사용자가 만나는 화면과 기능", [
  "화면 레이아웃", "세션·입력", "진행 가시화", "활동 타임라인", "아티팩트 패널", "차트 인터랙션", "설정·업데이트", "Mock 시나리오",
]);
p2.s_layout(pres);
p2.s_session(pres);
p2.s_progress(pres);
p2.s_timeline(pres);
p2.s_askuser(pres);
p2.s_artifact(pres);
p2.s_chart(pres);
p2.s_settings(pres);
p2.s_mock(pres);

divider(pres, 3, "Backend 동작 흐름", "기동부터 채팅 한 턴이 처리되는 전 과정", [
  "5가지 책임", "기동·생명주기", "API 지도", "모듈 지도", "run_turn", "SSE 이벤트", "라우팅·위임", "Registry·도구", "산출물 파이프라인", "안전장치",
]);
p3.s_duties(pres);
p3.s_boot(pres);
p3.s_api(pres);
p3.s_modules(pres);
p3.s_runturn(pres);
p3.s_sse(pres);
p3.s_routing(pres);
p3.s_registry(pres);
p3.s_tools(pres);
p3.s_pipeline(pres);
p3.s_safety(pres);

closing(pres);

pres.writeFile({ fileName: __dirname + "/project-intro.pptx" }).then((f) => {
  console.log("written:", f);
});
