import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { ClassificationLabel, ClassificationHistoryRow } from "../../lib/types";
import { groupHistorySegments } from "../../lib/historySegments";
import { Card } from "./Card";

// 칩 색 — disqualified 는 차트 밴드 "미통과/탈락"(빨강)과 통일 (스펙 §3).
// Record<ClassificationLabel, ...> 선언: 분류 값이 늘면 컴파일러가 칩 색 누락을 강제(SSOT).
// 조회는 string 인덱싱 + 회색 fallback (미지 값 렌더 크래시 금지 — 스펙 §6).
const TONES: Record<ClassificationLabel, string> = {
  entry: "bg-success-soft text-success",
  watch: "bg-tint-blue text-accent",
  ignore: "bg-tint-stone text-muted",
  disqualified: "bg-rose-50 text-danger",
};

function Chip({ classification }: { classification: string }) {
  const tone = TONES[classification as ClassificationLabel] ?? "bg-tint-stone text-muted";
  return <span className={`chip ${tone}`}>{classification}</span>;
}

interface Props {
  rows: ClassificationHistoryRow[] | undefined; // ChartPage 의 classHistoryQ.data 재사용
  loading: boolean;
}

export function ClassificationHistoryTable({ rows, loading }: Props) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  if (loading) return <Card title="분류 이력">불러오는 중…</Card>;
  const segments = groupHistorySegments(rows ?? []);
  if (segments.length === 0) {
    return <Card title="분류 이력">이 기간 분류 이력이 없습니다.</Card>;
  }

  function toggle(key: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  return (
    <Card title={`분류 이력 (변화점 ${segments.length}건)`}>
      <table className="w-full text-data">
        <thead className="text-faint">
          <tr>
            <th className="text-left py-1.5 pr-3">기간</th>
            <th className="text-left py-1.5 pr-3">분류</th>
            <th className="text-left py-1.5 pr-3">패턴</th>
            <th className="text-right py-1.5 pr-4">확신도</th>
            <th className="text-left py-1.5">분석</th>
          </tr>
        </thead>
        <tbody>
          {segments.map((s) => {
            const key = `${s.classification}-${s.startDate}`;
            const open = expanded.has(key);
            return (
              <FragmentRow
                key={key}
                segment={s}
                open={open}
                onToggle={() => toggle(key)}
              />
            );
          })}
        </tbody>
      </table>
    </Card>
  );
}

function FragmentRow({
  segment: s,
  open,
  onToggle,
}: {
  segment: ReturnType<typeof groupHistorySegments>[number];
  open: boolean;
  onToggle: () => void;
}) {
  // 창-잘림 구간: 시작일을 전환일로 단정하지 않음 (스펙 §4)
  const period = s.truncatedStart
    ? `기간 이전부터 ~ ${s.endDate}`
    : s.startDate === s.endDate
    ? s.startDate
    : `${s.startDate} ~ ${s.endDate}`;
  return (
    <>
      <tr
        onClick={onToggle}
        className="border-t border-hairline cursor-pointer hover:bg-cream/60"
      >
        <td className="py-2 pr-3 num text-data-xs whitespace-nowrap">
          <span className="inline-flex items-center gap-1 text-faint">
            {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
          </span>{" "}
          {period}
        </td>
        <td className="py-2 pr-3"><Chip classification={s.classification} /></td>
        <td className="py-2 pr-3 text-muted">{s.pattern ?? "—"}</td>
        <td className="py-2 pr-4 num text-right">
          {s.confidence != null ? s.confidence.toFixed(2) : "—"}
        </td>
        <td className="py-2 text-data-xs text-faint">{s.weeks.length}주 분석</td>
      </tr>
      {open && (
        <tr className="bg-cream/40">
          <td colSpan={5} className="px-4 py-3">
            <div className="text-data-xs leading-relaxed mb-2">
              <span className="caps text-faint mr-2">
                사유{s.truncatedStart && " (기간 내 첫 기록 기준)"}
              </span>
              {s.reasoning ?? "사유 기록 없음"}
            </div>
            <table className="w-full text-data-xs">
              <thead className="text-faint">
                <tr>
                  <th className="text-left py-1 pr-3">날짜</th>
                  <th className="text-left py-1 pr-3">분류</th>
                  <th className="text-left py-1 pr-3">패턴</th>
                  <th className="text-right py-1 pr-4">conf</th>
                  <th className="text-left py-1">출처</th>
                </tr>
              </thead>
              <tbody>
                {[...s.weeks].reverse().map((w) => (
                  <tr key={w.date} className="border-t border-hairline/60">
                    <td className="py-1 pr-3 num">{w.date}</td>
                    <td className="py-1 pr-3"><Chip classification={w.classification} /></td>
                    <td className="py-1 pr-3 text-muted">{w.pattern ?? "—"}</td>
                    <td className="py-1 pr-4 num text-right">
                      {w.confidence != null ? w.confidence.toFixed(2) : "—"}
                    </td>
                    <td className="py-1 text-faint">{w.source}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </td>
        </tr>
      )}
    </>
  );
}
