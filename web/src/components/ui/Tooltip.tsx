import { useState, type ReactNode } from "react";

interface TooltipProps {
  content: ReactNode;
  children: ReactNode;
  maxWidth?: string;
}

export function Tooltip({ content, children, maxWidth = "max-w-xs" }: TooltipProps) {
  const [open, setOpen] = useState(false);

  return (
    <span
      className="relative inline-flex"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
    >
      {children}
      {open && (
        <span
          role="tooltip"
          className={`absolute left-1/2 -translate-x-1/2 bottom-full mb-2 z-50 ${maxWidth} pointer-events-none`}
        >
          <span className="block bg-ink text-paper text-data-xs leading-relaxed rounded-lg px-3 py-2 shadow-bento whitespace-normal">
            {content}
          </span>
        </span>
      )}
    </span>
  );
}
