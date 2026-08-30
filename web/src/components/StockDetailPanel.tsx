import { useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { StockRow } from "../lib/types";
import {
  BAND_OFFSET,
  buildChart,
  hitTest,
  mapClientToChart,
  type Candle,
  type ChartHit,
  type ChartIn,
} from "../lib/streakChart";
import StockTimeline from "./StockTimeline";
import StreakClosedCard from "./StreakClosedCard";
import ChartLegend, { CLOSED_DESC, TRIGGER_CONDITION, TRIGGER_LABEL } from "./ChartLegend";
import { LatestStatusCell, PerformanceCell, StreakHeader } from "./StockStreakRow";

// viewBox 좌표계(검토 #1): 종횡비 고정. 콘텐츠는 (PAD_X, PAD_Y) 로 평행이동 —
// PAD_X 는 y축 가격 라벨 공간(#143). 마우스 역변환은 mapClientToChart 가 흡수.
const VB_W = 940;
const VB_H = 360;
const PAD_X = 52;
const PAD_Y = 10;
const CHART_W = 872;
const CHART_H = 300;
const X_LABEL_Y = 332; // 하단 띠(306~311) 아래 날짜 라벨 기준선
const TOOLTIP_W = 220;

const CANDLE_UP = "#dc2626";   // 국내 관례: 상승 = 빨강
const CANDLE_DOWN = "#2563eb"; // 하락 = 파랑

const DECISION_LABEL: Record<string, string> = {
  go_now: "go_now (즉시 진입)",
  wait: "wait (대기)",
  abort: "abort (중단)",
};

function ongoingLabel(to: string) {
  return `진행중(~${to} 기준)`;
}

function TooltipBody({ hit, to, candleByDate }: {
  hit: ChartHit; to: string; candleByDate?: Map<string, Candle>;
}) {
  if (hit.kind === "price") {
    const c = candleByDate?.get(hit.date);
    if (c && c[1] != null && c[2] != null && c[3] != null) {
      return (
        <div className="flex flex-col gap-1">
          <span className="num text-data-xs text-muted">{hit.date}</span>
          <div className="num text-data-xs">
            시 {c[1].toLocaleString()} · 고 {c[2].toLocaleString()}
          </div>
          <div className="num text-data-xs">
            저 {c[3].toLocaleString()} · 종 {c[4].toLocaleString()}
          </div>
        </div>
      );
    }
    return (
      <div className="flex items-baseline justify-between">
        <span className="num text-data-xs text-muted">{hit.date}</span>
        <span className="num">종가 {hit.close.toLocaleString()}</span>
      </div>
    );
  }
  if (hit.kind === "closure") {
    return (
      <div className="flex flex-col gap-1">
        <div className="flex items-baseline justify-between">
          <span className="font-semibold">구간 닫힘</span>
          <span className="num text-data-xs text-muted">{hit.date}</span>
        </div>
        <span className="text-data-xs text-muted">{CLOSED_DESC[hit.closed_by]}</span>
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
        {TRIGGER_CONDITION[hit.trigger_type] && (
          <div className="text-data-xs text-muted">{TRIGGER_CONDITION[hit.trigger_type]}</div>
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
      <span className="font-semibold">watch 이상 구간</span>
      <span className="text-data-xs text-muted">
        LLM 분류가 watch 또는 entry(매수 후보)로 유지된 연속 기간입니다.
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

  // 캔들은 행 선택 시에만 fetch(#143) — /stocks 응답 비대화 방지. 실패·로딩 중엔
  // 종가 선으로 폴백하므로 에러를 따로 표시하지 않는다.
  const seriesFrom = row.series[0]?.[0];
  const seriesTo = row.series[row.series.length - 1]?.[0];
  const candlesQuery = useQuery<{ candles: Candle[] }>({
    queryKey: ["review-candles", row.symbol, seriesFrom, seriesTo],
    queryFn: () =>
      api<{ candles: Candle[] }>(
        `/review/stocks/${row.symbol}/candles?from=${seriesFrom}&to=${seriesTo}`),
    enabled: Boolean(seriesFrom && seriesTo),
    staleTime: 5 * 60 * 1000,
  });
  const candles = candlesQuery.data?.candles;

  const chartIn: ChartIn = useMemo(
    () => ({
      width: CHART_W,
      height: CHART_H,
      to,
      series: row.series,
      candles,
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
    [row, to, candles],
  );
  const out = useMemo(() => buildChart(chartIn), [chartIn]);
  const bandY = CHART_H + BAND_OFFSET;

  // 검토 #2: series 0~1점이면 buildChart 가 빈 ChartOut — 핸들러 미부착 플레이스홀더.
  const hasChart = out.pricePoints !== "";

  // 툴팁의 시·고·저·종 조회용 — 날짜 → 캔들.
  const candleByDate = useMemo(
    () => new Map((candles ?? []).map((c) => [c[0], c])),
    [candles],
  );
  // 캔들 몸통 폭 — 일수에 맞춰 좁히되 1.5~8 로 클램프.
  const candleW = out.candleMarks.length
    ? Math.max(1.5, Math.min(8, (CHART_W / out.candleMarks.length) * 0.6))
    : 0;

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
              {/* watch 이상 구간 배경 틴트(#143) — 기간을 차트 위에서 바로 읽게 */}
              {out.bands.map((b, i) => (
                <rect key={`t${i}`} x={b.x1} width={Math.max(b.x2 - b.x1, 1)}
                      y={0} height={CHART_H} fill="#16a34a" opacity={0.08} />
              ))}
              {/* y축: 수평 그리드 + 좌측 가격 라벨 */}
              {out.yTicks.map((t, i) => (
                <g key={`y${i}`}>
                  <line x1={0} x2={CHART_W} y1={t.y} y2={t.y}
                        stroke="#e5e7eb" strokeWidth={1} />
                  <text x={-8} y={t.y + 4} textAnchor="end" fontSize={11}
                        fill="#6b7280" className="num">
                    {Math.round(t.v).toLocaleString()}
                  </text>
                </g>
              ))}
              {out.steps.map((s, i) => (
                <line key={`s${i}`} x1={s.x1} x2={s.x2} y1={s.y} y2={s.y}
                      stroke="#9ca3af" strokeDasharray="6 5" strokeWidth={1.6} />
              ))}
              {/* 구간 닫힘 시점 수직 점선(#143) — 실격=붉은, ignore=회색 */}
              {out.bands.filter((b) => b.closed_by != null).map((b, i) => (
                <line key={`c${i}`} x1={b.x2} x2={b.x2} y1={0} y2={CHART_H}
                      stroke={b.closed_by === "disqualify" ? "#dc2626" : "#6b7280"}
                      strokeDasharray="5 4" strokeWidth={1.3} opacity={0.65} />
              ))}
              {out.candleMarks.length > 0 ? (
                out.candleMarks.map((m, i) => (
                  <g key={`k${i}`}>
                    {m.up == null ? (
                      /* 시·고·저 미백필 → 종가 위치의 짧은 가로 틱으로 폴백 */
                      <line x1={m.x - candleW / 2} x2={m.x + candleW / 2}
                            y1={m.yC} y2={m.yC} stroke="#6b7280" strokeWidth={1.6} />
                    ) : (
                      <>
                        <line x1={m.x} x2={m.x} y1={m.yH!} y2={m.yL!}
                              stroke={m.up ? CANDLE_UP : CANDLE_DOWN} strokeWidth={1} />
                        <rect x={m.x - candleW / 2}
                              y={Math.min(m.yO!, m.yC)}
                              width={candleW}
                              height={Math.max(Math.abs(m.yO! - m.yC), 1)}
                              fill={m.up ? CANDLE_UP : CANDLE_DOWN} />
                      </>
                    )}
                  </g>
                ))
              ) : (
                <polyline points={out.pricePoints} fill="none" stroke="#2563eb" strokeWidth={2} />
              )}
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
              {/* x축: 날짜 라벨(월 경계 우선) */}
              {out.xTicks.map((t, i) => (
                <text key={`x${i}`} x={t.x} y={X_LABEL_Y} textAnchor="middle"
                      fontSize={11} fill="#6b7280" className="num">
                  {t.label}
                </text>
              ))}
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
            <TooltipBody hit={hover.hit} to={to} candleByDate={candleByDate} />
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
