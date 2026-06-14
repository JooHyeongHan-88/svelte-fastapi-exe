// 마크다운 + 코드 하이라이트. assistant 메시지에만 적용.
// XSS 방어를 위해 marked → DOMPurify 순서로 통과시킨다.

import { Marked } from "marked";
import { markedHighlight } from "marked-highlight";
import DOMPurify from "dompurify";
import hljs from "highlight.js/lib/common";

const marked = new Marked(
  markedHighlight({
    emptyLangClass: "hljs",
    langPrefix: "hljs language-",
    highlight(code, lang) {
      const language = hljs.getLanguage(lang) ? lang : "plaintext";
      return hljs.highlight(code, { language }).value;
    },
  }),
  { breaks: true, gfm: true },
);

// 데스크탑 앱은 채팅이 곧 전체 창이라, 마크다운 링크가 같은 탭으로 이동하면 앱이
// 통째로 대체돼 세션이 소실된다. 모든 링크를 새 탭으로 강제하고 tabnabbing 을 막는다.
// DOMPurify 기본 ALLOWED_ATTR 에는 target 이 없어 그냥 두면 제거되므로, 속성 sanitize
// 이후 실행되는 훅에서 직접 부여한다 (예: open_curation 카드의 /ext/<tool> 진입 링크).
DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  if (node.tagName === "A" && node.getAttribute("href")) {
    node.setAttribute("target", "_blank");
    node.setAttribute("rel", "noopener noreferrer");
  }
});

export function renderMarkdown(text) {
  if (!text) return "";
  return DOMPurify.sanitize(marked.parse(text));
}
