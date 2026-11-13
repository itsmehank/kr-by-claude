import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ChevronRight,
  ChevronDown,
  RefreshCw,
  Info,
} from "lucide-react";
import { api } from "../lib/api";
import type { Classification } from "../lib/types";
import { relativeTime, formatKst } from "../lib/utils";
import { Tooltip } from "../components/ui/Tooltip";
import { matchesPresenceFilters } from "../lib/classificationFilters";
import { ClassificationChip } from "../components/classifications/ClassificationChip";
import { useChatStock } from "../components/chat/chatContext";
import { ClassificationDetail } from "../components/classifications/ClassificationDetail";
import { CLASSIFICATION_LABELS, FIELD_TOOLTIPS, PATTERN_DESCRIPTIONS } from "../components/classifications/meta";
import { useSidebarAutoCollapse } from "../components/sidebarContext";
import { DEFAULT_PAGE_SIZE, PAGE_SIZES, parsePageSize, type PageSize } from "../lib/pageSize";


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

const CLASSIFICATION_ORDER = ["watch", "entry", "ignore", "disqualified", "excluded_by_universe"] as const;

const PAGE_SIZE_KEY = "kr.classifications.pageSize";

function buildQueryString(filters: Filters): string {
  const params = new URLSearchParams();
  params.set("lookback_days", String(filters.lookback_days));
  for (const c of filters.classifications) params.append("classifications", c);
  for (const s of filters.sources) params.append("sources", s);
  params.set("min_confidence", String(filters.min_confidence));
  params.set("sort", filters.sort);
  return params.toString();
}


function RowHeader({
  row,
  selected,
  onSelect,
}: {
  row: Classification;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <div
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect();
        }
      }}
      className={`flex items-center gap-3 px-4 py-3 cursor-pointer border-l-2 ${
        selected ? "bg-tint-blue/60 border-accent" : "border-transparent hover:bg-cream"
      }`}
    >
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


function ClassificationGroup({
  classification,
  rows,
  selectedSymbol,
  onSelectRow,
  pageSize,
}: {
  classification: string;
  rows: Classification[];
  selectedSymbol: string | null;
  onSelectRow: (symbol: string) => void;
  pageSize: number;
}) {
  const [groupOpen, setGroupOpen] = useState(classification !== "ignore" && classification !== "disqualified");
  const listRef = useRef<HTMLDivElement>(null);
  const [rowHeight, setRowHeight] = useState<number | null>(null);

  // 목록 높이 = 첫 행 실제 높이 × N(#275). 행 높이를 재서 폰트·여백이 바뀌어도 N행이 정확히 보이게 한다.
  // 웹폰트 교체·확대 등으로 행 높이가 나중에 바뀌어도 따라가도록 첫 행을 관찰한다(리뷰 반영).
  useLayoutEffect(() => {
    const first = listRef.current?.firstElementChild as HTMLElement | null | undefined;
    if (!first) return;
    const measure = () => setRowHeight(first.offsetHeight);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(first);
    return () => ro.disconnect();
  }, [groupOpen, rows.length]);

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
        {groupOpen && rows.length > pageSize && (
          <span className="text-data-xs text-faint">· 스크롤해서 전체 보기</span>
        )}
      </div>
      {groupOpen && (
        <div
          ref={listRef}
          className="border-t border-hairline overflow-y-auto"
          style={rowHeight ? { maxHeight: rowHeight * pageSize } : undefined}
        >
          {rows.map((row, idx) => (
            <div
              key={row.symbol}
              className={idx < rows.length - 1 ? "border-b border-hairline" : ""}
            >
              <RowHeader
                row={row}
                selected={selectedSymbol === row.symbol}
                onSelect={() => onSelectRow(row.symbol)}
              />
            </div>
          ))}
        </div>
      )}
    </section>
  );
}


export default function ClassificationsPage() {
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS);
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const [pageSize, setPageSizeState] = useState<PageSize>(() => {
    try {
      return parsePageSize(window.localStorage.getItem(PAGE_SIZE_KEY));
    } catch {
      return DEFAULT_PAGE_SIZE;
    }
  });
  const autoCollapseSidebar = useSidebarAutoCollapse();

  const setPageSize = (n: PageSize) => {
    setPageSizeState(n);
    try {
      window.localStorage.setItem(PAGE_SIZE_KEY, String(n));
    } catch {
      /* 저장 불가 환경 — 무시 */
    }
  };

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

  // 필터로 목록에서 사라진 종목은 상세 영역에 남기지 않는다(#275)
  const selectedRow = useMemo(() => {
    if (!selectedSymbol) return null;
    for (const c of CLASSIFICATION_ORDER) {
      const hit = rowsByClassification[c]?.find((r) => r.symbol === selectedSymbol);
      if (hit) return hit;
    }
    return null;
  }, [selectedSymbol, rowsByClassification]);

  // 목록이 확정된 뒤에도 선택 종목이 없으면 선택 자체를 지운다 — 나중에 필터를 되돌려도 예전 선택이
  // 갑자기 다시 나타나지 않게(리뷰 반영). 로딩 중(새 필터로 재조회)에는 판단을 미룬다.
  const listSettled = emptySelection || (q.data !== undefined && !q.isFetching);
  if (selectedSymbol && !selectedRow && listSettled) setSelectedSymbol(null);
  useChatStock(selectedRow?.symbol, selectedRow?.name); // (#281) 채팅 위젯의 "현재 맥락"

  const detailRef = useRef<HTMLDivElement>(null);
  const [scrollRequest, setScrollRequest] = useState(0);
  // 아래쪽 그룹에서 골라도 결과가 보이게, 선택이 화면에 반영된 직후 상세 영역을 화면 안으로(이미 보이면 움직이지 않음)
  useEffect(() => {
    if (scrollRequest > 0) detailRef.current?.scrollIntoView({ block: "nearest" });
  }, [scrollRequest]);

  const selectRow = (symbol: string) => {
    setSelectedSymbol(symbol);
    autoCollapseSidebar();
    setScrollRequest((n) => n + 1);
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
          <div ref={detailRef} className="scroll-mt-4">
          {selectedRow ? (
            <ClassificationDetail key={selectedRow.symbol} row={selectedRow} />
          ) : (
            <div className="bento mb-4 px-4 py-6 text-center text-data text-muted">
              목록에서 종목을 선택하면 이 자리에 6개월 일봉 차트와 분석 내용(Reasoning)이 표시됩니다.
            </div>
          )}
          </div>
          <div className="flex justify-end items-center gap-2 mb-2 text-data-xs text-faint">
            <label htmlFor="cls-page-size">보기</label>
            <select
              id="cls-page-size"
              value={pageSize}
              onChange={(e) => setPageSize(parsePageSize(e.target.value))}
              className="num text-data-xs px-1.5 py-0.5 border border-hairline rounded-md bg-paper"
            >
              {PAGE_SIZES.map((n) => (
                <option key={n} value={n}>{n}개씩</option>
              ))}
            </select>
          </div>
          {CLASSIFICATION_ORDER.map((c) => (
            <ClassificationGroup
              key={c}
              classification={c}
              rows={rowsByClassification[c] ?? []}
              selectedSymbol={selectedRow?.symbol ?? null}
              onSelectRow={selectRow}
              pageSize={pageSize}
            />
          ))}
        </>
      )}
    </div>
  );
}
