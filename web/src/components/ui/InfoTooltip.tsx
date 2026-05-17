import * as Tooltip from "@radix-ui/react-tooltip";
import { Info } from "lucide-react";

interface InfoTooltipProps {
  children: React.ReactNode;
  size?: number;
}

export function InfoTooltip({ children, size = 13 }: InfoTooltipProps) {
  return (
    <Tooltip.Provider delayDuration={150} skipDelayDuration={300}>
      <Tooltip.Root>
        <Tooltip.Trigger asChild>
          <button
            type="button"
            className="inline-flex items-center justify-center text-faint hover:text-accent transition-colors ml-1 align-middle"
            aria-label="자세한 설명"
          >
            <Info size={size} strokeWidth={2} />
          </button>
        </Tooltip.Trigger>
        <Tooltip.Portal>
          <Tooltip.Content
            sideOffset={6}
            className="z-50 max-w-xs rounded-xl bg-ink text-paper text-data px-4 py-3 shadow-bento-hover data-[state=delayed-open]:animate-in data-[state=closed]:animate-out fade-in-0 fade-out-0 zoom-in-95 zoom-out-95"
          >
            {children}
            <Tooltip.Arrow className="fill-ink" />
          </Tooltip.Content>
        </Tooltip.Portal>
      </Tooltip.Root>
    </Tooltip.Provider>
  );
}
