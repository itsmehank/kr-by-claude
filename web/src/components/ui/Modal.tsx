import { useEffect } from "react";
import { X } from "lucide-react";

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  subtitle?: string;
  children: React.ReactNode;
  maxWidth?: string;
}

export function Modal({
  open,
  onClose,
  title,
  subtitle,
  children,
  maxWidth = "max-w-2xl",
}: ModalProps) {
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 bg-ink/40 backdrop-blur-sm flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className={`bg-paper rounded-2xl shadow-bento-hover w-full ${maxWidth} max-h-[85vh] overflow-hidden flex flex-col animate-in fade-in zoom-in-95 duration-150`}
      >
        {(title || subtitle) && (
          <div className="px-6 py-5 border-b border-hairline flex items-start justify-between gap-4">
            <div className="min-w-0 flex-1">
              {title && (
                <div className="text-headline font-bold text-ink">{title}</div>
              )}
              {subtitle && (
                <div className="text-data-xs text-muted mt-1">{subtitle}</div>
              )}
            </div>
            <button
              onClick={onClose}
              className="text-faint hover:text-ink transition-colors shrink-0"
              aria-label="닫기"
            >
              <X size={20} />
            </button>
          </div>
        )}
        <div className="overflow-y-auto flex-1">{children}</div>
      </div>
    </div>
  );
}
