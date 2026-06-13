<script>
  import { ui } from "../lib/state.svelte.js";
  import { sendMessage, stopStreaming } from "../lib/chatActions.svelte.js";
  import SkillPicker from "./SkillPicker.svelte";

  // contenteditable 입력창. Svelte 가 관리하는 자식을 두지 않고 내용은 명령형으로 조작한다
  // (Svelte 반응성과 DOM 변형 충돌 방지). 인용은 contenteditable=false pill atom 으로 인라인 삽입.
  let editorEl = $state(null);
  let highlight = $state(0);
  // 슬래시 picker 판정·빈 상태 판정용 평문 거울. 입력/삽입/삭제 때 editorEl 에서 동기화.
  let plainText = $state("");
  let hasPills = $state(false);
  // 에디터 밖 버튼(@참조)이 포커스를 가져가도 caret 위치를 복원하려고 보존하는 range.
  let savedRange = null;
  // 외부 신호(삽입/복원) 중복 소비 방지용 nonce 기억.
  let lastInsertNonce = 0;
  let lastSetNonce = 0;

  let pickerOpen = $derived(plainText.startsWith("/"));
  let pickerQuery = $derived(pickerOpen ? plainText.slice(1) : "");
  let filteredSkills = $derived(filterSkills(ui.availableSkills, pickerQuery));

  let isEmpty = $derived(plainText.trim().length === 0 && !hasPills);
  let canSend = $derived((!isEmpty || ui.composerSkills.length > 0) && !ui.streaming);

  let placeholder = $derived(
    ui.streaming
      ? "응답 중…  ·  ESC 로 중지"
      : ui.composerSkills.length > 0
        ? "본문을 입력하세요 (Backspace 로 스킬 제거)"
        : "메시지를 입력하세요  ·  / 로 스킬 호출",
  );

  function filterSkills(all, q) {
    const needle = (q ?? "").trim().toLowerCase();
    if (!needle) return all.slice(0, 6);
    return all
      .filter((s) => `${s.name} ${s.description ?? ""}`.toLowerCase().includes(needle))
      .slice(0, 6);
  }

  // ── 에디터 상태 동기화 ──────────────────────────────────────────────
  function syncEditorState() {
    if (!editorEl) return;
    plainText = editorEl.textContent ?? "";
    hasPills = !!editorEl.querySelector(".ref-pill");
  }

  function saveRange() {
    const sel = window.getSelection();
    if (!sel || sel.rangeCount === 0) return;
    const r = sel.getRangeAt(0);
    if (editorEl && editorEl.contains(r.commonAncestorContainer)) {
      savedRange = r.cloneRange();
    }
  }

  function focusEnd() {
    if (!editorEl) return;
    editorEl.focus();
    const sel = window.getSelection();
    const r = document.createRange();
    r.selectNodeContents(editorEl);
    r.collapse(false);
    sel.removeAllRanges();
    sel.addRange(r);
    savedRange = r.cloneRange();
  }

  // ── pill DOM (Svelte 컴포넌트 대신 평 DOM — contenteditable 안에 안전하게 삽입) ──
  function buildPill(path, label) {
    const span = document.createElement("span");
    span.className = "ref-pill";
    span.contentEditable = "false";
    span.dataset.path = path;
    span.dataset.label = label;
    span.title = path;
    span.innerHTML =
      '<svg class="ref-pill-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>';
    const lbl = document.createElement("span");
    lbl.className = "ref-pill-label";
    lbl.textContent = label;
    span.appendChild(lbl);
    return span;
  }

  function insertPill(path, label) {
    if (!editorEl) return;
    editorEl.focus();
    const sel = window.getSelection();
    let range;
    if (savedRange && editorEl.contains(savedRange.commonAncestorContainer)) {
      range = savedRange.cloneRange();
    } else {
      range = document.createRange();
      range.selectNodeContents(editorEl);
      range.collapse(false);
    }
    sel.removeAllRanges();
    sel.addRange(range);
    range.deleteContents();
    const pill = buildPill(path, label);
    const space = document.createTextNode(" "); // pill 뒤 caret 자리 확보
    range.insertNode(space);
    range.insertNode(pill);
    range.setStartAfter(space);
    range.collapse(true);
    sel.removeAllRanges();
    sel.addRange(range);
    savedRange = range.cloneRange();
    syncEditorState();
  }

  // caret 직전에 붙어 있는 pill 엘리먼트를 반환 (없으면 null) — 백스페이스 통째 삭제용.
  function pillBeforeCaret() {
    const sel = window.getSelection();
    if (!sel || sel.rangeCount === 0 || !sel.isCollapsed) return null;
    const r = sel.getRangeAt(0);
    const node = r.startContainer;
    if (node.nodeType === Node.TEXT_NODE) {
      if (r.startOffset > 0) return null; // 텍스트 중간 — 일반 글자 삭제
      const prev = node.previousSibling;
      return _isPill(prev) ? prev : null;
    }
    const child = node.childNodes[r.startOffset - 1];
    return _isPill(child) ? child : null;
  }

  function _isPill(node) {
    return (
      node &&
      node.nodeType === Node.ELEMENT_NODE &&
      node.classList?.contains("ref-pill")
    );
  }

  // ── parts 직렬화 (text 노드 + pill atom + br → 순서 있는 배열) ──
  function readParts() {
    const parts = [];
    const pushText = (t) => {
      if (!t) return;
      const last = parts[parts.length - 1];
      if (last && last.type === "text") last.value += t;
      else parts.push({ type: "text", value: t });
    };
    const walk = (node) => {
      node.childNodes.forEach((n) => {
        if (n.nodeType === Node.TEXT_NODE) {
          pushText(n.textContent.replace(/ /g, " "));
        } else if (n.nodeType === Node.ELEMENT_NODE) {
          if (_isPill(n)) {
            parts.push({ type: "ref", path: n.dataset.path, label: n.dataset.label });
          } else if (n.tagName === "BR") {
            pushText("\n");
          } else {
            pushText("\n"); // 예기치 못한 블록(붙여넣기 잔재) — 줄바꿈 후 재귀
            walk(n);
          }
        }
      });
    };
    walk(editorEl);
    return parts;
  }

  function clearEditor() {
    if (editorEl) editorEl.innerHTML = "";
    savedRange = null;
    syncEditorState();
  }

  function setEditorFromParts(parts) {
    if (!editorEl) return;
    editorEl.innerHTML = "";
    for (const p of parts ?? []) {
      if (p.type === "ref" && p.path) {
        editorEl.appendChild(buildPill(p.path, p.label || p.path));
        editorEl.appendChild(document.createTextNode(" "));
      } else if (p.type === "text") {
        editorEl.appendChild(document.createTextNode(p.value ?? ""));
      }
    }
    syncEditorState();
    queueMicrotask(() => focusEnd());
  }

  // ── 액션 ────────────────────────────────────────────────────────────
  function pickSkill(name) {
    if (!name) return;
    if (!ui.composerSkills.includes(name)) {
      ui.composerSkills = [...ui.composerSkills, name];
    }
    clearEditor(); // "/query" 토큰 제거 — 본문은 사용자가 다시 작성한다고 가정 (단순 정책).
    highlight = 0;
    focusEnd();
  }

  function removeSkill(name) {
    ui.composerSkills = ui.composerSkills.filter((s) => s !== name);
    editorEl?.focus();
  }

  async function submit() {
    if (!canSend) return;
    // 빈 본문 + 스킬만 있는 경우 빈 parts 로 전송 (skill 이름이 본문 대체).
    const parts = isEmpty ? [] : readParts();
    clearEditor();
    await sendMessage(parts);
  }

  function insertLineBreak() {
    const sel = window.getSelection();
    if (!sel || sel.rangeCount === 0) return;
    const r = sel.getRangeAt(0);
    r.deleteContents();
    const br = document.createElement("br");
    r.insertNode(br);
    r.setStartAfter(br);
    r.collapse(true);
    sel.removeAllRanges();
    sel.addRange(r);
    saveRange();
    syncEditorState();
  }

  function onInput() {
    highlight = 0;
    syncEditorState();
    saveRange();
  }

  function onPaste(e) {
    e.preventDefault();
    const text = e.clipboardData?.getData("text/plain") ?? "";
    if (!text) return;
    const sel = window.getSelection();
    if (!sel || sel.rangeCount === 0) return;
    const r = sel.getRangeAt(0);
    r.deleteContents();
    const node = document.createTextNode(text);
    r.insertNode(node);
    r.setStartAfter(node);
    r.collapse(true);
    sel.removeAllRanges();
    sel.addRange(r);
    saveRange();
    syncEditorState();
  }

  function onKey(e) {
    // 패널 열림 — 화살표/Enter/Esc/Tab 을 가로채 picker 조작에만 사용.
    if (pickerOpen && filteredSkills.length > 0) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        highlight = (highlight + 1) % filteredSkills.length;
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        highlight = (highlight - 1 + filteredSkills.length) % filteredSkills.length;
        return;
      }
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
        e.preventDefault();
        pickSkill(filteredSkills[highlight]?.name);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        clearEditor(); // 패널 닫기 = "/" 토큰 제거.
        return;
      }
      if (e.key === "Tab") {
        e.preventDefault();
        pickSkill(filteredSkills[highlight]?.name);
        return;
      }
    }

    // 백스페이스 — caret 직전이 pill 이면 글자 단위가 아니라 통째 삭제.
    if (e.key === "Backspace" && !e.isComposing) {
      const pill = pillBeforeCaret();
      if (pill) {
        e.preventDefault();
        const after = pill.nextSibling;
        pill.remove();
        // pill 직후 caret 정착자(nbsp)도 같이 정리해 흔적이 남지 않게 한다.
        if (after && after.nodeType === Node.TEXT_NODE && after.textContent === " ") {
          after.remove();
        }
        syncEditorState();
        saveRange();
        return;
      }
      // 빈 입력에서 백스페이스 → 마지막 스킬 칩 제거 (UX 통념).
      if (isEmpty && ui.composerSkills.length > 0) {
        e.preventDefault();
        ui.composerSkills = ui.composerSkills.slice(0, -1);
        return;
      }
    }

    // Enter — 전송, Shift+Enter — 줄바꿈. 한글 조합(isComposing) 중엔 무시.
    if (e.key === "Enter" && !e.isComposing) {
      if (e.shiftKey) {
        e.preventDefault();
        insertLineBreak();
      } else {
        e.preventDefault();
        submit();
      }
    }
  }

  // ── 외부 신호 소비 ($effect — composerSeed 패턴 계승, nonce 로 중복 방지) ──
  $effect(() => {
    const sig = ui.composerInsertRef;
    if (sig && sig.nonce !== lastInsertNonce) {
      lastInsertNonce = sig.nonce;
      for (const item of sig.items ?? []) insertPill(item.path, item.label);
      ui.composerInsertRef = null;
      queueMicrotask(() => editorEl?.focus());
    }
  });

  $effect(() => {
    const sig = ui.composerSetParts;
    if (sig && sig.nonce !== lastSetNonce) {
      lastSetNonce = sig.nonce;
      setEditorFromParts(sig.parts ?? []);
      ui.composerSetParts = null;
    }
  });

  // 윈도우 레벨 ESC — 입력창이 streaming 중 비편집이라 onKey 가 안 잡힌다.
  function onWindowKey(e) {
    if (e.key !== "Escape" || !ui.streaming) return;
    e.preventDefault();
    stopStreaming();
  }
