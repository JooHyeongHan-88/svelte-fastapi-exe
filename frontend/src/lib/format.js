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

export function autoTitle(firstUserMessage) {
  const cleaned = (firstUserMessage ?? "").trim().replace(/\s+/g, " ");
  if (!cleaned) return "새 대화";
  if (cleaned.length <= MAX_TITLE_LEN) return cleaned;
  return cleaned.slice(0, MAX_TITLE_LEN) + "…";
}
