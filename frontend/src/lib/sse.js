// SSE 스트림을 줄(이벤트) 단위로 잘라 onEvent 콜백에 넘긴다.
// 이벤트는 빈 줄(\n\n)로 구분되고, 우리는 data: 라인만 모아 JSON.parse 한다.

export async function parseSseStream(body, onEvent, signal) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  // 외부 abort 시 reader.read() 가 영원히 대기하므로 즉시 cancel 로 풀어준다.
  const onAbort = () => {
    reader.cancel().catch(() => {});
  };
  if (signal) {
    if (signal.aborted) {
      reader.cancel().catch(() => {});
      return;
    }
    signal.addEventListener("abort", onAbort);
  }

  try {
    while (true) {
      if (signal?.aborted) break;
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      let idx;
      while ((idx = buffer.indexOf("\n\n")) !== -1) {
        const rawEvent = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);

        const dataLine = rawEvent
          .split("\n")
          .filter((l) => l.startsWith("data:"))
          .map((l) => l.slice(5).trimStart())
          .join("\n");

        if (!dataLine) continue;

        try {
          onEvent(JSON.parse(dataLine));
        } catch {
          // 손상된 chunk 는 조용히 스킵 — 다음 이벤트로 진행.
        }
      }
    }
  } finally {
    signal?.removeEventListener("abort", onAbort);
  }
}
