import type { ReactNode } from "react";

export function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="bg-paper border border-hairline rounded-xl p-4 shadow-bento">
      <h3 className="caps text-faint mb-3">{title}</h3>
      {children}
    </div>
  );
}
