import { useState, useMemo } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ChevronRight,
  ChevronDown,
  LineChart,
  RefreshCw,
  AlertTriangle,
  Info,
} from "lucide-react";
import { api } from "../lib/api";
import type { Classification } from "../lib/types";
import { relativeTime, formatKst } from "../lib/utils";
import { Tooltip } from "../components/ui/Tooltip";
import ReactMarkdown from "react-markdown";
import {
  BREAKOUT_VOL_PREFERRED,
  MARKET_DISTRIBUTION_LOOKBACK_DAYS,
} from "../data/thresholds.generated";
import { matchesPresenceFilters } from "../lib/classificationFilters";


type SortOption = "classified_at_desc" | "confidence_desc";


interface Filters {
  lookback_days: number;
  classifications: string[];
  sources: string[];
  min_confidence: number;
  sort: SortOption;
  // 클라이언트 측 presence 필터 (백엔드 쿼리 비관여) — 받아온 행을 화면에서 거른다.
  has_pattern: boolean;
  has_pivot: boolean;
}


const DEFAULT_FILTERS: Filters = {
  lookback_days: 14,
  classifications: ["watch", "entry"],
  sources: ["weekend", "daily_delta"],
  min_confidence: 0.0,
  sort: "classified_at_desc",
  has_pattern: false,
  has_pivot: false,
};

const CLASSIFICATION_ORDER = ["watch", "entry", "ignore", "disqualified"] as const;

const CLASSIFICATION_LABELS: Record<string, string> = {
  watch: "Watch",
  entry: "Entry",
  ignore: "Ignore",
  disqualified: "자격 상실",
};

const CLASSIFICATION_TONES: Record<string, string> = {
  watch: "bg-tint-blue text-accent",
  entry: "bg-success-soft text-success",
  ignore: "bg-tint-stone text-muted",
  disqualified: "bg-tint-stone text-faint",
};

const PATTERN_DESCRIPTIONS: Record<string, string> = {
  flat_base:
    "5~7주 횡보 통합, depth ≤15% — Cup-with-handle 이후 자주 등장하는 2차 base (Box 형태).",
  cup_with_handle:
    "U자 컵 (12~33% 조정, 깊으면 50%까지) + cup 상반부에 형성된 짧은 손잡이 (8~12% pullback), 7주~수개월. O'Neil 의 가장 흔한 정통 패턴.",
  cup_without_handle:
    "U자 컵 (기준은 cup_with_handle 과 동일) — 손잡이 없이 컵 고점 돌파를 노리는 패턴 (O'Neil 5대 모델). 우측이 고점의 90%까지 회복돼야 인정. 보수 장치: 돌파 거래량 strict 1.5× + 사이징 감액 (#74).",
  vcp:
    "Volatility Contraction Pattern — 변동성과 거래량이 단계적으로 줄어드는 통합 (Minervini).",
  double_bottom:
    "W 형태 이중 바닥. 두 번째 저점이 첫 저점을 살짝 undercut(shakeout). Buy point 는 W 중앙 peak (top of middle peak, 우측). 두 번째 바닥에서 매수는 너무 이름.",
  none:
    "Base 패턴 식별되지 않음.",
  high_tight_flag:
    "4~8주에 가격 100~120%+ 상승(깃대) 후 3~6주간 25% 이내 횡보(깃발) — 매우 강한 매수 신호 (드문 패턴, O'Neil HMM 'High Tight Flag' / Minervini Power Play).",
  "3c_cheat":
    "Cup이 완성되기 전 중·하반부에서 형성되는 cheat 영역의 early entry pivot (Minervini Trade Like a Stock Market Wizard ch.10 / Think & Trade Like a Champion ch.7).",
  base_on_base:
    "1차 base 돌파 후 20~30% 상승 못 하고 위쪽에 2차 base 형성. Bear market 막판 강세 신호 (O'Neil HMM 'Base on Top of a Base').",
  ascending_base:
    "3번의 10~20% pullback이 점점 더 높은 저점에서 발생. 시장 약세기에 강한 종목 (O'Neil HMM 'Ascending Base').",
};

