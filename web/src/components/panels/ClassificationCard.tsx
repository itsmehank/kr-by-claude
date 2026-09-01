import { useQuery } from "@tanstack/react-query";
import ReactMarkdown from "react-markdown";
import { api } from "../../lib/api";
import type { Classification, ClassificationHistoryRow } from "../../lib/types";
import { Card } from "./Card";

interface Props {
  ticker: string;
}

const CLASSIFICATION_COLOR: Record<string, string> = {
  entry: "bg-green-100 text-green-800",
  watch: "bg-blue-100 text-blue-800",
  ignore: "bg-gray-200 text-gray-700",
};

// 실격 포함 최신 1건 — 기본 필터(disqualified 제외)에 기대면 최신 상태가 실격인
// 종목이 "이력 없음"으로 오표기된다(#149, 072870 사례).
const ALL_CLASSIFICATIONS =
  "classifications=entry&classifications=watch&classifications=ignore&classifications=disqualified";

export function ClassificationCard({ ticker }: Props) {
  const q = useQuery<Classification[]>({
    queryKey: ["classification-card", ticker],
    queryFn: () =>
      api<Classification[]>(
        `/classifications?ticker=${ticker}&lookback_days=60&limit=1&${ALL_CLASSIFICATIONS}`),
    enabled: !!ticker,
  });
  const latest = q.data?.[0];
  // 최신이 실격이면 직전 유효 분류를 history 로 조회 — /classifications 는 DISTINCT ON
  // (종목당 최신 1건) 이후 필터라 "직전" 행을 돌려줄 수 없다(#149).
  const prevQ = useQuery<ClassificationHistoryRow[]>({
    queryKey: ["classification-card-prev", ticker],
    queryFn: () => api<ClassificationHistoryRow[]>(`/classifications/history/${ticker}`),
    enabled: !!ticker && latest?.classification === "disqualified",
  });

  if (q.isLoading) return <Card title="분류">불러오는 중…</Card>;
  if (q.isError || !q.data || q.data.length === 0) {
    return <Card title="분류">최근 60일 분류 이력 없음</Card>;
  }

  const c = q.data[0];

  if (c.classification === "disqualified") {
    const prev = [...(prevQ.data ?? [])]
      .reverse()
      .find((r) => r.classification !== "disqualified");
    const disqDate = c.analyzed_for_date ?? c.classified_at.slice(0, 10);
    return (
      <Card title="분류">
        <div className="space-y-2 text-data">
          <div className="flex items-center gap-2">
            <span className="px-2 py-0.5 rounded bg-red-50 text-red-700">disqualified</span>
            <span className="num text-data-xs text-muted">{disqDate}</span>
          </div>
          <div className="text-data-xs text-muted">
            실격 — 미너비니 조건 미달 등으로 관찰 자격을 잃은 상태입니다. 조건을 다시
            통과해 재분류되면 이 카드가 갱신됩니다.
          </div>
          {c.reasoning && (
            <div className="text-data-xs text-muted whitespace-pre-wrap">{c.reasoning}</div>
          )}
          {prev && (
            <div className="text-data-xs">
              <span className="caps text-faint mr-2">직전 분류</span>
              {prev.classification}
              {prev.pattern ? ` · ${prev.pattern}` : ""} ·{" "}
              <span className="num">{prev.date}</span>
              {prev.pivot_price != null && (
                <>
                  {" "}· pivot <span className="num">{prev.pivot_price.toLocaleString()}원</span>
                </>
              )}
            </div>
          )}
        </div>
      </Card>
    );
  }
  const baseEnd = c.analyzed_for_date ?? c.classified_at.slice(0, 10);
  const baseStart = c.base_start_date;
  const baseWeeks =
    baseStart && baseEnd
      ? Math.round(
          (new Date(baseEnd).getTime() - new Date(baseStart).getTime()) /
            (7 * 24 * 60 * 60 * 1000),
        )
      : null;

  return (
    <Card title="분류">
      <div className="space-y-2 text-data">
        <div className="flex items-center gap-2">
          <span
            className={`px-2 py-0.5 rounded ${
              CLASSIFICATION_COLOR[c.classification] ?? "bg-gray-100"
            }`}
          >
            {c.classification}
          </span>
          {c.pattern && <span className="text-muted">{c.pattern}</span>}
        </div>
        <div>
          <span className="caps text-faint">Base 기간</span>{" "}
          {baseStart
            ? `${baseStart} ~ ${baseEnd}${baseWeeks ? ` (${baseWeeks}주)` : ""}`
            : "—"}
        </div>
        <div>
          <span className="caps text-faint">Base 가격대</span>{" "}
          {c.base_low != null && c.base_high != null
            ? `${c.base_low.toLocaleString()} ~ ${c.base_high.toLocaleString()}원`
            : "—"}
        </div>
        <div>
          <span className="caps text-faint">Base 깊이</span>{" "}
          {c.base_depth_pct != null ? `${c.base_depth_pct.toFixed(2)}%` : "—"}
        </div>
        <div>
          <span className="caps text-faint">Pivot</span>{" "}
          {c.pivot_price != null ? `${c.pivot_price.toLocaleString()}원` : "—"}
          {c.pivot_basis && <span className="text-faint"> ({c.pivot_basis})</span>}
        </div>
        {c.risk_flags.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {c.risk_flags.map((f) => (
              <span
                key={f}
                className="px-2 py-0.5 rounded bg-red-50 text-red-700 text-data-xs"
              >
                {f}
              </span>
            ))}
          </div>
        )}
        {c.reasoning && (
          <div className="prose prose-sm max-w-none text-muted">
            <ReactMarkdown>{c.reasoning}</ReactMarkdown>
          </div>
        )}
      </div>
    </Card>
  );
}
