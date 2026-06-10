<script>
  import { ui } from "../lib/state.svelte.js";
  import { sendMessage, stopStreaming } from "../lib/chatActions.svelte.js";
  import SkillPicker from "./SkillPicker.svelte";

  let value = $state("");
  let textareaEl = $state(null);
  let highlight = $state(0);

  const MAX_HEIGHT = 200;

  // 패널은 입력값이 줄 시작에서 "/" 인 경우에만 — 본문 중간 "/" 와의 충돌 회피.
  let pickerOpen = $derived(value.startsWith("/"));
  // "/query" 에서 query 부분만 추출.
  let pickerQuery = $derived(pickerOpen ? value.slice(1) : "");

  // 필터링 후 보이는 항목 — Enter 시 어떤 인덱스를 고를지 결정하는 데 사용.
  let filteredSkills = $derived(filterSkills(ui.availableSkills, pickerQuery));

  function filterSkills(all, q) {
    const needle = (q ?? "").trim().toLowerCase();
    if (!needle) return all.slice(0, 6);
    return all
      .filter((s) => `${s.name} ${s.description ?? ""}`.toLowerCase().includes(needle))
      .slice(0, 6);
  }

  function autoResize() {
    if (!textareaEl) return;
    textareaEl.style.height = "auto";
    const next = Math.min(textareaEl.scrollHeight, MAX_HEIGHT);
    textareaEl.style.height = next + "px";
  }

  function onInput() {
    // 입력이 바뀌면 highlight 를 안전한 위치로 리셋.
    highlight = 0;
    autoResize();
  }

  function pickSkill(name) {
    if (!name) return;
    if (!ui.composerSkills.includes(name)) {
      ui.composerSkills = [...ui.composerSkills, name];
    }
    value = ""; // "/query" 토큰 제거 — 본문은 사용자가 다시 작성한다고 가정 (단순 정책).
    highlight = 0;
    autoResize();
    textareaEl?.focus();
  }

  function removeSkill(name) {
    ui.composerSkills = ui.composerSkills.filter((s) => s !== name);
    textareaEl?.focus();
  }

  async function submit() {
    const text = value;
    const canSubmit = (text.trim().length > 0 || ui.composerSkills.length > 0) && !ui.streaming;
    if (!canSubmit) return;
    value = "";
    autoResize();
    await sendMessage(text);
  }

  function onKey(e) {
    // 패널 열림 — 화살표/Enter/Esc 를 가로채 picker 조작에만 사용.
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
        value = ""; // 패널 닫기 = "/" 토큰 제거.
        autoResize();
        return;
      }
      if (e.key === "Tab") {
        e.preventDefault();
        pickSkill(filteredSkills[highlight]?.name);
        return;
      }
    }

    // 빈 입력 상태에서 Backspace → 마지막 chip 제거 (UX 통념).
    if (
      e.key === "Backspace" &&
      value.length === 0 &&
      ui.composerSkills.length > 0
    ) {
      e.preventDefault();
      ui.composerSkills = ui.composerSkills.slice(0, -1);
      return;
    }

    // 일반 Enter — 전송.
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      submit();
    }
  }

  // skill chip 이 붙어 있으면 본문이 없어도 전송 활성화
  let canSend = $derived((value.trim().length > 0 || ui.composerSkills.length > 0) && !ui.streaming);

  // ui.composerSeed 가 외부에서 채워지면 textarea 에 반영 후 즉시 비운다.
  // 빈 문자열 → 빈 문자열 변경은 Svelte 가 트리거하지 않으므로 무한 루프 위험 없음.
  // rewindToMessage 는 빈 composer 에서 발동하므로 append 든 replace 든 결과가 같고,
  // 아티팩트 참조 삽입(insertArtifactReference)은 기존 입력 뒤에 공백으로 이어 붙인다.
  $effect(() => {
    if (ui.composerSeed) {
      const seed = ui.composerSeed;
      value = value ? `${value.trimEnd()} ${seed}` : seed;
      ui.composerSeed = "";
      // autoResize / focus 는 DOM 갱신 직후가 안전 — microtask 로 한 프레임 미룬다.
      queueMicrotask(() => {
        autoResize();
        textareaEl?.focus();
      });
    }
  });

  // 윈도우 레벨 ESC — textarea 가 streaming 중 disabled 라 onKey 가 안 잡힌다.
  // 입력란 외 어디서든 ESC 를 눌러 스트리밍을 중지할 수 있어야 한다.
  function onWindowKey(e) {
    if (e.key !== "Escape" || !ui.streaming) return;
    // 슬래시 패널 닫기와 충돌하지 않게: streaming 중에는 picker 가 안 뜬다 (입력 비활성).
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

  <!-- 부착된 skill chip — 입력창 위 별도 줄 -->
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
    <textarea
      bind:this={textareaEl}
      bind:value
      oninput={onInput}
      onkeydown={onKey}
      placeholder={ui.streaming
        ? "응답 중…  ·  ESC 로 중지"
        : ui.composerSkills.length > 0
          ? "본문을 입력하세요 (Backspace 로 스킬 제거)"
          : "메시지를 입력하세요  ·  / 로 스킬 호출"}
      rows="1"
      disabled={ui.streaming}
    ></textarea>
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
    /* composer 위 6px 간격, 사이드바와 동일 토큰의 그림자는 SkillPicker 자체에 있음 */
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
    background: color-mix(in srgb, var(--accent) 12%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent) 30%, transparent);
    border-radius: 20px;
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
    transition: opacity 0.1s ease, background 0.1s ease;
  }

  .chip-remove:hover {
    opacity: 1;
    background: color-mix(in srgb, var(--accent) 18%, transparent);
  }

  .composer {
    display: flex;
    align-items: flex-end;
    gap: 8px;
    background: var(--bg-elevated);
    border: 1px solid var(--border-strong);
    border-radius: 14px;
    padding: 10px 10px 10px 14px;
    transition: border-color 0.12s ease, box-shadow 0.12s ease;
  }

  .composer:focus-within {
    border-color: var(--accent);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent);
  }

  textarea {
    flex: 1;
    resize: none;
    border: none;
    outline: none;
    background: transparent;
    font-size: 14.5px;
    line-height: 1.5;
    padding: 4px 0;
    max-height: 200px;
    color: var(--fg);
  }

  textarea::placeholder {
    color: var(--fg-subtle);
  }

  .send {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 34px;
    height: 34px;
    border-radius: 10px;
    background: var(--accent);
    color: var(--accent-fg);
    transition: background 0.12s ease, transform 0.06s ease;
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
