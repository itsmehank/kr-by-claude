import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  Layers,
  TrendingUp,
  Star,
  Building2,
  Trophy,
  Activity,
  ChevronRight,
} from "lucide-react";
import { api } from "../lib/api";
import type {
  Stock,
  MinerviniPassed,
  MarketContext,
  PipelineRun,
} from "../lib/types";
import { InfoTooltip } from "../components/ui/InfoTooltip";
import { Skeleton, SkeletonRow } from "../components/ui/Skeleton";
import { RunDetailModal } from "../components/ui/RunDetailModal";
import { relativeTime } from "../lib/utils";

// ── Helpers ────────────────────────────────────────────────────────────────

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    confirmed_uptrend: "상승 추세 확정",
    uptrend_under_pressure: "상승 추세 압박",
    downtrend: "하락 추세",
    correction: "조정 국면",
    rally_attempt: "반등 시도",
  };
  return map[status] ?? status;
}

function statusTone(status: string): "up" | "down" | "neutral" {
  if (status === "confirmed_uptrend" || status === "rally_attempt") return "up";
  if (status === "downtrend" || status === "correction") return "down";
  return "neutral";
}

function todayParts() {
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  const weekdayKr = ["일", "월", "화", "수", "목", "금", "토"][d.getDay()];
  return { yyyy, mm, dd, weekdayKr };
}

// ── Empty state ────────────────────────────────────────────────────────────

interface EmptyProps {
  label?: string;
}
function EmptyState({ label = "데이터 없음" }: EmptyProps) {
  return <div className="text-data text-muted py-2">{label}</div>;
}

// ── Sub-components ─────────────────────────────────────────────────────────

interface StatBentoProps {
  Icon: typeof Layers;
  iconBg: string;
  iconColor: string;
  label: string;
  value: number | null | undefined;
  loading: boolean;
  error: boolean;
  subLabel?: string;
  onClick?: () => void;
}

function StatBento({
  Icon,
  iconBg,
  iconColor,
  label,
  value,
  loading,
  error,
  subLabel,
  onClick,
}: StatBentoProps) {
  const clickable = !!onClick;
  return (
    <div
      role={clickable ? "button" : undefined}
      tabIndex={clickable ? 0 : undefined}
      onClick={onClick}
      onKeyDown={
        clickable
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onClick?.();
              }
            }
          : undefined
      }
      className={`bento p-6 ${
        clickable ? "bento-clickable group" : ""
      }`}
    >
      <div className="flex items-center justify-between mb-5">
        <div className={["p-2.5 rounded-xl", iconBg].join(" ")}>
          <Icon size={20} className={iconColor} strokeWidth={2} />
        </div>
        <div className="flex items-center gap-2">
          {subLabel && <span className="caps text-faint">{subLabel}</span>}
          {clickable && (
            <ChevronRight
              size={16}
              className="text-faint group-hover:text-accent transition-colors"
            />
          )}
        </div>
      </div>
      <div className="text-subhead text-muted font-medium mb-2">{label}</div>
      {loading ? (
        <Skeleton height={44} width="60%" />
      ) : error ? (
        <div className="num text-data-xl font-semibold text-danger">오류</div>
      ) : (
        <div className="num text-data-xl font-semibold tracking-tight text-ink">
          {(value ?? 0).toLocaleString()}
        </div>
      )}
    </div>
  );
}

interface DataLabelProps {
  label: string;
  tip: React.ReactNode;
}
function DataLabel({ label, tip }: DataLabelProps) {
  return (
    <span className="caps inline-flex items-center">
      {label}
      <InfoTooltip>{tip}</InfoTooltip>
    </span>
  );
}

interface MarketBentoProps {
  context: MarketContext | undefined;
  title: string;
  code: string;
  tint: "blue" | "amber" | "rose" | "mint" | "stone";
}