const RISK_FLAG_DESCRIPTIONS: Record<string, string> = {
  climax_run:
    "1~3주에 가격 25%+ 상승 + 가장 큰 주봉/거래량 — Minervini Stage 3 climax 경고.",
  late_stage_base:
    "현재 Stage 2 advance 의 3번째 이상 base. O'Neil: base 3~4는 경계, Minervini: base 4+ 위험.",
  extended_from_ma:
    "50일 이평선 위 15%+ — 추격 진입 위험 (실무 휴리스틱; O'Neil 원전은 pivot 에서 5~10%+ 추격 시 늦은 매수).",
  faulty_pivot:
    "Pivot 의 형태적 결함 (wedging handle, handle이 base 하반부, V자 즉시 신고가, 거래량 없는 돌파 등).",
  low_volume_breakout:
    `돌파 거래량이 50일 평균의 ${BREAKOUT_VOL_PREFERRED.toFixed(1)}배 미만 (O'Neil: 50% above average 가 최소).`,
  narrow_base:
    "패턴별 최소 기간보다 짧은 base.",
  wide_and_loose:
    "주봉 변동폭이 erratic / 시장 조정 대비 2.5배 초과 — 거래 어려운 base (O'Neil).",
  prior_uptrend_insufficient:
    "직전 base 대비 20% 미만 상승 — flat_base 패턴의 prior uptrend 요건 미달 (prompt §5). C6 (52주 저점 ×1.25) 와 다른 개념.",
  volume_contraction_on_advance:
    "상승 중 거래량 감소 — 수요 약화 / 기관 매수 부족 신호 (O'Neil: lost appetite).",
  reverse_split_distortion:
    "최근 12주 내 reverse split — 가격 왜곡 가능 (실무 휴리스틱, 책 원전 아님).",
  unfavorable_market_context:
    `시장 downtrend/correction 또는 distribution day 5개 이상 (${MARKET_DISTRIBUTION_LOOKBACK_DAYS} sessions). O'Neil HMMS Ch.9 의 표준.`,
  etf_methodology_mismatch:
    "ETF/fund — Minervini/O'Neil 개별 leadership 종목 방법론 적용 안 됨.",
  thin_liquidity_us_only:
    "(US only) 일평균 거래대금 $5M 미만 (실무 변형; O'Neil disciple 원전은 35~50만 주 최소).",
};

const FIELD_TOOLTIPS = {
  pivot:
    "베이스 안에서 거래량 동반으로 이 가격을 돌파하면 buy point (Minervini/O'Neil 진입 기준).",
  base:
    "가격 통합 구간 (low~high, 형성 시작일~현재). depth = 고점 대비 저점 하락률. 매물 소화 후 새 추세 시작.",
  confidence:
    "LLM 의 분류 자신감 (0~1). 데이터 부족 / 모호한 패턴 / 시장 컨텍스트 불리 시 낮아짐.",
};


function buildQueryString(filters: Filters): string {
  const params = new URLSearchParams();
  params.set("lookback_days", String(filters.lookback_days));
  for (const c of filters.classifications) params.append("classifications", c);
  for (const s of filters.sources) params.append("sources", s);
  params.set("min_confidence", String(filters.min_confidence));
  params.set("sort", filters.sort);
  return params.toString();
}


function ClassificationChip({ classification }: { classification: string }) {
  const tone = CLASSIFICATION_TONES[classification] ?? "bg-tint-stone text-muted";
  const label = CLASSIFICATION_LABELS[classification] ?? classification;
  return <span className={`chip ${tone}`}>{label}</span>;
}


