import {
  BASE_PATTERNS,
  NARROW_BASE_THRESHOLDS,
  DEPTH_RULES,
  PIVOT_RULES,
} from "../../data/llm-pipeline-audit/base-patterns";

export function PatternCards() {
  return (
    <div>
      <h4 className="caps text-faint mb-2">5.1 패턴 정의</h4>
      <div className="overflow-x-auto mb-4">
        <table className="w-full text-data border-collapse">
          <thead>
            <tr className="border-b border-hairline text-faint">
              <th className="text-left py-2 pr-3">Pattern</th>
              <th className="text-left py-2 pr-3">Definition</th>
              <th className="text-left py-2">Source</th>
            </tr>
          </thead>
          <tbody>
            {BASE_PATTERNS.map((p) => (
              <tr key={p.id} className="border-b border-hairline align-top">
                <td className="py-2 pr-3">
                  <code className="num font-semibold text-ink">{p.id}</code>
                </td>
                <td className="py-2 pr-3 text-data-xs text-muted">{p.definition}</td>
                <td className="py-2 text-data-xs text-faint italic">{p.source}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mb-4 p-3 bg-cream border border-hairline rounded-xl text-data-xs">
        <div className="caps text-faint mb-1">narrow_base 패턴별 최소 기간</div>
        <ul className="text-muted space-y-0.5">
          {NARROW_BASE_THRESHOLDS.map((t) => (
            <li key={t.pattern}>
              <code className="num">{t.pattern}</code>: &lt; {t.minWeeks} 주
            </li>
          ))}
          <li className="text-faint italic">high_tight_flag 는 narrow_base 적용 안 됨</li>
        </ul>
      </div>

      <div className="mb-4 p-3 bg-cream border border-hairline rounded-xl text-data-xs">
        <div className="caps text-faint mb-1">Depth 무효화 규칙</div>
        <div className="text-muted whitespace-pre-wrap">{DEPTH_RULES}</div>
      </div>

      <h4 className="caps text-faint mb-2">5.2 Pivot price 계산 규칙</h4>
      <div className="overflow-x-auto">
        <table className="w-full text-data border-collapse">
          <thead>
            <tr className="border-b border-hairline text-faint">
              <th className="text-left py-2 pr-3">Pattern</th>
              <th className="text-left py-2 pr-3">Pivot Formula</th>
              <th className="text-left py-2">Pivot Basis Label</th>
            </tr>
          </thead>
          <tbody>
            {PIVOT_RULES.map((r) => (
              <tr key={r.pattern} className="border-b border-hairline">
                <td className="py-2 pr-3">
                  <code className="num">{r.pattern}</code>
                </td>
                <td className="py-2 pr-3 text-data text-ink num">{r.formula}</td>
                <td className="py-2 text-data-xs text-faint num">{r.basisLabel}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