function MarketBento({ context, title, code, tint }: MarketBentoProps) {
  const tintClass = {
    blue: "bento-tint-blue",
    amber: "bento-tint-amber",
    rose: "bento-tint-rose",
    mint: "bento-tint-mint",
    stone: "bento-tint-stone",
  }[tint];

  if (!context) {
    return (
      <div className={`${tintClass} p-7`}>
        <div className="flex items-center gap-2.5 mb-6">
          <div className="p-2 rounded-xl bg-paper">
            <Building2 size={18} className="text-faint" strokeWidth={2} />
          </div>
          <div>
            <div className="font-display text-display-md font-bold leading-none">
              {title}
            </div>
            <div className="text-data-xs text-muted mt-1">Index · {code}</div>
          </div>
        </div>
        <EmptyState label="시장 데이터 없음" />
      </div>
    );
  }

  const tone = statusTone(context.current_status);
  const toneClass =
    tone === "down"
      ? "text-danger"
      : tone === "up"
      ? "text-success"
      : "text-muted";
  const dotClass =
    tone === "down" ? "bg-danger" : tone === "up" ? "bg-success" : "bg-faint";
  const toneKr = tone === "up" ? "상승" : tone === "down" ? "하락" : "중립";

  return (
    <div className={`${tintClass} p-7`}>
      <div className="flex items-start justify-between mb-6">
        <div className="flex items-center gap-2.5">
          <div className="p-2 rounded-xl bg-paper">
            <Building2 size={18} className="text-ink" strokeWidth={2} />
          </div>
          <div>
            <div className="font-display text-display-md font-bold leading-none">
              {title}
            </div>
            <div className="text-data-xs text-muted mt-1">Index · {code}</div>
          </div>
        </div>
        <span className={["chip bg-paper", toneClass].join(" ")}>
          <span className={["h-1.5 w-1.5 rounded-full", dotClass].join(" ")} />
          {toneKr}
        </span>
      </div>

      <div className={["text-headline font-bold mb-7", toneClass].join(" ")}>
        {statusLabel(context.current_status)}
      </div>

      <dl className="grid grid-cols-3 gap-4">
        <div>
          <dt>
            <DataLabel
              label="Distribution"
              tip={
                <>
                  <div className="font-semibold mb-1">Distribution Day</div>
                  <div>
                    지수가 -0.2% 이상 하락 + 거래량 전일 대비 증가한 날. 기관 매도 신호.
                    최근 25일 중 5일 이상이면 약세장 시사.
                  </div>
                  <div className="text-faint mt-1 text-data-xs">
                    O'Neil HTMMIS Ch.9
                  </div>
                </>
              }
            />
          </dt>
          <dd className="num text-data-lg font-semibold mt-1.5">
            {context.distribution_day_count_last_25_sessions ?? "—"}
            <span className="text-data text-muted ml-1 font-normal">/25d</span>
          </dd>
        </div>
        <div>
          <dt>
            <DataLabel
              label="Breadth"
              tip={
                <>
                  <div className="font-semibold mb-1">Market Breadth</div>
                  <div>
                    전체 종목 중 200일 이평선 위에 있는 비율. 시장 폭 지표.
                    &gt; 60% 강세, &lt; 40% 약세 시사.
                  </div>
                </>
              }
            />
          </dt>
          <dd className="num text-data-lg font-semibold mt-1.5">
            {context.pct_stocks_above_200d_ma != null
              ? `${context.pct_stocks_above_200d_ma.toFixed(1)}%`
              : "—"}
          </dd>
        </div>
        <div>
          <dt>
            <DataLabel
              label="FTD"
              tip={
                <>
                  <div className="font-semibold mb-1">Follow-Through Day</div>
                  <div>
                    시장 바닥 후 4-7일째 +1.7% 이상 상승 + 거래량 증가한 첫 강세 신호.
                    신규 상승장 진입 트리거.
                  </div>
                </>
              }
            />
          </dt>
          <dd className="num text-data-md font-semibold mt-1.5 text-muted">
            {context.last_follow_through_day ?? "—"}
          </dd>
        </div>
      </dl>
    </div>
  );
}

interface RunStatusProps {
  status: string;
}
function RunStatus({ status }: RunStatusProps) {
  if (status === "success") {
    return (
      <span className="chip bg-success-soft text-success">
        <span className="h-1.5 w-1.5 rounded-full bg-success" />
        success
      </span>
    );
  }
  if (status === "failed" || status === "error") {
    return (
      <span className="chip bg-danger-soft text-danger">
        <span className="h-1.5 w-1.5 rounded-full bg-danger" />
        {status}
      </span>
    );
  }
  if (status === "running") {
    return (
      <span className="chip bg-amber-soft text-amber">
        <span className="h-1.5 w-1.5 rounded-full bg-amber animate-pulse" />
        running
      </span>
    );
  }
  return <span className="chip bg-tint-stone text-muted">{status}</span>;
}

