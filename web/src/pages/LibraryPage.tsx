import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight, ExternalLink, FileText } from "lucide-react";
import { LIBRARY_DOCS, LIBRARY_TITLE_BY_FILE, type LibraryDoc } from "../data/library";

const KIND_BADGE: Record<LibraryDoc["kind"], string> = {
  해설: "bg-sky-100 text-sky-800",
  검증: "bg-amber-100 text-amber-800",
  소설: "bg-rose-100 text-rose-800",
  "창작 자료": "bg-violet-100 text-violet-800",
  시뮬레이터: "bg-emerald-100 text-emerald-800",
};

function docUrl(file: string) {
  return `/library/${file}`;
}

function DocCard({ doc }: { doc: LibraryDoc }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="bg-paper rounded-xl shadow-bento overflow-hidden">
      <div className="flex items-start gap-3 px-4 py-3">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="mt-0.5 p-0.5 rounded text-faint hover:text-ink transition-colors shrink-0"
          aria-label={open ? "목적 접기" : "목적 펼치기"}
          aria-expanded={open}
        >
          {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        </button>
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <a
              href={docUrl(doc.file)}
              target="_blank"
              rel="noreferrer"
              className="text-subhead font-semibold hover:text-accent hover:underline inline-flex items-center gap-1.5"
            >
              {doc.title}
              <ExternalLink size={13} className="text-faint shrink-0" />
            </a>
            <span
              className={`text-data-xs px-1.5 py-0.5 rounded-md font-medium ${KIND_BADGE[doc.kind]}`}
            >
              {doc.kind}
            </span>
            {doc.markdown && (
              <span className="text-data-xs px-1.5 py-0.5 rounded-md bg-slate-100 text-slate-600 inline-flex items-center gap-1">
                <FileText size={11} /> markdown 원문
              </span>
            )}
            {doc.superseded && (
              <span className="text-data-xs px-1.5 py-0.5 rounded-md bg-slate-200 text-slate-600">
                중간본 — 최신은{" "}
                <a
                  href={docUrl(doc.superseded)}
                  target="_blank"
                  rel="noreferrer"
                  className="underline"
                >
                  {LIBRARY_TITLE_BY_FILE[doc.superseded]}
                </a>
              </span>
            )}
          </div>
          <div className="text-data-xs text-faint mt-1">
            생성 {doc.created} · 최종 업데이트 {doc.updated} (KST)
          </div>
          {open && (
            <div className="mt-3 pt-3 border-t border-hairline space-y-3">
              <div>
                <div className="caps text-faint mb-1.5">
                  이 문서의 목적 — 실제 요청 근거
                </div>
                <div className="space-y-2 text-body text-muted leading-relaxed">
                  {doc.purpose.map((p, i) => (
                    <p key={i}>{p}</p>
                  ))}
                </div>
              </div>
              {doc.relations.length > 0 && (
                <div>
                  <div className="caps text-faint mb-1.5">연관 문서</div>
                  <ul className="space-y-1.5 text-body">
                    {doc.relations.map((r) => (
                      <li key={r.file} className="flex gap-2">
                        <span className="text-faint shrink-0">↳</span>
                        <span className="min-w-0">
                          <a
                            href={docUrl(r.file)}
                            target="_blank"
                            rel="noreferrer"
                            className="font-medium text-accent hover:underline"
                          >
                            {LIBRARY_TITLE_BY_FILE[r.file] ?? r.file}
                          </a>
                          <span className="text-muted"> — {r.how}</span>
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function LibraryPage() {
  // 최종 업데이트 날짜(내림차순) 기준 그룹핑
  const groups = useMemo(() => {
    const byDate = new Map<string, LibraryDoc[]>();
    for (const doc of LIBRARY_DOCS) {
      const date = doc.updated.slice(0, 10);
      if (!byDate.has(date)) byDate.set(date, []);
      byDate.get(date)!.push(doc);
    }
    return Array.from(byDate.entries())
      .map(([date, docs]) => ({
        date,
        docs: docs.sort((a, b) => b.updated.localeCompare(a.updated)),
      }))
      .sort((a, b) => b.date.localeCompare(a.date));
  }, []);

  return (
    <div className="px-8 py-6 max-w-4xl">
      <h1 className="font-display text-display-md font-bold mb-2">자료실</h1>
      <p className="text-body text-muted leading-relaxed mb-6">
        백테스트 해설 → 오닐·미너비니 전문 AI 자문 검증 → 무협 소설·시뮬레이터로
        이어진 교육 콘텐츠 시리즈(2026-07). 제목을 클릭하면 새 탭에서 열립니다.
        각 항목을 펼치면 문서가 만들어진 목적(과거 세션의 실제 요청 근거)과 연관
        문서를 볼 수 있고, 문서 자체의 상단에도 같은 내용의 접이식 헤더가
        들어있습니다.
      </p>
      <div className="space-y-8">
        {groups.map(({ date, docs }) => (
          <section key={date}>
            <div className="flex items-baseline gap-2 mb-3">
              <h2 className="font-display text-headline font-bold num">{date}</h2>
              <span className="text-data-xs text-faint">
                문서 {docs.length}건 · 최종 업데이트 기준
              </span>
            </div>
            <div className="space-y-2.5">
              {docs.map((doc) => (
                <DocCard key={doc.file} doc={doc} />
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}
