import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { api } from "../lib/api";
import type { Stock } from "../lib/types";

interface StockSearchProps {
  onSelect: (ticker: string) => void;
  placeholder?: string;
}

export function StockSearch({ onSelect, placeholder }: StockSearchProps) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);

  // PromptPage 의 StockPicker 와 같은 queryKey → 캐시 공유.
  const stocksQ = useQuery<Stock[]>({
    queryKey: ["stocks-all"],
    queryFn: () => api<Stock[]>("/stocks?limit=10000"),
    staleTime: 5 * 60 * 1000,
  });

  const filtered = useMemo(() => {
    if (!stocksQ.data) return [];
    const q = query.trim().toLowerCase();
    if (!q) return stocksQ.data.slice(0, 20);
    return stocksQ.data
      .filter(
        (s) =>
          s.ticker.toLowerCase().includes(q) ||
          s.name.toLowerCase().includes(q)
      )
      .slice(0, 20);
  }, [stocksQ.data, query]);

  const handleSelect = (ticker: string) => {
    setQuery("");
    setOpen(false);
    onSelect(ticker);
  };

  return (
    <div className="relative w-72">
      <div className="relative">
        <Search
          size={16}
          className="absolute left-3 top-1/2 -translate-y-1/2 text-faint pointer-events-none"
        />
        <input
          type="text"
          value={query}
          placeholder={placeholder ?? "코드 또는 종목명 (예: 000660, 하이닉스)"}
          className="w-full border border-hairline rounded-lg pl-10 pr-3 py-2 text-data bg-cream focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent"
          onFocus={() => setOpen(true)}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && filtered.length > 0) {
              e.preventDefault();
              handleSelect(filtered[0].ticker);
            }
          }}
        />
      </div>

      {open && (
        <div className="absolute z-10 mt-1.5 w-full bg-paper border border-hairline rounded-xl shadow-bento overflow-hidden max-h-64 overflow-y-auto">
          {stocksQ.isError && (
            <div className="px-4 py-3 text-data text-danger">목록 오류</div>
          )}
          {!stocksQ.isError && filtered.length === 0 && (
            <div className="px-4 py-3 text-data text-muted">검색 결과 없음</div>
          )}
          {filtered.map((s) => (
            <button
              key={s.ticker}
              type="button"
              className="w-full flex items-center gap-3 px-4 py-2.5 text-left hover:bg-tint-blue transition-colors"
              onClick={() => handleSelect(s.ticker)}
            >
              <span className="num text-data text-accent font-semibold w-20 shrink-0">
                {s.ticker}
              </span>
              <span className="text-data text-ink truncate">{s.name}</span>
              <span className="ml-auto text-data-xs text-faint shrink-0">
                {s.market}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
