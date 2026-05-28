import { useEffect, useRef, useState } from "react";

interface MermaidDiagramProps {
  /** Mermaid diagram source (e.g., "graph LR\n  A --> B"). */
  chart: string;
  /** Optional id prefix (used for unique SVG id when multiple diagrams on one page). */
  idPrefix?: string;
}

type MermaidInstance = typeof import("mermaid")["default"];

let _mermaidPromise: Promise<MermaidInstance> | null = null;

function loadMermaid(): Promise<MermaidInstance> {
  if (!_mermaidPromise) {
    _mermaidPromise = import("mermaid").then((mod) => {
      mod.default.initialize({
        startOnLoad: false,
        theme: "neutral",
        flowchart: { useMaxWidth: true, htmlLabels: true },
        themeVariables: {
          fontFamily: "inherit",
        },
      });
      return mod.default;
    });
  }
  return _mermaidPromise;
}

export function MermaidDiagram({ chart, idPrefix = "mermaid" }: MermaidDiagramProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const idRef = useRef(`${idPrefix}-${Math.random().toString(36).slice(2)}`);

  useEffect(() => {
    let cancelled = false;
    loadMermaid()
      .then(async (mermaid) => {
        if (cancelled || !ref.current) return;
        try {
          const { svg } = await mermaid.render(idRef.current, chart);
          if (cancelled || !ref.current) return;
          ref.current.innerHTML = svg;
          setError(null);
        } catch (e) {
          setError(String(e));
        }
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [chart]);

  if (error) {
    return (
      <div className="text-danger text-data-xs num bg-paper border border-hairline rounded-lg p-3">
        Mermaid 렌더 실패: {error}
      </div>
    );
  }
  return <div ref={ref} className="mermaid-container overflow-x-auto" />;
}