</script>

<svelte:window onkeydown={onWindowKey} />

<div class="composer-wrap">
  <!-- 슬래시 커맨드 패널 — 입력창 위에 부유 -->
  {#if pickerOpen}
    <div class="picker-anchor">
      <SkillPicker
        query={pickerQuery}
        skills={ui.availableSkills}
        {highlight}
        onPick={pickSkill}
      />
    </div>
  {/if}

  <!-- 부착된 skill chip — 입력창 위 별도 줄 (스킬은 위치 비의존 modifier 라 트레이 유지) -->
  {#if ui.composerSkills.length > 0}
    <div class="chips">
      {#each ui.composerSkills as name (name)}
        <span class="chip">
          <span class="chip-icon">✦</span>
          {name}
          <button
            type="button"
            class="chip-remove"
            onclick={() => removeSkill(name)}
            aria-label={`${name} 제거`}
          >×</button>
        </span>
      {/each}
    </div>
  {/if}

  <div class="composer">
    <div
      bind:this={editorEl}
      class="editor"
      class:is-empty={isEmpty}
      contenteditable={ui.streaming ? "false" : "true"}
      role="textbox"
      tabindex="0"
      aria-multiline="true"
      aria-label="메시지 입력"
      data-placeholder={placeholder}
      oninput={onInput}
      onkeydown={onKey}
      onpaste={onPaste}
      onkeyup={saveRange}
      onmouseup={saveRange}
      onblur={saveRange}
    ></div>
    <button class="send" onclick={submit} disabled={!canSend} aria-label="전송">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M22 2 11 13" />
        <path d="m22 2-7 20-4-9-9-4 20-7z" />
      </svg>
    </button>
  </div>
  <div class="hint">Enter 로 전송 · Shift+Enter 줄바꿈 · / 로 스킬 검색</div>
</div>

<style>
  .composer-wrap {
    max-width: 760px;
    margin: 0 auto;
    padding: 12px 24px 18px;
    width: 100%;
    position: relative; /* picker-anchor 의 절대 위치 기준 */
  }

  /* SkillPicker 를 입력창 바로 위에 띄움 */
  .picker-anchor {
    position: absolute;
    left: 24px;
    right: 24px;
    bottom: calc(100% - 4px);
    z-index: 20;
  }

  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-bottom: 8px;
  }

  .chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 12px;
    font-weight: 500;
    color: var(--accent);
    background: var(--accent-soft);
    border: 1px solid var(--accent-border);
    border-radius: var(--radius-full);
    padding: 3px 4px 3px 9px;
    line-height: 1.4;
  }

  .chip-icon {
    font-size: 11px;
  }

  .chip-remove {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    margin-left: 2px;
    color: var(--accent);
    font-size: 14px;
    line-height: 1;
    opacity: 0.7;
    transition: opacity var(--dur-fast) ease, background var(--dur-fast) ease;
  }

  .chip-remove:hover {
    opacity: 1;
    background: var(--accent-soft-strong);
  }

  .composer {
    display: flex;
    align-items: flex-end;
    gap: 8px;
    background: var(--bg-elevated);
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-lg);
    padding: 10px 10px 10px 14px;
    box-shadow: var(--shadow-sm);
    transition: border-color var(--dur-fast) ease, box-shadow var(--dur-fast) ease;
  }

  .composer:focus-within {
    border-color: var(--accent);
    box-shadow: var(--focus-ring);
  }

  .editor {
    flex: 1;
    min-width: 0;
    outline: none;
    background: transparent;
    font-size: 15px; /* 채팅 본문(.markdown 15px)과 톤 일치 */
    line-height: 1.5;
    padding: 4px 0;
    min-height: 24px;
    max-height: 200px;
    overflow-y: auto;
    color: var(--fg);
    white-space: pre-wrap;
    word-break: break-word;
    position: relative;
  }

  /* 빈 상태 placeholder — :empty 는 bogus <br> 에 취약해 is-empty 클래스로 제어 */
  .editor.is-empty::before {
    content: attr(data-placeholder);
    color: var(--fg-subtle);
    pointer-events: none;
  }

  /* 인라인 인용 pill — 본문 텍스트와 구분되는 액센트 톤 */
  :global(.editor .ref-pill) {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    vertical-align: baseline;
    font-size: 13px;
    font-weight: 500;
    color: var(--accent);
    background: var(--accent-soft);
    border: 1px solid var(--accent-border);
    border-radius: var(--radius-sm);
    padding: 0 6px;
    margin: 0 1px;
    line-height: 1.5;
    white-space: nowrap;
    user-select: none;
    cursor: default;
  }

  :global(.editor .ref-pill-icon) {
    flex-shrink: 0;
    opacity: 0.85;
  }

  :global(.editor .ref-pill-label) {
    max-width: 220px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .send {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 34px;
    height: 34px;
    border-radius: var(--radius-md);
    background: var(--accent);
    color: var(--accent-fg);
    transition: background var(--dur-fast) ease, transform 0.06s ease;
    flex-shrink: 0;
  }

  .send:hover:not(:disabled) {
    background: var(--accent-hover);
  }

  .send:active:not(:disabled) {
    transform: scale(0.96);
  }

  .send:disabled {
    background: var(--border-strong);
    color: var(--fg-subtle);
  }

  .hint {
    text-align: center;
    margin-top: 8px;
    font-size: 11.5px;
    color: var(--fg-subtle);
  }
</style>
