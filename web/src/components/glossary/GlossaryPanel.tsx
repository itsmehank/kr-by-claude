import { useEffect, useMemo, useRef, useState } from "react";
import { BookOpenText, ChevronDown, ChevronRight, Search, X } from "lucide-react";
import { GLOSSARY, GLOSSARY_BY_ID } from "../../data/reasoningGlossary";
import { GLOSSARY_CATEGORIES, formatThreshold, type GlossaryEntry } from "../../lib/glossaryTypes";
import { useGlossary } from "./glossaryContext";

const Q_KEY = "kr.glossary.q";

function readQ(): string {
  try {
    return window.localStorage.getItem(Q_KEY) ?? "";
  } catch {
    return "";
  }
}

function matches(e: GlossaryEntry, q: string): boolean {
  return (
    e.title.toLowerCase().includes(q) ||
    e.short.toLowerCase().includes(q) ||
    e.aliases.some((a) => a.toLowerCase().includes(q))
  );
}

function EntryDetail({ entry, onJump }: { entry: GlossaryEntry; onJump: (id: string) => void }) {
  return (
    <div className="mt-1.5 space-y-2 text-data-xs leading-relaxed text-ink">
      <p>{entry.short}</p>
      {entry.thresholds && entry.thresholds.length > 0 && (
        <div>
          <div className="caps text-faint mb-0.5">현재 기준</div>
          <ul className="list-disc ml-4 space-y-0.5">
            {entry.thresholds.map((t) => (
              <li key={t.label}>
                {formatThreshold(t)} <span className="text-faint">({t.source})</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {entry.meaning && (
        <div>
          <div className="caps text-faint mb-0.5">분석에서의 의미</div>
          <p>{entry.meaning}</p>
        </div>
      )}
      {entry.example && (
        <div>
          <div className="caps text-faint mb-0.5">예시</div>
          <p>{entry.example}</p>
        </div>
      )}
      <div>
        <div className="caps text-faint mb-0.5">글에 나오는 표기</div>
        <p className="font-mono text-[11px] text-muted break-words">{entry.aliases.join(" · ")}</p>
      </div>
      {entry.related && entry.related.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {entry.related.map((r) => (
            <button
              key={r}
              type="button"
              onClick={() => onJump(r)}
              className="px-1.5 py-0.5 rounded border border-hairline bg-cream hover:border-accent text-muted hover:text-ink"
            >
              {GLOSSARY_BY_ID[r]?.title ?? r}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** 모든 페이지 공통 — 화면 오른쪽 아래 버튼 + 스크롤을 따라오는 용어 검색 창 */
export function GlossaryPanel() {
  const g = useGlossary();
  const [q, setQ] = useState<string>(readQ);
  const [expanded, setExpanded] = useState<string | null>(null);
  const itemRefs = useRef<Record<string, HTMLLIElement | null>>({});
  const listRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    try {
      window.localStorage.setItem(Q_KEY, q);
    } catch {
      /* 무시 */
    }
  }, [q]);

  // 본문 용어 클릭 → 그 항목 펼치고(렌더 중 파생 갱신) 스크롤(effect)
  const focus = g?.focus ?? null;
  const [seenFocusN, setSeenFocusN] = useState(0);
  if (focus && focus.n !== seenFocusN) {
    setSeenFocusN(focus.n);
    setQ("");
    setExpanded(focus.id);
  }
  useEffect(() => {
    if (!focus) return;
    // scrollIntoView 는 페이지까지 스크롤하므로 창 내부 목록만 직접 스크롤한다
    const raf = requestAnimationFrame(() => {
      const list = listRef.current;
      const el = itemRefs.current[focus.id];
      if (list && el) list.scrollTop = el.offsetTop - 32;
    });
    return () => cancelAnimationFrame(raf);
  }, [focus]);

  const filtered = useMemo(() => {
    const s = q.trim().toLowerCase();
    return s ? GLOSSARY.filter((e) => matches(e, s)) : GLOSSARY;
  }, [q]);

  if (!g) return null;

  const jump = (id: string) => g.openEntry(id);

  const renderItem = (e: GlossaryEntry) => {
    const isOpen = expanded === e.id;
    return (
      <li
        key={e.id}
        ref={(el) => {
          itemRefs.current[e.id] = el;
        }}
        className={`px-3 py-2 border-b border-hairline last:border-b-0 ${isOpen ? "bg-cream" : ""}`}
      >
        <button
          type="button"
          onClick={() => setExpanded(isOpen ? null : e.id)}
          className="flex items-start gap-1 w-full text-left text-data text-ink hover:text-accent"
        >
          <span className="shrink-0 mt-0.5 text-faint">{isOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}</span>
          <span>{e.title}</span>
        </button>
        {isOpen && <EntryDetail entry={e} onJump={jump} />}
      </li>
    );
  };

  return (
    <>
      {g.open && (
        <div
          role="dialog"
          aria-label="용어 사전"
          className="fixed right-4 bottom-16 z-[60] w-80 max-w-[calc(100vw-2rem)] max-h-[70vh] flex flex-col bg-paper border border-hairline rounded-xl shadow-bento-hover"
        >
          <div className="flex items-center gap-2 px-3 py-2 border-b border-hairline">
            <BookOpenText size={14} className="text-faint" />
            <span className="text-data font-semibold text-ink flex-1">용어 사전</span>
            <span className="text-data-xs text-faint num">{filtered.length}개</span>
            <button type="button" aria-label="용어 창 닫기" onClick={() => g.setOpen(false)} className="text-faint hover:text-ink">
              <X size={14} />
            </button>
          </div>
          <div className="px-3 py-2 border-b border-hairline">
            <label className="flex items-center gap-2 px-2 py-1 rounded-lg border border-hairline bg-cream focus-within:border-accent">
              <Search size={13} className="text-faint" />
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="용어 검색 (예: FTD, 분배일, G0)"
                className="flex-1 bg-transparent text-data outline-none placeholder:text-faint"
              />
              {q && (
                <button type="button" aria-label="검색어 지우기" onClick={() => setQ("")} className="text-faint hover:text-ink">
                  <X size={12} />
                </button>
              )}
            </label>
          </div>
          <div ref={listRef} className="relative overflow-y-auto">
            {filtered.length === 0 ? (
              <p className="px-3 py-4 text-data-xs text-muted">'{q}' 에 해당하는 용어가 없습니다.</p>
            ) : q.trim() ? (
              <ul>{filtered.map(renderItem)}</ul>
            ) : (
              GLOSSARY_CATEGORIES.map((cat) => {
                const items = filtered.filter((e) => e.category === cat);
                if (items.length === 0) return null;
                return (
                  <section key={cat}>
                    <div className="sticky top-0 bg-paper/95 px-3 py-1 caps text-faint border-b border-hairline">{cat}</div>
                    <ul>{items.map(renderItem)}</ul>
                  </section>
                );
              })
            )}
          </div>
        </div>
      )}
      <button
        type="button"
        onClick={() => g.setOpen(!g.open)}
        aria-expanded={g.open}
        className="fixed right-4 bottom-4 z-[60] flex items-center gap-1.5 px-3 py-2 rounded-full bg-ink text-paper text-data-xs shadow-bento-hover hover:bg-ink/90"
      >
        <BookOpenText size={14} />
        용어
      </button>
    </>
  );
}
