import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { tradeApi } from "../../lib/tradeApi";
import type { SearchHit } from "../../lib/tradeTypes";

export default function SymbolSearch({ onSelect }: { onSelect: (hit: SearchHit) => void }) {
  const [q, setQ] = useState("");
  const hits = useQuery<SearchHit[]>({
    queryKey: ["trade", "search", q],
    queryFn: () => tradeApi<SearchHit[]>(`/search?q=${encodeURIComponent(q)}`),
    enabled: q.trim().length >= 1,
    staleTime: 60_000,
  });
  return (
    <div className="relative">
      <input className="w-full rounded border px-2 py-1 text-sm" placeholder="종목명 또는 코드" value={q} onChange={(e) => setQ(e.target.value)} />
      {q && hits.data && hits.data.length > 0 && (
        <ul className="absolute z-10 mt-1 w-full max-h-60 overflow-auto rounded border bg-white shadow text-sm">
          {hits.data.map((h) => (
            <li key={h.ticker} className="cursor-pointer px-2 py-1 hover:bg-slate-100" onClick={() => { onSelect(h); setQ(""); }}>
              <span className="font-mono">{h.ticker}</span> {h.name} <span className="text-slate-400">{h.market}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
