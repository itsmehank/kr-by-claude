import type { ReactNode } from "react";

interface Props {
  label: string;       // 예: "Trend Template 8 조건 모두 보기"
  count?: number;       // 옵션 — 라벨 옆 카운트 chip
  variant?: "default" | "subtle"; // subtle = 더 작은 톤
  children: ReactNode;
}

/**
 * 'X 항목 모두 보기 ▼' 공통 fold 래퍼.
 * 기존 안내 박스의 <details> 패턴을 카드 내부용으로 축소.
 */
export function ListFold({ label, count, variant = "default", children }: Props) {
  const summaryBg = variant === "subtle"
    ? "bg-cream hover:bg-tint-stone"
    : "bg-tint-stone hover:bg-cream";
  return (
    <details className="mt-2 group">
      <summary className={`cursor-pointer select-none px-3 py-2 ${summaryBg} border border-hairline rounded-lg text-data-xs text-ink font-semibold transition-colors list-none flex items-center justify-between`}>
        <span>
          {label}
          {count != null && (
            <span className="ml-2 num text-faint font-normal">({count})</span>
          )}
        </span>
        <span className="text-faint font-normal group-open:hidden">▼</span>
        <span className="text-faint font-normal hidden group-open:inline">▲</span>
      </summary>
      <div className="mt-2 px-3 py-3 bg-cream border border-hairline rounded-lg text-data-xs text-muted leading-relaxed">
        {children}
      </div>
    </details>
  );
}
