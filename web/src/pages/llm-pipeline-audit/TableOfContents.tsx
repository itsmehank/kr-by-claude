import { useEffect, useState } from "react";

interface TocItem {
  id: string;
  label: string;
  depth: 0 | 1;
}

const TOC: TocItem[] = [
  { id: "overview", label: "1. 시스템 개요", depth: 0 },
  { id: "schedule", label: "2. 실행 스케줄", depth: 0 },
  { id: "stages", label: "3. 단계별 상세", depth: 0 },
  { id: "stage-weekend", label: "3.1 weekend", depth: 1 },
  { id: "stage-daily-delta", label: "3.2 daily_delta", depth: 1 },
  { id: "stage-evaluate-pivot", label: "3.3 evaluate_pivot", depth: 1 },
  { id: "stage-entry-params", label: "3.4 entry_params", depth: 1 },
  { id: "stage-performance", label: "3.5 performance", depth: 1 },
  { id: "minervini-8", label: "4. Minervini 8조건", depth: 0 },
  { id: "base-patterns", label: "5. Base 패턴 9개", depth: 0 },
  { id: "risk-flags", label: "6. Risk Flags 13개", depth: 0 },
  { id: "zip-payload", label: "7. LLM Payload (ZIP 13)", depth: 0 },
  { id: "prompts", label: "8. Prompt 전체 (3개)", depth: 0 },
  { id: "change-log", label: "9. 비일관성 / 변경 이력", depth: 0 },
];

export function TableOfContents() {
  const [activeId, setActiveId] = useState<string>(TOC[0].id);

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setActiveId(entry.target.id);
            return;
          }
        }
      },
      { rootMargin: "-20% 0px -70% 0px" },
    );

    for (const item of TOC) {
      const el = document.getElementById(item.id);
      if (el) observer.observe(el);
    }
    return () => observer.disconnect();
  }, []);

  return (
    <nav className="sticky top-6 max-h-[calc(100vh-3rem)] overflow-y-auto">
      <div className="caps text-faint mb-3">목차</div>
      <ul className="space-y-1 text-data">
        {TOC.map((item) => (
          <li key={item.id} className={item.depth === 1 ? "pl-3" : ""}>
            <a
              href={`#${item.id}`}
              className={`block py-1 hover:text-accent transition-colors ${
                activeId === item.id ? "text-accent font-semibold" : "text-muted"
              }`}
            >
              {item.label}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
