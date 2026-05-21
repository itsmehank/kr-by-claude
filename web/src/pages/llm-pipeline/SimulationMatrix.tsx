import type {
  SimCell,
  SimClassification,
  SimDay,
  SimRow,
} from "../../data/llm-pipeline-simulation";

interface Props {
  days: SimDay[];
  rows: SimRow[];
  onCellClick: (row: SimRow, day: SimDay) => void;
}

const CLASS_STYLE: Record<SimClassification, { bg: string; emoji: string; label: string }> = {
  entry:  { bg: "bg-green-100 border-green-300",   emoji: "🟢", label: "entry" },
  watch:  { bg: "bg-yellow-100 border-yellow-300", emoji: "🟡", label: "watch" },
  ignore: { bg: "bg-gray-200 border-gray-300",     emoji: "⬜", label: "ignore" },
};

const DECISION_BADGE: Record<string, { emoji: string; title: string }> = {
  go_now: { emoji: "✨", title: "go_now (즉시 매수)" },
  wait:   { emoji: "⏸",  title: "wait (보류)" },
  abort:  { emoji: "⚠️", title: "abort (베이스 무효화)" },
};

function CellContent({ cell }: { cell: SimCell }) {
  if (cell.notIncluded) {
    return <span className="text-faint text-data-xs">결정론 미통과</span>;
  }

  const cls = cell.classification;
  const style = cls ? CLASS_STYLE[cls] : null;
  const badge = cell.decision ? DECISION_BADGE[cell.decision] : null;

  return (
    <div className="flex items-center justify-between gap-1">
      <div className="flex items-center gap-1">
        {style && (
          <>
            <span>{style.emoji}</span>
            <span className="text-data-xs">{style.label}</span>
          </>
        )}
        {cell.trigger && (
          <span className="text-faint text-data-xs ml-1">{cell.trigger}</span>
        )}
        {cell.newlyDiscovered && (
          <span
            className="text-data-xs bg-blue-100 text-blue-700 px-1 rounded ml-1"
            title="daily_delta 신규 분류"
          >
            ⚡
          </span>
        )}
      </div>
      {badge && (
        <span className="text-data-xs" title={badge.title}>
          {badge.emoji}
        </span>
      )}
    </div>
  );
}

function Legend() {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-data-xs text-muted mb-3">
      <span>🟢 entry</span>
      <span>🟡 watch</span>
      <span>⬜ ignore</span>
      <span className="text-faint">|</span>
      <span>✨ go_now</span>
      <span>⏸ wait</span>
      <span>⚠️ abort</span>
      <span className="text-faint">|</span>
      <span>⚡ daily_delta 신규</span>
      <span>W weekend 재분석</span>
    </div>
  );
}

export function SimulationMatrix({ days, rows, onCellClick }: Props) {
  return (
    <div>
      <Legend />
      <div className="overflow-x-auto">
        <table className="w-full text-data border-collapse">
          <thead>
            <tr>
              <th className="text-left py-2 pr-3 caps text-faint">종목</th>
              {days.map((d) => (
                <th
                  key={d.date}
                  className="text-left py-2 px-2 caps text-faint border-l border-hairline"
                >
                  <div className="font-semibold text-ink">{d.label}</div>
                  <div className="num text-data-xs text-faint">{d.date}</div>
                  {d.stage && (
                    <div className="text-data-xs text-muted">
                      {d.stage === "weekend"
                        ? "weekend"
                        : d.stage === "daily-pipeline"
                          ? "full-daily"
                          : d.stage === "market-closed"
                            ? "휴장"
                            : ""}
                    </div>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.symbol} className="border-t border-hairline">
                <td className="py-2 pr-3 align-top">
                  <div className="num font-semibold text-ink">{row.symbol}</div>
                  {row.note && (
                    <div className="text-data-xs text-faint mt-0.5">{row.note}</div>
                  )}
                </td>
                {days.map((d) => {
                  const cell = row.cells[d.date];
                  const hasContent =
                    cell &&
                    (cell.classification ||
                      cell.trigger ||
                      cell.notIncluded);
                  const style = cell?.classification
                    ? CLASS_STYLE[cell.classification].bg
                    : cell?.notIncluded
                      ? "bg-stone-50"
                      : "";
                  const clickable = hasContent && cell?.modal;
                  return (
                    <td
                      key={d.date}
                      onClick={() => clickable && cell && onCellClick(row, d)}
                      className={`py-2 px-2 align-top border-l border-hairline relative ${style} ${clickable ? "cursor-pointer hover:opacity-80" : ""}`}
                    >
                      {cell?.reanalyzed && (
                        <span
                          className="absolute top-0.5 left-0.5 text-data-xs bg-violet-100 text-violet-700 px-1 rounded"
                          title="weekend 재분석"
                        >
                          W
                        </span>
                      )}
                      {cell ? <CellContent cell={cell} /> : <span className="text-faint">—</span>}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
