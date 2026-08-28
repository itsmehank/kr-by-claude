import { useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { StockRow } from "../lib/types";
import {
  BAND_OFFSET,
  buildChart,
  hitTest,
  mapClientToChart,
  type ChartHit,
  type ChartIn,
} from "../lib/streakChart";
import StockTimeline from "./StockTimeline";
import StreakClosedCard from "./StreakClosedCard";
import ChartLegend, { CLOSED_DESC } from "./ChartLegend";
import { LatestStatusCell, PerformanceCell, StreakHeader } from "./StockStreakRow";

// viewBox 좌표계(검토 #1): 종횡비 고정 + 단일 배율. 콘텐츠는 (PAD_X, PAD_Y) 로 평행이동.
const VB_W = 940;
const VB_H = 360;
const PAD_X = 20;
const PAD_Y = 10;
const CHART_W = 900;
const CHART_H = 300;
const TOOLTIP_W = 220;

const TRIGGER_LABEL: Record<string, string> = {
  breakout: "돌파",
  breakout_from_watch: "돌파",
  promotion: "승격",
  invalidation: "무효화",
};

// 트리거 유형별 한 줄 설명 — trigger_gate.py 의 발동 조건을 사람 말로 풀어쓴 것.
const TRIGGER_DESC: Record<string, string> = {
  breakout: "종가가 pivot(돌파 기준가) 위로 마감했습니다.",
  breakout_from_watch: "watch 종목의 종가가 pivot(돌파 기준가) 위로 처음 마감했습니다.",
  promotion: "watch 종목이 pivot 에 근접해 entry 승격을 검토한 날입니다.",
  invalidation: "손절선 이탈·50일선 아래 마감 — 베이스 훼손이 의심됩니다.",
};

const DECISION_LABEL: Record<string, string> = {
  go_now: "go_now (즉시 진입)",
  wait: "wait (대기)",
  abort: "abort (중단)",
};

function ongoingLabel(to: string) {
  return `진행중(~${to} 기준)`;
}

function TooltipBody({ hit, to }: { hit: ChartHit; to: string }) {
  if (hit.kind === "price") {
    return (
      <div className="flex items-baseline justify-between">
        <span className="num text-data-xs text-muted">{hit.date}</span>
        <span className="num">종가 {hit.close.toLocaleString()}</span>
      </div>
    );
  }
  if (hit.kind === "dot") {
    return (
      <div className="flex flex-col gap-1">
        <div className="flex items-baseline justify-between">
          <span className="font-semibold">
            트리거 · {TRIGGER_LABEL[hit.trigger_type] ?? hit.trigger_type}
          </span>
          <span className="num text-data-xs text-muted">{hit.date}</span>
        </div>
        {TRIGGER_DESC[hit.trigger_type] && (
          <div className="text-data-xs text-muted">{TRIGGER_DESC[hit.trigger_type]}</div>
        )}
        <div className="text-data-xs">
          판정 {hit.decision != null ? DECISION_LABEL[hit.decision] ?? hit.decision : "—"}
        </div>
        <div className="num text-data-xs">
          종가 {hit.close != null ? hit.close.toLocaleString() : "—"} · pivot{" "}
          {hit.pivot_price != null ? hit.pivot_price.toLocaleString() : "—"}
        </div>
      </div>
    );
  }
  if (hit.kind === "step") {
    return (
      <div className="flex flex-col gap-1">
        <span className="font-semibold num">
          pivot(돌파 기준가) {hit.pivot.toLocaleString()}
        </span>
        <span className="num text-data-xs text-muted">
          {hit.from} ~ {hit.to ?? ongoingLabel(to)}
        </span>
        <span className="text-data-xs text-muted">
          종가가 이 가격 위로 마감하면 돌파로 봅니다.
        </span>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-1">
      <span className="font-semibold">관찰 묶음</span>
      <span className="text-data-xs text-muted">
        같은 셋업을 이어서 관찰한 분석 구간입니다.
      </span>
      <span className="num text-data-xs text-muted">
        {hit.start} ~ {hit.end ?? ongoingLabel(to)}
      </span>
      <span className="text-data-xs text-muted">
        {hit.closed_by == null ? ongoingLabel(to) : CLOSED_DESC[hit.closed_by]}
      </span>
    </div>
  );
}

/** 선택 종목의 큰 차트 + 차트 읽기 도움 데이터(설계 v3 §3). */
export default function StockDetailPanel({ row, to }: { row: StockRow; to: string }) {
  const navigate = useNavigate();
  const wrapRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<{ hit: ChartHit; left: number; top: number; mx: number } | null>(null);

  const chartIn: ChartIn = useMemo(
    () => ({
      width: CHART_W,
      height: CHART_H,
      to,
      series: row.series,
      pivotSteps: row.pivot_steps,
      streaks: row.streaks.map((s) => ({
        start: s.start,
        end: s.end,
        closed_by: (s.closed_by as "ignore" | "disqualify" | null) ?? null,
        censored: s.censored,
        backfilled: s.backfilled,
        has_gap: s.has_gap,
      })),
      triggers: row.streaks.flatMap((s) =>
        s.analyses.flatMap((a) =>
          a.triggers.map((t) => ({
            d: t.d,
            trigger_type: t.trigger_type,
            decision: t.decision,
            close: t.close,
            pivot_price: t.pivot_price,
          })),
        ),
      ),
    }),
    [row, to],
  );
  const out = useMemo(() => buildChart(chartIn), [chartIn]);
  const bandY = CHART_H + BAND_OFFSET;

  // 검토 #2: series 0~1점이면 buildChart 가 빈 ChartOut — 핸들러 미부착 플레이스홀더.
  const hasChart = out.pricePoints !== "";

  // y축 라벨용 min/max — computeScale 과 동일 정의(series ∪ pivot).
  const yDomain = useMemo(() => {
    if (!hasChart) return null;
    const values = row.series.map(([, v]) => v);
    const pivots = row.pivot_steps.map(([, , p]) => p);
    return {
      min: Math.min(...values, ...(pivots.length ? pivots : [Infinity])),
      max: Math.max(...values, ...(pivots.length ? pivots : [-Infinity])),
    };
  }, [hasChart, row]);

  function onMouseMove(e: React.MouseEvent) {
    const svg = svgRef.current;
    const wrap = wrapRef.current;
    if (!svg || !wrap) return;
    const rect = svg.getBoundingClientRect();
    // 범례가 세로 공간을 나눠 쓰면서 flex 가 svg 를 누를 수 있다 — letterbox 대응 역변환.
    const { mx, my } = mapClientToChart(
      { vbW: VB_W, vbH: VB_H, padX: PAD_X, padY: PAD_Y }, rect, e.clientX, e.clientY);
    const hit = hitTest(chartIn, mx, my);
    if (!hit) {
      setHover(null);
      return;
    }
    const wrapRect = wrap.getBoundingClientRect();
    const px = e.clientX - wrapRect.left;
    const py = e.clientY - wrapRect.top;
    const left = px + 12 + TOOLTIP_W > wrapRect.width ? px - TOOLTIP_W - 12 : px + 12;
    setHover({ hit, left, top: Math.max(8, py - 64), mx });
  }

  // 크로스헤어는 hit ≠ null 이면 항상 — 가장 가까운 거래일 인덱스에 스냅(검토 #12).
  const crossX = useMemo(() => {
    if (!hover || !hasChart) return null;
    const n = row.series.length;
    const i = Math.min(n - 1, Math.max(0, Math.round((hover.mx / CHART_W) * (n - 1))));
    return (i / (n - 1)) * CHART_W;
  }, [hover, hasChart, row]);

  return (
    <div className="mb-6 rounded-xl border border-hairline bg-cream/70 p-4 flex gap-4 h-[380px]">
      <div
        ref={wrapRef}
        className="relative flex-[2] min-w-0 flex flex-col justify-center gap-2"
        onMouseMove={hasChart ? onMouseMove : undefined}
        onMouseLeave={hasChart ? () => setHover(null) : undefined}
      >
        {hasChart ? (
          <svg
            ref={svgRef}
            viewBox={`0 0 ${VB_W} ${VB_H}`}
            style={{ width: "100%", height: "auto" }}
            className="block"
          >
            <g transform={`translate(${PAD_X},${PAD_Y})`}>
              {out.steps.map((s, i) => (
                <line key={`s${i}`} x1={s.x1} x2={s.x2} y1={s.y} y2={s.y}
                      stroke="#9ca3af" strokeDasharray="6 5" strokeWidth={1.6} />
              ))}
              <polyline points={out.pricePoints} fill="none" stroke="#2563eb" strokeWidth={2} />
              {crossX != null && (
                <line x1={crossX} x2={crossX} y1={0} y2={bandY + 8}
                      stroke="#9ca3af" strokeWidth={1} strokeDasharray="3 3" />
              )}
              {out.bands.map((b, i) => (
                <g key={`b${i}`}>
                  <line x1={b.x1} x2={b.x2} y1={bandY} y2={bandY} stroke="#16a34a"
                        strokeWidth={6} strokeDasharray={b.dashed ? "8 6" : undefined} />
                  {b.censored && (
                    <text x={b.x1} y={bandY + 5} fontSize={12} fill="#b45309">⟵</text>
                  )}
                  {b.marker && (
                    <text x={Math.min(b.x2, CHART_W - 10)} y={bandY + 5} fontSize={13}
                          fill={b.marker === "x" ? "#dc2626" : "#6b7280"}>
                      {b.marker === "x" ? "✕" : "○"}
                    </text>
                  )}
                </g>
              ))}
              {out.dots.map((d, i) => (
                <circle key={`d${i}`} cx={d.x} cy={d.y} r={4.5} fill={d.color} />
              ))}
              {yDomain && (
                <g fill="#6b7280" fontSize={11} className="num">
                  <text x={4} y={12}>{yDomain.max.toLocaleString()}</text>
                  <text x={4} y={CHART_H - 4}>{yDomain.min.toLocaleString()}</text>
                </g>
              )}
            </g>
          </svg>
        ) : (
          <div className="w-full text-center text-muted text-data-xs">
            가격 계열 없음 — 조회 기간에 표시할 시세가 없습니다
          </div>
        )}
        {hasChart && <ChartLegend />}
        {hover && (
          <div
            className="absolute pointer-events-none bg-paper border border-hairline shadow-bento-hover rounded-xl px-3 py-2.5 z-10 w-[220px]"
            style={{ left: hover.left, top: hover.top }}
          >
            <TooltipBody hit={hover.hit} to={to} />
          </div>
        )}
      </div>

      <div className="flex-1 min-w-0 overflow-y-auto flex flex-col gap-3 pr-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span
            className="font-semibold hover:underline cursor-pointer"
            onClick={() => navigate(`/chart/${row.symbol}`)}
          >
            {row.symbol}
          </span>
          <span className="text-muted">{row.name}</span>
          <span className="chip bg-tint-stone text-muted text-data-xs">{row.market}</span>
        </div>
        <div className="flex items-center gap-4 flex-wrap">
          <LatestStatusCell latest={row.latest} />
          <PerformanceCell latest={row.latest} />
        </div>
        {row.streaks.map((streak, i) => (
          <div key={`${row.symbol}-${streak.start}-${i}`} className="flex flex-col gap-2">
            <StreakHeader streak={streak} />
            <StockTimeline rows={streak.analyses} />
            <StreakClosedCard streak={streak} />
          </div>
        ))}
      </div>
    </div>
  );
}
