// 시간/문자열 표현 헬퍼.

const MS_DAY = 24 * 60 * 60 * 1000;
const MAX_TITLE_LEN = 30;

export function relativeTimeBucket(updatedAt) {
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const diff = startOfToday - updatedAt;

  if (updatedAt >= startOfToday) return "오늘";
  if (diff < MS_DAY) return "어제";
  if (diff < 7 * MS_DAY) return "지난 7일";
  return "이전";
}

export const BUCKET_ORDER = ["오늘", "어제", "지난 7일", "이전"];

// 메시지 hover footer 용 절대시간 포맷. 같은 날이면 HH:MM, 어제는 "어제 HH:MM",
// 그 이전은 "M월 D일 HH:MM". relativeTimeBucket 과 달리 분 단위까지 표시한다.
export function formatAbsoluteTime(ms) {
  const d = new Date(ms);
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  const isYesterday = d.toDateString() === yesterday.toDateString();

  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const hm = `${hh}:${mm}`;

  if (sameDay) return hm;
  if (isYesterday) return `어제 ${hm}`;
  return `${d.getMonth() + 1}월 ${d.getDate()}일 ${hm}`;
}

export function autoTitle(firstUserMessage) {
  const cleaned = (firstUserMessage ?? "").trim().replace(/\s+/g, " ");
  if (!cleaned) return "새 대화";
  if (cleaned.length <= MAX_TITLE_LEN) return cleaned;
  return cleaned.slice(0, MAX_TITLE_LEN) + "…";
}
