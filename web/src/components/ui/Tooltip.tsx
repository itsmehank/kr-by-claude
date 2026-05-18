import { useState, useRef, useLayoutEffect, type ReactNode } from "react";

interface TooltipProps {
  content: ReactNode;
  children: ReactNode;
  maxWidth?: string;
}

type Placement = "top" | "bottom";
type Alignment = "center" | "right" | "left";

export function Tooltip({ content, children, maxWidth = "max-w-md" }: TooltipProps) {
  const [open, setOpen] = useState(false);
  const [placement, setPlacement] = useState<Placement>("top");
  const [alignment, setAlignment] = useState<Alignment>("center");
  const wrapRef = useRef<HTMLSpanElement>(null);
  const tipRef = useRef<HTMLSpanElement>(null);

  useLayoutEffect(() => {
    if (!open || !wrapRef.current || !tipRef.current) return;
    const wrap = wrapRef.current.getBoundingClientRect();
    const tip = tipRef.current.getBoundingClientRect();

    // 수직 — 위쪽 공간이 부족하면 아래로
    setPlacement(wrap.top < tip.height + 12 ? "bottom" : "top");

    // 수평 — 우측 viewport 넘으면 우측 정렬, 좌측 넘으면 좌측 정렬
    const viewportWidth = window.innerWidth;
    const centerX = wrap.left + wrap.width / 2;
    const halfTip = tip.width / 2;
    const margin = 12;
    if (centerX + halfTip > viewportWidth - margin) {
      setAlignment("right");
    } else if (centerX - halfTip < margin) {
      setAlignment("left");
    } else {
      setAlignment("center");
    }
  }, [open]);

  const verticalClass =
    placement === "top" ? "bottom-full mb-2" : "top-full mt-2";
  const horizontalClass =
    alignment === "center"
      ? "left-1/2 -translate-x-1/2"
      : alignment === "right"
      ? "right-0"
      : "left-0";

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
          className={`absolute ${horizontalClass} ${verticalClass} z-50 ${maxWidth} pointer-events-none`}
        >
          <span className="block bg-ink text-paper text-data-xs leading-relaxed rounded-lg px-3 py-2 shadow-bento whitespace-normal min-w-[260px]">
            {content}
          </span>
        </span>
      )}
    </span>
  );
}
