interface SkeletonProps {
  width?: string | number;
  height?: string | number;
  className?: string;
  rounded?: "md" | "lg" | "xl" | "2xl" | "full";
}

export function Skeleton({
  width,
  height,
  className = "",
  rounded = "md",
}: SkeletonProps) {
  const radiusClass = {
    md: "rounded-md",
    lg: "rounded-lg",
    xl: "rounded-xl",
    "2xl": "rounded-2xl",
    full: "rounded-full",
  }[rounded];
  return (
    <div
      className={`bg-tint-stone animate-pulse ${radiusClass} ${className}`}
      style={{
        width: typeof width === "number" ? `${width}px` : width,
        height: typeof height === "number" ? `${height}px` : height,
      }}
    />
  );
}

export function SkeletonRow({ cols = 5 }: { cols?: number }) {
  return (
    <div className="flex items-center gap-4 py-3">
      {Array.from({ length: cols }).map((_, i) => (
        <Skeleton
          key={i}
          height={14}
          className={i === 0 ? "w-16" : "flex-1"}
        />
      ))}
    </div>
  );
}

export function SkeletonText({
  lines = 1,
  className = "",
}: {
  lines?: number;
  className?: string;
}) {
  return (
    <div className={`space-y-2 ${className}`}>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          height={14}
          width={i === lines - 1 ? "60%" : "100%"}
        />
      ))}
    </div>
  );
}
