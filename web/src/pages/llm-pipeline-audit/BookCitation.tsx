import { BookOpen } from "lucide-react";

interface Props {
  book: string;
  chapter?: string;
  page?: string;
  englishQuote: string;
  koreanSummary: string;
  codeRef?: string;
}

export function BookCitation({
  book,
  chapter,
  page,
  englishQuote,
  koreanSummary,
  codeRef,
}: Props) {
  return (
    <div className="bg-cream border border-hairline rounded-xl p-4 my-3">
      <div className="flex items-baseline gap-2 mb-2">
        <BookOpen size={14} className="text-accent shrink-0" strokeWidth={2} />
        <div className="text-data-xs">
          <span className="font-semibold text-ink">{book}</span>
          {chapter && <span className="text-muted">, {chapter}</span>}
          {page && <span className="text-muted">, {page}</span>}
        </div>
      </div>
      <blockquote className="text-data text-ink italic border-l-2 border-accent pl-3 my-2">
        "{englishQuote}"
      </blockquote>
      <div className="text-data text-muted">
        <span className="caps text-faint mr-1">KR</span>
        {koreanSummary}
      </div>
      {codeRef && (
        <div className="mt-2 pt-2 border-t border-hairline text-data-xs">
          <span className="caps text-faint">코드</span>{" "}
          <code className="num bg-tint-stone px-1.5 py-0.5 rounded">{codeRef}</code>
        </div>
      )}
    </div>
  );
}