// ── Main Page ──────────────────────────────────────────────────────────────

export default function HomePage() {
  const navigate = useNavigate();
  const { yyyy, mm, dd, weekdayKr } = todayParts();
  const [openRunId, setOpenRunId] = useState<number | null>(null);

  const stocksQ = useQuery<Stock[]>({
    queryKey: ["snapshot", "stocks"],
    queryFn: () => api<Stock[]>("/stocks?limit=10000"),
  });
  const minerviniQ = useQuery<MinerviniPassed[]>({
    queryKey: ["snapshot", "minervini70"],
    queryFn: () =>
      api<MinerviniPassed[]>("/indicators/minervini-passed?min_rs=70&limit=10000"),
  });
  const minervini80Q = useQuery<MinerviniPassed[]>({
    queryKey: ["snapshot", "minervini80"],
    queryFn: () =>
      api<MinerviniPassed[]>("/indicators/minervini-passed?min_rs=80&limit=10000"),
  });
  const marketQ = useQuery<MarketContext[]>({
    queryKey: ["market-context"],
    queryFn: () => api<MarketContext[]>("/market-context"),
  });
  const topRsQ = useQuery<MinerviniPassed[]>({
    queryKey: ["top-rs"],
    queryFn: () =>
      api<MinerviniPassed[]>("/indicators/minervini-passed?min_rs=70&limit=10"),
  });
  const runsQ = useQuery<PipelineRun[]>({
    queryKey: ["recent-runs"],
    queryFn: () => api<PipelineRun[]>("/runs?limit=8"),
  });

  const kospi = marketQ.data?.find((m) => m.index_code === "1001");
  const kosdaq = marketQ.data?.find((m) => m.index_code === "2001");

  return (
    <div className="px-10 py-10 max-w-[1240px] mx-auto">
      {/* Header */}
      <header className="flex items-end justify-between mb-8">
        <div>
          <div className="caps text-faint mb-2">Overview</div>
          <h2 className="font-display text-display-xl font-bold tracking-tight leading-none">
            오늘의 시장
          </h2>
        </div>
        <div className="text-right shrink-0 pl-12">
          <div className="num text-data-md font-semibold text-ink">
            {yyyy}.{mm}.{dd}
          </div>
          <div className="text-data-xs text-muted mt-1">{weekdayKr}요일</div>
        </div>
      </header>

      {/* Row 1: 3 stat cards */}
      <div className="grid grid-cols-3 gap-5 mb-5">
        <StatBento
          Icon={Layers}
          iconBg="bg-tint-stone"
          iconColor="text-ink"
          label="활성 종목"
          subLabel="ALL"
          value={stocksQ.data?.length}
          loading={stocksQ.isLoading}
          error={stocksQ.isError}
        />
        <StatBento
          Icon={TrendingUp}
          iconBg="bg-tint-blue"
          iconColor="text-accent"
          label="미너비니 통과"
          subLabel="RS ≥ 70"
          value={minerviniQ.data?.length}
          loading={minerviniQ.isLoading}
          error={minerviniQ.isError}
          onClick={() => navigate("/minervini?min_rs=70")}
        />
        <StatBento
          Icon={Star}
          iconBg="bg-tint-amber"
          iconColor="text-amber"
          label="고 RS 통과"
          subLabel="RS ≥ 80"
          value={minervini80Q.data?.length}
          loading={minervini80Q.isLoading}
          error={minervini80Q.isError}
          onClick={() => navigate("/minervini?min_rs=80")}
        />
      </div>

      {/* Row 2: 2 market cards */}
      <div className="grid grid-cols-2 gap-5 mb-5">
        {marketQ.isLoading && (
          <>
            <div className="bento p-7">
              <Skeleton height={28} width="50%" className="mb-4" />
              <Skeleton height={20} width="70%" />
            </div>
            <div className="bento p-7">
              <Skeleton height={28} width="50%" className="mb-4" />
              <Skeleton height={20} width="70%" />
            </div>
          </>
        )}
        {marketQ.isError && (
          <div className="bento p-7 text-danger col-span-2">
            시장 컨텍스트 로딩 실패
          </div>
        )}
        {marketQ.data && (
          <>
            <MarketBento context={kospi} title="KOSPI" code="1001" tint="blue" />
            <MarketBento
              context={kosdaq}
              title="KOSDAQ"
              code="2001"
              tint="amber"
            />
          </>
        )}
      </div>

      {/* Row 3: Top RS + Runs */}
      <div className="grid grid-cols-[7fr_5fr] gap-5">
        <section className="bento p-6">
          <div className="flex items-center justify-between mb-5">
            <div className="flex items-center gap-2.5">
              <div className="p-2 rounded-xl bg-tint-amber">
                <Trophy size={16} className="text-amber" strokeWidth={2} />
              </div>
              <div>
                <div className="text-subhead font-bold text-ink">
                  RS Rating Top 10
                </div>
                <div className="text-data-xs text-muted mt-0.5">
                  미너비니 통과 종목
                </div>
              </div>
            </div>
          </div>

          {topRsQ.isLoading && (
            <div className="space-y-1">
              {Array.from({ length: 5 }).map((_, i) => (
                <SkeletonRow key={i} cols={5} />
              ))}
            </div>
          )}
          {topRsQ.isError && <EmptyState label="로딩 실패" />}
          {topRsQ.data && topRsQ.data.length === 0 && (
            <EmptyState label="통과 종목 없음" />
          )}
          {topRsQ.data && topRsQ.data.length > 0 && (
            <div className="space-y-0.5">
              {topRsQ.data.map((row, i) => (
                <div
                  key={row.ticker}
                  className="row-clickable px-3 py-2.5 flex items-center gap-4"
                  onClick={() => navigate(`/chart/${row.ticker}`)}
                >
                  <div className="num text-data-xs text-faint w-6 shrink-0">
                    {String(i + 1).padStart(2, "0")}
                  </div>
                  <div className="num text-data text-muted w-16 shrink-0">
                    {row.ticker}
                  </div>
                  <div
                    className="text-data text-ink flex-1 truncate"
                    title={row.name}
                  >
                    {row.name}
                  </div>
                  <div className="num text-data-md font-semibold text-ink w-12 text-right">
                    {row.rs_rating}
                  </div>
                  <div className="num text-data text-muted w-24 text-right">
                    ₩{row.adj_close.toLocaleString()}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="bento p-6">
          <div className="flex items-center justify-between mb-5">
            <div className="flex items-center gap-2.5">
              <div className="p-2 rounded-xl bg-tint-stone">
                <Activity size={16} className="text-muted" strokeWidth={2} />
              </div>
              <div>
                <div className="text-subhead font-bold text-ink">
                  파이프라인 이력
                </div>
                <div className="text-data-xs text-muted mt-0.5">최근 8개</div>
              </div>
            </div>
          </div>

          {runsQ.isLoading && (
            <div className="space-y-1">
              {Array.from({ length: 4 }).map((_, i) => (
                <SkeletonRow key={i} cols={4} />
              ))}
            </div>
          )}
          {runsQ.isError && <EmptyState label="로딩 실패" />}
          {runsQ.data && runsQ.data.length === 0 && (
            <EmptyState label="이력 없음" />
          )}
          {runsQ.data && runsQ.data.length > 0 && (
            <div className="space-y-1.5">
              {runsQ.data.map((run) => (
                <button
                  key={run.id}
                  onClick={() => setOpenRunId(run.id)}
                  className="row-clickable w-full flex items-center gap-3 px-3 py-2 text-left"
                >
                  <div className="num text-data-xs text-faint w-6 shrink-0">
                    {run.id}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-data text-ink truncate">
                      {run.pipeline}
                    </div>
                    <div className="text-data-xs text-muted mt-0.5">
                      {run.mode} · {relativeTime(run.started_at)}
                    </div>
                  </div>
                  <RunStatus status={run.status} />
                </button>
              ))}
            </div>
          )}
        </section>
      </div>

      <RunDetailModal runId={openRunId} onClose={() => setOpenRunId(null)} />
    </div>
  );
}
