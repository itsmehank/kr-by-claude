import {
  MINERVINI_CONDITIONS,
  MINERVINI_PASS_FORMULA,
  MINERVINI_PASS_REF,
  NAN_POLICY,
  WEEKLY_MINERVINI_NOTE,
} from "../../data/llm-pipeline-audit/minervini";

export function ConditionTable() {
  return (
    <div>
      <div className="mb-4">
        <h4 className="caps text-faint mb-1">minervini_pass 정의</h4>
        <pre className="bg-cream border border-hairline rounded-xl p-3 text-data-xs overflow-auto">
          <code className="num">{MINERVINI_PASS_FORMULA}</code>
        </pre>
        <div className="text-data-xs text-faint mt-1">
          코드: <code className="num">{MINERVINI_PASS_REF}</code>
        </div>
      </div>

      <h4 className="caps text-faint mb-2">8 조건 표</h4>
      <div className="overflow-x-auto">
        <table className="w-full text-data border-collapse">
          <thead>
            <tr className="border-b border-hairline text-faint">
              <th className="text-left py-2 pr-3">#</th>
              <th className="text-left py-2 pr-3">한국어 정의</th>
              <th className="text-left py-2 pr-3">임계</th>
              <th className="text-left py-2 pr-3">코드</th>
              <th className="text-left py-2">책 원문 (영어)</th>
            </tr>
          </thead>
          <tbody>
            {MINERVINI_CONDITIONS.map((c) => (
              <tr key={c.num} className="border-b border-hairline align-top">
                <td className="py-2 pr-3 num text-faint">{c.num}</td>
                <td className="py-2 pr-3 num text-ink">{c.korean}</td>
                <td className="py-2 pr-3 num">{c.threshold}</td>
                <td className="py-2 pr-3">
                  <code className="num text-data-xs bg-tint-stone px-1 rounded">{c.codeRef}</code>
                </td>
                <td className="py-2 text-data-xs text-muted">
                  <div>"{c.englishOriginal}"</div>
                  {c.note && <div className="mt-1 text-faint italic">{c.note}</div>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-4 p-3 bg-cream border border-hairline rounded-xl text-data-xs">
        <div className="caps text-faint mb-1">NaN 처리</div>
        <div className="text-muted whitespace-pre-wrap">{NAN_POLICY}</div>
      </div>

      <div className="mt-3 p-3 bg-cream border border-hairline rounded-xl text-data-xs">
        <div className="caps text-faint mb-1">주봉 (weekly) Minervini</div>
        <div className="text-muted whitespace-pre-wrap">{WEEKLY_MINERVINI_NOTE}</div>
      </div>
    </div>
  );
}
