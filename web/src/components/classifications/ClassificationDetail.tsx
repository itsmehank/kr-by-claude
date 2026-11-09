import { Link } from "react-router-dom";
import type { Components } from "react-markdown";
import { AlertTriangle, Info, LineChart } from "lucide-react";
import type { Classification } from "../../lib/types";
import { formatKst, relativeTime } from "../../lib/utils";
import { Tooltip } from "../ui/Tooltip";
import { GlossaryMarkdown } from "../glossary/GlossaryMarkdown";
import { ClassificationChip } from "./ClassificationChip";
import { ClassificationChart } from "./ClassificationChart";
import { FIELD_TOOLTIPS, PATTERN_DESCRIPTIONS, RISK_FLAG_DESCRIPTIONS } from "./meta";

/* eslint-disable @typescript-eslint/no-unused-vars -- node(hast)는 DOM 으로 넘기지 않도록 분리만 한다 */
const REASONING_MD: Components = {
  p: ({ node: _node, ...props }) => <p className="mb-2 last:mb-0" {...props} />,
  strong: ({ node: _node, ...props }) => (
    <strong className="font-semibold text-ink block mt-3 first:mt-0" {...props} />
  ),
  ul: ({ node: _node, ...props }) => <ul className="list-disc ml-5 my-1" {...props} />,
  ol: ({ node: _node, ...props }) => <ol className="list-decimal ml-5 my-1" {...props} />,
  code: ({ node: _node, ...props }) => (
    <code className="font-mono bg-cream px-1 rounded text-data-xs" {...props} />
  ),
};
/* eslint-enable @typescript-eslint/no-unused-vars */

function DetailInfo({ row }: { row: Classification }) {
  return (
    <div className="space-y-3">
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
          <div className="text-data text-ink bg-paper border border-hairline rounded-lg p-3 leading-relaxed">
            <GlossaryMarkdown components={REASONING_MD}>
              {row.reasoning}
            </GlossaryMarkdown>
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
        className="inline-flex items-center gap-1 text-data-xs text-accent hover:underline"
      >
        <LineChart size={11} /> 차트 페이지에서 전체 보기
      </Link>
    </div>
  );
}

/** 선택 종목 상세 — 왼쪽 6개월 일봉 차트, 오른쪽 기존 상세 정보(#275, 분석 회고 페이지 형태) */
export function ClassificationDetail({ row }: { row: Classification }) {
  return (
    <section className="bento mb-4 overflow-hidden" aria-label={`${row.symbol} ${row.name} 상세`}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3 border-b border-hairline">
        <span className="num text-data text-ink">{row.symbol}</span>
        <span className="text-data font-semibold text-ink">{row.name}</span>
        <span className="text-data-xs text-faint">
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
          <span className="num text-data-xs text-faint flex items-center gap-1">
            conf {row.confidence.toFixed(2)}
            <Tooltip content={FIELD_TOOLTIPS.confidence}>
              <span className="cursor-help text-faint">
                <Info size={11} />
              </span>
            </Tooltip>
          </span>
        )}
        <Tooltip content={<div className="num">분류: {formatKst(row.classified_at)} (KST)</div>}>
          <span className="text-data-xs text-faint cursor-help underline decoration-dotted decoration-faint underline-offset-2">
            {relativeTime(row.classified_at)}
          </span>
        </Tooltip>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-5">
        <div className="lg:col-span-3 p-3 min-w-0">
          <ClassificationChart row={row} />
        </div>
        <div className="lg:col-span-2 p-4 border-t lg:border-t-0 lg:border-l border-hairline bg-cream/40 lg:max-h-[460px] overflow-y-auto min-w-0">
          <DetailInfo row={row} />
        </div>
      </div>
    </section>
  );
}
