import {
  RISK_FLAGS,
  AUTO_RULES,
  KR_NOTE,
} from "../../data/llm-pipeline-audit/risk-flags";

export function RiskFlagTable() {
  return (
    <div>
      <h4 className="caps text-faint mb-2">6.1 정의</h4>
      <div className="overflow-x-auto mb-4">
        <table className="w-full text-data border-collapse">
          <thead>
            <tr className="border-b border-hairline text-faint">
              <th className="text-left py-2 pr-3">Flag</th>
              <th className="text-left py-2">Definition</th>
            </tr>
          </thead>
          <tbody>
            {RISK_FLAGS.map((f) => (
              <tr key={f.id} className="border-b border-hairline align-top">
                <td className="py-2 pr-3">
                  <code className="num font-semibold text-ink">{f.id}</code>
                </td>
                <td className="py-2 text-data-xs text-muted">{f.definition}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h4 className="caps text-faint mb-2">6.2 시장 컨텍스트 자동 추가 규칙</h4>
      <ul className="mb-4 space-y-2 text-data-xs">
        {AUTO_RULES.map((r, i) => (
          <li key={i} className="flex gap-2">
            <code className="num text-ink font-semibold shrink-0">{r.flag}</code>
            <span className="text-muted">— {r.trigger}</span>
          </li>
        ))}
      </ul>

      <div className="p-3 bg-cream border border-hairline rounded-xl text-data-xs">
        <div className="caps text-faint mb-1">6.3 KR 시장 제약</div>
        <div className="text-muted">{KR_NOTE}</div>
      </div>
    </div>
  );
}
