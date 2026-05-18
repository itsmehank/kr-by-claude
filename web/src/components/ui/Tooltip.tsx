import { useState, useRef, useLayoutEffect, type ReactNode } from "react";

interface TooltipProps {
  content: ReactNode;
  children: ReactNode;
  maxWidth?: string;
}

export function Tooltip({ content, children, maxWidth = "max-w-md" }: TooltipProps) {
  const [open, setOpen] = useState(false);
  const [placement, setPlacement] = useState<"top" | "bottom">("top");
  const wrapRef = useRef<HTMLSpanElement>(null);
  const tipRef = useRef<HTMLSpanElement>(null);

  useLayoutEffect(() => {
    if (!open || !wrapRef.current || !tipRef.current) return;
    const wrap = wrapRef.current.getBoundingClientRect();
    const tip = tipRef.current.getBoundingClientRect();
    // 위쪽 공간이 부족하면 아래로 배치
    setPlacement(wrap.top < tip.height + 12 ? "bottom" : "top");
  }, [open]);

  return (
    <span
      ref={wrapRef}
      className="relative inline-flex"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
    >
      {children}
      {open && (
        <span
          ref={tipRef}
          role="tooltip"
          className={`absolute left-1/2 -translate-x-1/2 ${
            placement === "top" ? "bottom-full mb-2" : "top-full mt-2"
          } z-50 ${maxWidth} pointer-events-none`}
        >
          <span className="block bg-ink text-paper text-data-xs leading-relaxed rounded-lg px-3 py-2 shadow-bento whitespace-normal min-w-[260px]">
            {content}
          </span>
        </span>
      )}
    </span>
  );
}
