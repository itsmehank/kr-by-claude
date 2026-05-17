import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * 상대 시간 한국어 표기.
 * 예: "방금 전", "5분 전", "3시간 전", "2일 전"
 */
export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "방금 전";
  if (mins < 60) return `${mins}분 전`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}시간 전`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}일 전`;
  const months = Math.floor(days / 30);
  return `${months}개월 전`;
}

/**
 * 마지막 갱신 시간을 status tone 으로 변환.
 * 1시간 이내: success, 1일 이내: warning, 그 이상: danger.
 */
export function stalenessLevel(
  iso: string | null | undefined
): "fresh" | "stale" | "old" {
  if (!iso) return "old";
  const diff = Date.now() - new Date(iso).getTime();
  const hours = diff / (60 * 60_000);
  if (hours < 24) return "fresh";
  if (hours < 24 * 7) return "stale";
  return "old";
}