function RowHeader({
  row,
  expanded,
  onToggle,
}: {
  row: Classification;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <div
      onClick={onToggle}
      className="flex items-center gap-3 px-4 py-3 hover:bg-cream cursor-pointer"
    >
      <span className="text-faint shrink-0">
        {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
      </span>
      <span className="num text-data text-ink shrink-0">{row.symbol}</span>
      <span className="text-data text-ink truncate min-w-0">{row.name}</span>
      <span className="text-data-xs text-faint shrink-0 whitespace-nowrap">
        {row.sector && `· ${row.sector}`}
        {row.market && ` · ${row.market}`}
      </span>
      <div className="flex-1" />
      <ClassificationChip classification={row.classification} />
      {row.pattern && (
        <Tooltip content={PATTERN_DESCRIPTIONS[row.pattern] ?? row.pattern}>
          <span className="text-data-xs text-muted cursor-help underline decoration-dotted decoration-faint underline-offset-2">
            {row.pattern}
          </span>
        </Tooltip>
      )}
      {row.confidence != null && (
        <span className="num text-data-xs text-faint shrink-0 flex items-center gap-1">
          conf {row.confidence.toFixed(2)}
          <Tooltip content={FIELD_TOOLTIPS.confidence}>
            <span className="cursor-help text-faint">
              <Info size={11} />
            </span>
          </Tooltip>
        </span>
      )}
      <Tooltip
        content={
          <>
            <div className="num">분류: {formatKst(row.classified_at)}</div>
            <div className="text-faint mt-1">(KST)</div>
          </>
        }
      >
        <span className="text-data-xs text-faint shrink-0 cursor-help underline decoration-dotted decoration-faint underline-offset-2">
          {relativeTime(row.classified_at)}
        </span>
      </Tooltip>
    </div>
  );
}


function RowDetails({ row }: { row: Classification }) {
  return (
    <div className="px-10 pb-4 space-y-3 bg-cream/50">
      <div className="grid grid-cols-2 gap-4 text-data-xs">
        {row.pivot_price != null && (
          <div>
            <div className="caps text-faint flex items-center gap-1">
              Pivot
              <Tooltip content={FIELD_TOOLTIPS.pivot}>
                <span className="cursor-help">
                  <Info size={10} />
                </span>
              </Tooltip>
            </div>
            <div className="num text-data text-ink">
              {row.pivot_price.toLocaleString()}{" "}
              {row.pivot_basis && (
                <span className="text-data-xs text-faint">({row.pivot_basis})</span>
              )}
            </div>
          </div>
        )}
        {row.base_high != null && row.base_low != null && (
          <div>
            <div className="caps text-faint flex items-center gap-1">
              Base
              <Tooltip content={FIELD_TOOLTIPS.base}>
                <span className="cursor-help">
                  <Info size={10} />
                </span>
              </Tooltip>
            </div>
            <div className="num text-data text-ink">
              {row.base_low.toLocaleString()} ~ {row.base_high.toLocaleString()}
              {row.base_depth_pct != null && (
                <span className="text-data-xs text-faint"> ({row.base_depth_pct.toFixed(1)}%)</span>
              )}
              {row.base_start_date && (
                <div className="text-data-xs text-faint">{row.base_start_date} 부터</div>
              )}
            </div>
          </div>
        )}
      </div>

      {row.risk_flags && row.risk_flags.length > 0 && (
        <div>
          <div className="caps text-faint mb-1">Risk Flags</div>
          <div className="flex flex-wrap gap-1">
            {row.risk_flags.map((flag) => (
              <Tooltip key={flag} content={RISK_FLAG_DESCRIPTIONS[flag] ?? flag}>
                <span className="chip bg-amber-soft text-amber cursor-help">
                  <AlertTriangle size={11} /> {flag}
                </span>
              </Tooltip>
            ))}
          </div>
        </div>
      )}

      {row.reasoning && (
        <div>
          <div className="caps text-faint mb-1">Reasoning</div>
          <div className="text-data text-ink bg-paper border border-hairline rounded-lg p-3 max-h-96 overflow-auto leading-relaxed">
            <ReactMarkdown
              components={{
                p: ({ node: _node, ...props }) => <p className="mb-2 last:mb-0" {...props} />,
                strong: ({ node: _node, ...props }) => (
                  <strong className="font-semibold text-ink block mt-3 first:mt-0" {...props} />
                ),
                ul: ({ node: _node, ...props }) => <ul className="list-disc ml-5 my-1" {...props} />,
                ol: ({ node: _node, ...props }) => <ol className="list-decimal ml-5 my-1" {...props} />,
                code: ({ node: _node, ...props }) => (
                  <code className="font-mono bg-cream px-1 rounded text-data-xs" {...props} />
                ),
              }}
            >
              {row.reasoning}
            </ReactMarkdown>
          </div>
        </div>
      )}

      <div className="flex flex-wrap gap-x-4 gap-y-1 text-data-xs text-faint num">
        {row.analyzed_for_date && <span>기준일: {row.analyzed_for_date}</span>}
        <span>source: {row.source}</span>
        {row.llm_call_duration_s != null && (
          <span>duration: {row.llm_call_duration_s.toFixed(1)}s</span>
        )}
        {row.llm_input_tokens != null && (
          <span>in: {row.llm_input_tokens.toLocaleString()} tok</span>
        )}
        {row.llm_output_tokens != null && (
          <span>out: {row.llm_output_tokens.toLocaleString()} tok</span>
        )}
      </div>

      <Link
        to={`/chart/${row.symbol}`}
        target="_blank"
        rel="noopener noreferrer"
        onClick={(e) => e.stopPropagation()}
        className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-accent text-white rounded-lg text-data-xs font-semibold hover:bg-accent-light"
      >
        <LineChart size={11} /> 차트 보기
      </Link>
    </div>
  );
}


function ClassificationGroup({
  classification,
  rows,
  expandedRows,
  onToggleRow,
}: {
  classification: string;
  rows: Classification[];
  expandedRows: Set<string>;
  onToggleRow: (symbol: string) => void;
}) {
  const [groupOpen, setGroupOpen] = useState(classification !== "ignore" && classification !== "disqualified");

  if (rows.length === 0) return null;

  return (
    <section className="bento mb-4">
      <div
        onClick={() => setGroupOpen(!groupOpen)}
        className="flex items-center gap-2 px-4 py-3 cursor-pointer hover:bg-cream"
      >
        <span className="text-faint">
          {groupOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </span>
        <ClassificationChip classification={classification} />
        <span className="text-data text-muted">{rows.length} 건</span>
      </div>
      {groupOpen && (
        <div className="border-t border-hairline">
          {rows.map((row, idx) => (
            <div
              key={row.symbol}
              className={idx < rows.length - 1 ? "border-b border-hairline" : ""}
            >
              <RowHeader
                row={row}
                expanded={expandedRows.has(row.symbol)}
                onToggle={() => onToggleRow(row.symbol)}
              />
              {expandedRows.has(row.symbol) && <RowDetails row={row} />}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}


export default function ClassificationsPage() {
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS);
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());

  const qs = buildQueryString(filters);
  // 체크 0개 = "아무것도 안 보여야". 파라미터를 아예 안 보내면 백엔드가
  // NULL 필터로 받아 "전부 표시"로 반전되므로, 빈 선택은 요청 없이 빈 결과 처리.
  const emptySelection =
    filters.classifications.length === 0 || filters.sources.length === 0;
  const q = useQuery<Classification[]>({
    queryKey: ["classifications", qs],
    queryFn: () => api<Classification[]>(`/classifications?${qs}`),
    enabled: !emptySelection,
  });

  const rowsByClassification = useMemo(() => {
    const grouped: Record<string, Classification[]> = {
      watch: [],
      entry: [],
      ignore: [],
      disqualified: [],
    };
    const presence = { hasPattern: filters.has_pattern, hasPivot: filters.has_pivot };
    for (const row of emptySelection ? [] : q.data ?? []) {
      if (!matchesPresenceFilters(row, presence)) continue;
      const c = grouped[row.classification] ?? (grouped[row.classification] = []);
      c.push(row);
    }
    return grouped;
  }, [q.data, emptySelection, filters.has_pattern, filters.has_pivot]);

  const counts = {
    watch: rowsByClassification.watch?.length ?? 0,
    entry: rowsByClassification.entry?.length ?? 0,
    ignore: rowsByClassification.ignore?.length ?? 0,
    disqualified: rowsByClassification.disqualified?.length ?? 0,
  };

  // presence 필터 적용 후 화면에 남는 총 행 수. q.data 는 있으나 클라이언트
  // 필터가 전부 걸러내면 0 — 이때 빈 화면 대신 안내를 띄우기 위해 별도 집계.
  const totalVisible = counts.watch + counts.entry + counts.ignore + counts.disqualified;
  const presenceActive = filters.has_pattern || filters.has_pivot;

  const toggleRow = (symbol: string) => {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(symbol)) next.delete(symbol);
      else next.add(symbol);
      return next;
    });
  };

  const toggleClassification = (c: string) => {
    setFilters((prev) => ({
      ...prev,
      classifications: prev.classifications.includes(c)
        ? prev.classifications.filter((x) => x !== c)
        : [...prev.classifications, c],
    }));
  };

  const toggleSource = (s: string) => {
    setFilters((prev) => ({
      ...prev,
      sources: prev.sources.includes(s)
        ? prev.sources.filter((x) => x !== s)
        : [...prev.sources, s],
    }));
  };

  return (
    <div className="px-10 py-10 max-w-[1240px] mx-auto">
      <header className="flex items-end justify-between mb-8">
        <div>
          <div className="caps text-faint mb-2">Classifications</div>
          <h2 className="font-display text-display-xl font-bold tracking-tight leading-none">
            LLM 분류
          </h2>
          <div className="flex gap-2 mt-3">
            <span className="chip bg-tint-blue text-accent">Watch {counts.watch}</span>
            <span className="chip bg-success-soft text-success">Entry {counts.entry}</span>
            <span className="chip bg-tint-stone text-muted">Ignore {counts.ignore}</span>
            {counts.disqualified > 0 && (
              <span className="chip bg-tint-stone text-faint">자격 상실 {counts.disqualified}</span>
            )}
          </div>
        </div>
        <button
          onClick={() => q.refetch()}
          className="flex items-center gap-1.5 text-data text-muted hover:text-ink"
        >
          <RefreshCw size={14} />
          새로고침
        </button>
      </header>

      <section className="bento p-4 mb-6">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
          <div className="flex items-center gap-2">
            <span className="caps text-faint">분류 기간</span>
            <Tooltip
              content={
                <div className="leading-relaxed">
                  선택한 기간 내에 분류된 적이 있는 종목만 표시.
                  한 종목이 여러 번 분류되었다면 그 중 가장 최신 1건만 응답.
                  <br /><br />
                  예: '14일' = 직전 14일 안에 분류된 종목들, 종목당 최신 분류 1건.
                </div>
              }
            >
              <span className="text-faint cursor-help">
                <Info size={11} />
              </span>
            </Tooltip>
            <select
              value={filters.lookback_days}
              onChange={(e) => setFilters({ ...filters, lookback_days: parseInt(e.target.value, 10) })}
              className="num text-data px-2 py-1 border border-hairline rounded-lg bg-paper"
            >
              <option value={7}>7일</option>
              <option value={14}>14일</option>
              <option value={30}>30일</option>
              <option value={90}>90일</option>
            </select>
          </div>

          <div className="flex items-center gap-2">
            <span className="caps text-faint">분류</span>
            {(["watch", "entry", "ignore", "disqualified"] as const).map((c) => (
              <label key={c} className="flex items-center gap-1 cursor-pointer text-data-xs">
                <input
                  type="checkbox"
                  checked={filters.classifications.includes(c)}
                  onChange={() => toggleClassification(c)}
                  className="accent-accent"
                />
                {CLASSIFICATION_LABELS[c]}
              </label>
            ))}
          </div>

          <div className="flex items-center gap-2">
            <span className="caps text-faint">소스</span>
            {(["weekend", "daily_delta"] as const).map((s) => (
              <label key={s} className="flex items-center gap-1 cursor-pointer text-data-xs">
                <input
                  type="checkbox"
                  checked={filters.sources.includes(s)}
                  onChange={() => toggleSource(s)}
                  className="accent-accent"
                />
                {s}
              </label>
            ))}
          </div>

          <div className="flex items-center gap-2">
            <span className="caps text-faint">조건</span>
            <Tooltip
              content={
                <div className="leading-relaxed">
                  받아온 분류 행을 화면에서 추가로 거른다 (watch 목록 추리기용).
                  <br />
                  · pattern 있음 — base 패턴이 식별된 종목 ('none'/미식별 제외)
                  <br />
                  · pivot 있음 — buy point(pivot)가 계산된 종목
                </div>
              }
            >
              <span className="text-faint cursor-help">
                <Info size={11} />
              </span>
            </Tooltip>
            <label className="flex items-center gap-1 cursor-pointer text-data-xs">
              <input
                type="checkbox"
                checked={filters.has_pattern}
                onChange={() => setFilters((p) => ({ ...p, has_pattern: !p.has_pattern }))}
                className="accent-accent"
              />
              pattern 있음
            </label>
            <label className="flex items-center gap-1 cursor-pointer text-data-xs">
              <input
                type="checkbox"
                checked={filters.has_pivot}
                onChange={() => setFilters((p) => ({ ...p, has_pivot: !p.has_pivot }))}
                className="accent-accent"
              />
              pivot 있음
            </label>
          </div>

          <div className="flex items-center gap-2">
            <span className="caps text-faint">최소 conf</span>
            <input
              type="number"
              min={0}
              max={1}
              step={0.05}
              value={filters.min_confidence}
              onChange={(e) => setFilters({ ...filters, min_confidence: parseFloat(e.target.value) || 0 })}
              className="num text-data w-20 px-2 py-1 border border-hairline rounded-lg"
            />
          </div>

          <div className="flex items-center gap-2">
            <span className="caps text-faint">정렬</span>
            <select
              value={filters.sort}
              onChange={(e) => setFilters({ ...filters, sort: e.target.value as SortOption })}
              className="text-data px-2 py-1 border border-hairline rounded-lg bg-paper"
            >
              <option value="classified_at_desc">시각 최신</option>
              <option value="confidence_desc">Confidence</option>
            </select>
          </div>
        </div>
      </section>

      {q.isLoading && <div className="text-muted">로딩 중…</div>}
      {q.isError && <div className="text-danger">에러: {String(q.error)}</div>}
      {q.data && totalVisible === 0 && (
        <div className="bento p-8 text-center text-muted">
          {presenceActive ? (
            "선택한 조건(pattern/pivot 있음)에 맞는 종목이 없습니다."
          ) : (
            <>
              최근 {filters.lookback_days}일간 분류 결과 없음.
              <div className="text-data-xs text-faint mt-2">
                /runner 에서 'LLM 주말 분류' 또는 'LLM 평일 전체 분석' 실행.
              </div>
            </>
          )}
        </div>
      )}
      {q.data && totalVisible > 0 && (
        <>
          {CLASSIFICATION_ORDER.map((c) => (
            <ClassificationGroup
              key={c}
              classification={c}
              rows={rowsByClassification[c] ?? []}
              expandedRows={expandedRows}
              onToggleRow={toggleRow}
            />
          ))}
        </>
      )}
    </div>
  );
}
