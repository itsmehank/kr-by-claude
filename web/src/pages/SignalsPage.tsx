import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  Zap,
  AlertTriangle,
  Download,
  ExternalLink,
} from "lucide-react";
import { api, apiUrl } from "../lib/api";
import type { Signal } from "../lib/types";
import { Skeleton } from "../components/ui/Skeleton";
import { relativeTime } from "../lib/utils";

// ── Helpers ────────────────────────────────────────────────────────────────

type DayFilter = 1 | 3 | 5 | 14;
const DAY_OPTIONS: { value: DayFilter; label: string }[] = [
  { value: 1, label: "1일" },
  { value: 3, label: "3일" },
  { value: 5, label: "5일" },
  { value: 14, label: "14일" },
];

function fmtPrice(n: number | null | undefined): string {
  if (n == null) return "—";
  return `₩${n.toLocaleString("ko-KR")}`;
}

function fmtPct(n: number | null | undefined): string {
  if (n == null) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(2)}%`;
}

function fmtRR(n: number | null | undefined): string {
  if (n == null) return "—";
  return `${n.toFixed(2)}`;
}

function pctClass(n: number | null | undefined): string {
  if (n == null) return "text-muted";
  if (n > 0) return "text-success";
  if (n < 0) return "text-danger";
  return "text-muted";
}

function entryModeChip(mode: string | null) {
  if (!mode) return null;
  const colorMap: Record<string, string> = {
    breakout: "bg-tint-blue text-accent",
    pivot: "bg-tint-blue text-accent",
    pullback: "bg-tint-amber text-amber",
    base: "bg-tint-mint text-success",
  };
  const cls = colorMap[mode.toLowerCase()] ?? "bg-tint-stone text-muted";
  return (
    <span className={`chip ${cls}`}>{mode}</span>
  );
}

function marketChip(market: string | null) {
  if (!market) return null;
  const cls =
    market.toUpperCase() === "KOSPI"
      ? "bg-tint-blue text-accent"
      : "bg-tint-amber text-amber";
  return <span className={`chip ${cls}`}>{market}</span>;
}

function sectorChip(sector: string | null) {
  if (!sector) return null;
  return <span className="chip bg-tint-stone text-muted">{sector}</span>;
}

// ── Signal Card ─────────────────────────────────────────────────────────────

interface SignalCardProps {
  signal: Signal;
}

function SignalCard({ signal }: SignalCardProps) {
  const navigate = useNavigate();

  return (
    <div className="bento p-6 space-y-5">
      {/* Card Header */}
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3 min-w-0">
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <span className="num text-data-lg font-bold text-ink">
                {signal.symbol}
              </span>
              {signal.name && (
                <span className="text-data text-muted font-medium truncate">
                  {signal.name}
                </span>
              )}
            </div>
            <div className="flex items-center gap-1.5 mt-1.5 flex-wrap">
              {marketChip(signal.market)}
              {sectorChip(signal.sector)}
              {entryModeChip(signal.entry_mode)}
            </div>
          </div>
        </div>
        <div className="shrink-0 text-right">
          <div className="text-data-xs text-faint num">
            {relativeTime(signal.signal_at)}
          </div>
          <div className="text-data-xs text-faint mt-0.5">
            {signal.signal_at.slice(0, 10)}
          </div>
        </div>
      </div>

      {/* Main Grid */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
        {/* 진입가 */}
        <div className="bento-tint-blue p-4 rounded-xl">
          <div className="caps text-faint mb-1.5">진입가</div>
          <div className="num text-data-lg font-bold text-ink">
            {fmtPrice(signal.entry_price)}
          </div>
          {signal.trigger_price != null && (
            <div className="num text-data-xs text-muted mt-1">
              트리거 {fmtPrice(signal.trigger_price)}
            </div>
          )}
        </div>

        {/* 손절가 */}
        <div className="bento-tint-rose p-4 rounded-xl">
          <div className="caps text-faint mb-1.5">손절가</div>
          <div className="num text-data-lg font-bold text-danger">
            {fmtPrice(signal.stop_loss)}
          </div>
          <div className="flex gap-2 mt-1 flex-wrap">
            {signal.stop_loss_pct_from_pivot != null && (
              <span className="num text-data-xs text-muted">
                pivot {fmtPct(signal.stop_loss_pct_from_pivot)}
              </span>
            )}
            {signal.stop_loss_pct_from_current_price != null && (
              <span className="num text-data-xs text-muted">
                현재 {fmtPct(signal.stop_loss_pct_from_current_price)}
              </span>
            )}
          </div>
        </div>

        {/* 목표가 */}
        <div className="bento-tint-mint p-4 rounded-xl">
          <div className="caps text-faint mb-1.5">목표가</div>
          <div className="num text-data-lg font-bold text-success">
            {fmtPrice(signal.expected_target_price)}
          </div>
          {signal.expected_target_pct != null && (
            <div className={`num text-data-xs mt-1 ${pctClass(signal.expected_target_pct)}`}>
              {fmtPct(signal.expected_target_pct)}
            </div>
          )}
        </div>

        {/* R:R */}
        <div className="p-4 rounded-xl bg-tint-stone">
          <div className="caps text-faint mb-1.5">리스크·리워드</div>
          <div className="num text-data-lg font-bold text-ink">
            {fmtRR(signal.risk_reward_ratio)}
          </div>
          <div className="text-data-xs text-faint mt-1">R:R ratio</div>
        </div>

        {/* 포지션 사이즈 */}
        {signal.position_size_pct != null && (
          <div className="p-4 rounded-xl bg-tint-stone">
            <div className="caps text-faint mb-1.5">사이즈</div>
            <div className="num text-data-lg font-bold text-ink">
              {signal.position_size_pct.toFixed(1)}%
            </div>
            <div className="text-data-xs text-faint mt-1">포지션 비중</div>
          </div>
        )}
      </div>

      {/* Warnings */}
      {signal.known_warnings.length > 0 && (
        <div>
          <div className="flex items-center gap-1.5 mb-2">
            <AlertTriangle size={13} className="text-amber shrink-0" />
            <span className="caps text-amber">주의사항</span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {signal.known_warnings.map((w, i) => (
              <span key={i} className="chip bg-amber-soft text-amber text-data-xs">
                {w}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Notes */}
      {signal.notes && (
        <div className="text-data text-muted leading-relaxed border-t border-hairline pt-4">
          {signal.notes}
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center gap-2 pt-1 border-t border-hairline">
        <button
          onClick={() => navigate(`/chart/${signal.symbol}`)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-tint-blue text-accent text-data-xs font-semibold hover:bg-accent hover:text-white transition-colors"
        >
          <ExternalLink size={13} />
          차트 보기
        </button>
        <a
          href={apiUrl(`/prompts/${signal.symbol}.zip`)}
          download
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-tint-stone text-muted text-data-xs font-semibold hover:bg-paper hover:text-ink transition-colors"
        >
          <Download size={13} />
          ZIP 다운로드
        </a>
      </div>
    </div>
  );
}

// ── Skeleton Card ───────────────────────────────────────────────────────────

function SignalCardSkeleton() {
  return (
    <div className="bento p-6 space-y-5">
      <div className="flex items-start justify-between">
        <div className="space-y-2">
          <Skeleton height={24} width={120} />
          <Skeleton height={16} width={200} />
        </div>
        <Skeleton height={16} width={60} />
      </div>
      <div className="grid grid-cols-3 gap-4">
        {[0, 1, 2].map((i) => (
          <div key={i} className="rounded-xl bg-tint-stone p-4 space-y-2">
            <Skeleton height={12} width={50} />
            <Skeleton height={22} width={80} />
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────

export default function SignalsPage() {
  const [days, setDays] = useState<DayFilter>(5);

  const { data, isLoading, isError } = useQuery<Signal[]>({
    queryKey: ["signals", days],
    queryFn: () => api<Signal[]>(`/signals?days=${days}`),
  });

  const signals = data ?? [];

  return (
    <div className="px-10 py-10 max-w-[1240px] mx-auto">
      {/* Header */}
      <header className="flex items-end justify-between mb-8">
        <div>
          <div className="caps text-faint mb-2">Signals</div>
          <h2 className="font-display text-display-xl font-bold tracking-tight leading-none">
            오늘의 시그널
          </h2>
        </div>
        <div className="text-right shrink-0 pl-12">
          {isLoading ? (
            <Skeleton height={32} width={60} />
          ) : isError ? (
            <div className="text-danger text-data">오류</div>
          ) : (
            <>
              <div className="num text-data-xl font-bold text-ink">
                {signals.length}
              </div>
              <div className="text-data-xs text-muted mt-0.5">시그널</div>
            </>
          )}
        </div>
      </header>

      {/* Period Filter */}
      <div className="flex items-center gap-2 mb-8">
        <div className="flex items-center gap-1.5 p-1 bg-tint-stone rounded-xl">
          {DAY_OPTIONS.map(({ value, label }) => (
            <button
              key={value}
              onClick={() => setDays(value)}
              className={`px-4 py-1.5 rounded-lg text-data-xs font-semibold transition-colors ${
                days === value
                  ? "bg-paper shadow-bento text-ink"
                  : "text-muted hover:text-ink"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1.5">
          <Zap size={14} className="text-faint" />
          <span className="text-data-xs text-faint">최근 {days}일 시그널</span>
        </div>
      </div>

      {/* Content */}
      {isLoading && (
        <div className="space-y-5">
          {[0, 1, 2].map((i) => (
            <SignalCardSkeleton key={i} />
          ))}
        </div>
      )}

      {isError && (
        <div className="bento p-10 text-center">
          <div className="text-danger text-data-lg font-semibold">
            시그널을 불러오지 못했습니다.
          </div>
          <div className="text-muted text-data mt-2">잠시 후 다시 시도해 주세요.</div>
        </div>
      )}

      {!isLoading && !isError && signals.length === 0 && (
        <div className="bento p-16 text-center">
          <div className="p-4 rounded-2xl bg-tint-stone inline-flex mb-4">
            <Zap size={28} className="text-faint" strokeWidth={1.5} />
          </div>
          <div className="text-headline font-semibold text-ink mb-2">
            시그널 없음
          </div>
          <div className="text-data text-muted">
            최근 {days}일간 생성된 시그널이 없습니다.
          </div>
        </div>
      )}

      {!isLoading && !isError && signals.length > 0 && (
        <div className="space-y-5">
          {signals.map((signal) => (
            <SignalCard key={`${signal.symbol}-${signal.signal_at}`} signal={signal} />
          ))}
        </div>
      )}
    </div>
  );
}
