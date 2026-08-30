import { Fragment, memo, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { Streak, StockLatest, StockRow } from "../lib/types";
import StreakChart from "./StreakChart";
import StockTimeline from "./StockTimeline";
import StreakClosedCard from "./StreakClosedCard";
import { BACKFILL_TOOLTIP } from "./SourceChip";

const pct = (v: number | null) =>
  v == null ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;

const CLOSED_BY_LABEL: Record<string, string> = {
  ignore: "ignore",
  disqualify: "실격",
};

const STAGE_LABEL: Record<string, string> = {
  breakout: "breakout",
  staging: "staging",
  watching: "watching",
  base_forming: "base_forming",
};

/** 종목 최근 구간 상태 pill(스펙 §5) — 진행중/닫힘·사유 + 보조 표식(배지). */
export function LatestStatusCell({ latest }: { latest: StockLatest }) {
  const isOpen = latest.status === "open";
  const closedLabel = latest.closed_by ? CLOSED_BY_LABEL[latest.closed_by] ?? latest.closed_by : null;
  const tone = isOpen
    ? { bg: "bg-tint-blue", text: "text-accent", dot: "bg-accent" }
    : { bg: "bg-tint-stone", text: "text-muted", dot: "bg-gray-400" };
  return (
    <div className="flex flex-col gap-1">
      <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded w-fit ${tone.bg} ${tone.text}`}>
        <span className={`h-1.5 w-1.5 rounded-full ${tone.dot}`} />
        {isOpen ? "진행중" : `닫힘${closedLabel ? ` · ${closedLabel}` : ""}`}
      </span>
      <div className="flex items-center gap-1 flex-wrap">
        {latest.censored && (
          <span
            className="chip bg-amber-soft text-amber text-data-xs"
            title="구간의 시작이 이 화면의 관측 시작일과 맞물려 있어, 그 이전에도 watch 이상이었는지 알 수 없음"
          >
            이전 이력 불명
          </span>
        )}
        {latest.backfilled && (
          <span className="chip bg-tint-stone text-muted text-data-xs" title={BACKFILL_TOOLTIP}>
            백필
          </span>
        )}
      </div>
    </div>
  );
}

/** 성과 셀(스펙 §2·§5) — stage 별 표시. */
export function PerformanceCell({ latest }: { latest: StockLatest }) {
  if (latest.stage === "breakout") {
    return (
      <span className="num">
        T+5 {pct(latest.t5_pct)} · T+20 {pct(latest.t20_pct)}
      </span>
    );
  }
  if (latest.stage === "staging" || latest.stage === "watching") {
    return (
      <span className="num">
        최고 {pct(latest.max_reach_pct)}
        {latest.corp_action_flag && (
          <span
            className="ml-1.5 chip bg-amber-soft text-amber text-data-xs"
            title="구간 내 기업행위 발생 — 가격 왜곡 가능"
          >
            ⚠ 기업행위
          </span>
        )}
      </span>
    );
  }
  return <span className="text-muted">베이스 형성 중</span>;
}

function latestStreak(row: StockRow): Streak | undefined {
  return row.streaks[row.streaks.length - 1];
}

/** 최근 pivot — 최근 구간의 마지막 pivot 값(스펙 §5 "최근 pivot" 컬럼). */
function recentPivot(row: StockRow): number | null {
  const streak = latestStreak(row);
  if (!streak) return null;
  for (let i = streak.analyses.length - 1; i >= 0; i--) {
    const p = streak.analyses[i].pivot_price;
    if (p != null) return p;
  }
  return null;
}

export function StreakHeader({ streak }: { streak: Streak }) {
  const closedLabel = streak.closed_by ? CLOSED_BY_LABEL[streak.closed_by] ?? streak.closed_by : null;
  return (
    <div className="flex items-center gap-2 flex-wrap text-data-xs text-muted mb-1.5">
      <span className="num">
        {streak.start} ~ {streak.end ?? "진행중"}
      </span>
      {closedLabel && <span className="chip bg-tint-stone text-muted text-data-xs">{closedLabel}</span>}
      <span className="chip bg-tint-violet text-muted text-data-xs">{STAGE_LABEL[streak.stage] ?? streak.stage}</span>
      {streak.censored && (
        <span
          className="chip bg-amber-soft text-amber text-data-xs"
          title="구간 시작이 관측 시작일과 맞물림 — 그 이전 이력은 알 수 없음"
        >
          이전 이력 불명
        </span>
      )}
      {streak.backfilled && (
        <span className="chip bg-tint-stone text-muted text-data-xs" title={BACKFILL_TOOLTIP}>
          백필
        </span>
      )}
    </div>
  );
}

function StockStreakRow({
  row,
  to,
  selected,
  onSelect,
}: {
  row: StockRow;
  to: string;
  selected: boolean;
  onSelect: (symbol: string) => void;
}) {
  const navigate = useNavigate();
  const [isOpen, setIsOpen] = useState(false);

  const streaks = useMemo(
    () =>
      row.streaks.map((s) => ({
        start: s.start,
        end: s.end,
        closed_by: (s.closed_by as "ignore" | "disqualify" | null) ?? null,
        censored: s.censored,
        backfilled: s.backfilled,
        has_gap: s.has_gap,
      })),
    [row],
  );
  const triggers = useMemo(
    () =>
      row.streaks.flatMap((s) =>
        s.analyses.flatMap((a) => a.triggers.map((t) => ({ d: t.d, trigger_type: t.trigger_type }))),
      ),
    [row],
  );

  return (
    <Fragment>
      {/* 행 클릭 = 상세 패널 선택. 펼침은 chevron 버튼 전용(설계 v3 §2). */}
      <tr
        onClick={() => onSelect(row.symbol)}
        className="border-t border-hairline align-top hover:bg-paper/40 cursor-pointer"
      >
        {/* 선택 표시는 배경이 아닌 좌측 인디케이터 — hover 배경과 축 분리(검토 #16) */}
        <td className={`px-3 py-1.5 border-l-2 ${selected ? "border-l-accent" : "border-l-transparent"}`}>
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              aria-label={isOpen ? "구간 타임라인 접기" : "구간 타임라인 펼치기"}
              className="text-faint shrink-0 hover:text-ink"
              onClick={(e) => {
                e.stopPropagation();
                setIsOpen((v) => !v);
              }}
            >
              {isOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            </button>
            <span
              className="font-semibold hover:underline"
              onClick={(e) => {
                e.stopPropagation();
                navigate(`/chart/${row.symbol}`);
              }}
            >
              {row.symbol}
            </span>
            <span className="text-muted">{row.name}</span>
          </div>
        </td>
        <td className="px-3 py-1.5">
          <LatestStatusCell latest={row.latest} />
        </td>
        <td className="px-3 py-1.5 text-right num">{row.latest.streak_count}</td>
        <td className="px-3 py-1.5 text-right num">
          {recentPivot(row) != null ? recentPivot(row)!.toLocaleString() : "—"}
        </td>
        <td className="px-3 py-1.5">
          <PerformanceCell latest={row.latest} />
        </td>
        <td className="px-3 py-1.5">
          <StreakChart to={to} series={row.series} pivotSteps={row.pivot_steps} streaks={streaks} triggers={triggers} />
        </td>
      </tr>
      {isOpen && (
        <tr className="border-t border-hairline bg-cream/50">
          <td colSpan={6} className="px-6 py-3">
            <div className="flex flex-col gap-4">
              {row.streaks.map((streak, i) => (
                <div key={`${row.symbol}-${streak.start}-${i}`} className="flex flex-col gap-2">
                  <StreakHeader streak={streak} />
                  <StockTimeline rows={streak.analyses} />
                  <StreakClosedCard streak={streak} />
                </div>
              ))}
            </div>
          </td>
        </tr>
      )}
    </Fragment>
  );
}

// memo: 선택 변경 시 다른 행(최대 500개)의 buildChart 재실행을 막는다(검토 #7).
export default memo(StockStreakRow);
