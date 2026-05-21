import { useEffect } from "react";
import { X } from "lucide-react";
import type { SimModal } from "../../data/llm-pipeline-simulation";

interface Props {
  open: boolean;
  modal: SimModal | null;
  onClose: () => void;
}

export function SimulationModal({ open, modal, onClose }: Props) {
  // ESC 키 닫기
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open || !modal) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40"
      onClick={onClose}
    >
      <div
        className="bg-paper border border-hairline rounded-2xl shadow-bento-hover max-w-3xl w-full max-h-[85vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between px-6 py-4 border-b border-hairline sticky top-0 bg-paper">
          <h3 className="text-subhead font-bold text-ink">{modal.title}</h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="닫기"
            className="p-1 rounded hover:bg-stone-100 text-muted"
          >
            <X size={18} />
          </button>
        </header>

        <div className="px-6 py-5 grid grid-cols-1 md:grid-cols-2 gap-6">
          <section>
            <h4 className="caps text-faint mb-2">LLM 입력 (요약)</h4>
            <dl className="space-y-2 text-data">
              {modal.inputs.map((row) => (
                <div key={row.label}>
                  <dt className="text-data-xs text-faint">{row.label}</dt>
                  <dd className="text-ink num">{row.value}</dd>
                </div>
              ))}
            </dl>
          </section>

          <section>
            <h4 className="caps text-faint mb-2">LLM 출력</h4>
            <dl className="space-y-2 text-data">
              {modal.outputs.map((row) => (
                <div key={row.label}>
                  <dt className="text-data-xs text-faint">{row.label}</dt>
                  <dd className="text-ink num">{row.value}</dd>
                </div>
              ))}
            </dl>
          </section>
        </div>

        <div className="px-6 pb-5">
          <h4 className="caps text-faint mb-2">Reasoning</h4>
          <p className="text-data text-ink leading-relaxed">{modal.reasoning}</p>
        </div>

        <div className="px-6 pb-6">
          <h4 className="caps text-faint mb-2">이 결과의 영향</h4>
          <p className="text-data text-muted leading-relaxed">{modal.impact}</p>
        </div>
      </div>
    </div>
  );
}
