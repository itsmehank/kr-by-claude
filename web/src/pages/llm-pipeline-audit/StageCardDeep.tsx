import type { StageDetail } from "../../data/llm-pipeline-audit/stages";
import { BookCitation } from "./BookCitation";

interface Props {
  stage: StageDetail;
}

export function StageCardDeep({ stage }: Props) {
  return (
    <div id={`stage-${stage.id}`} className="scroll-mt-20 mb-8">
      <h3 className="text-subhead font-bold text-ink mb-3">
        {stage.num}. {stage.label}
      </h3>

      <Field title="시기" value={stage.schedule} />

      <Field title="입력 필터" code={stage.inputFilter} />
      <div className="text-data-xs text-faint mb-3">
        코드: <code className="num bg-tint-stone px-1 rounded">{stage.inputFilterCodeRef}</code>
      </div>

      {stage.deterministicLogic && (
        <Field title="결정론 로직" code={stage.deterministicLogic} />
      )}

      <Field
        title={`LLM Prompt — ${stage.promptFile}${stage.promptLines > 0 ? ` (${stage.promptLines} 행)` : ""}`}
        value={stage.promptSummary}
      />

      <Field title="출력 — 테이블" value={stage.outputTable} />
      <Field title="출력 — 컬럼" code={stage.outputColumns} />
      <Field title="INSERT 정책" value={stage.insertPolicy} />
      <Field title="Side Effects" value={stage.sideEffects} />

      {stage.bookCitations.length > 0 && (
        <div className="mt-4">
          <h4 className="caps text-faint mb-2">책 근거</h4>
          {stage.bookCitations.map((c, i) => (
            <BookCitation
              key={i}
              book={c.book}
              chapter={c.chapter}
              englishQuote={c.englishQuote}
              koreanSummary={c.koreanSummary}
            />
          ))}
        </div>
      )}

      {stage.codeRefs.length > 0 && (
        <div className="mt-3">
          <h4 className="caps text-faint mb-1">코드 참조</h4>
          <ul className="text-data-xs space-y-0.5">
            {stage.codeRefs.map((ref) => (
              <li key={ref}>
                <code className="num bg-tint-stone px-1.5 py-0.5 rounded">{ref}</code>
              </li>
            ))}
          </ul>
        </div>
      )}

      {stage.notes && (
        <div className="mt-3 p-3 bg-cream border border-hairline rounded-xl text-data-xs text-muted">
          📝 {stage.notes}
        </div>
      )}
    </div>
  );
}

function Field({ title, value, code }: { title: string; value?: string; code?: string }) {
  return (
    <div className="mb-3">
      <h4 className="caps text-faint mb-1">{title}</h4>
      {value && <p className="text-data text-ink leading-relaxed">{value}</p>}
      {code && (
        <pre className="bg-cream border border-hairline rounded-xl p-3 text-data-xs overflow-auto">
          <code className="num">{code}</code>
        </pre>
      )}
    </div>
  );
}
